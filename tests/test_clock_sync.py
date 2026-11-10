"""Tests for the controller clock sync: helpers, manager, HA client, entities."""

import json
import logging
from datetime import (
    UTC,
    date,
    datetime,
    time,
    timedelta,
)
from pathlib import Path
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)
from zoneinfo import ZoneInfo

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from custom_components.homeworks_hwi import clock_sync
from custom_components.homeworks_hwi.client import (
    HomeworksClient,
    HomeworksClientConfig,
)
from custom_components.homeworks_hwi.clock_sync import (
    ClockSyncManager,
    ClockSyncSettings,
    dst_job_run_time,
    find_next_transition,
    is_repeated_fall_back_hour,
    is_scheduled_day,
    offset_seconds,
)
from custom_components.homeworks_hwi.const import (
    CLOCK_REPLY_TIMEOUT_S,
    CLOCK_SYNC_FREQ_MONTHLY_FIRST,
    CLOCK_SYNC_FREQ_WEEKLY,
    CLOCK_SYNC_TZ_AUTO,
    CLOCK_SYNC_WEEKDAYS,
    CONF_CLOCK_SYNC_ENABLED,
    CONF_CLOCK_SYNC_MANAGE_DST,
    CONF_CONTROLLER_ID,
    DOMAIN,
    DST_JOB_SETTLE,
)
from custom_components.homeworks_hwi.hwi_protocol import (
    HomeworksException,
    HomeworksTimeout,
    ProcessorDateMessage,
    ProcessorTimeMessage,
)
from custom_components.homeworks_hwi.models import ClockReading

pytestmark = pytest.mark.requires_ha

CHICAGO = ZoneInfo("America/Chicago")
PHOENIX = ZoneInfo("America/Phoenix")
LORD_HOWE = ZoneInfo("Australia/Lord_Howe")
# 17:17:41 CST in Chicago, a Tuesday with no DST
NOW = datetime(2026, 11, 10, 23, 17, 41, tzinfo=UTC)
# 01:30 CST, the second pass of the repeated hour in Chicago
REPEATED_HOUR_SECOND_PASS = datetime(2027, 11, 7, 7, 30, tzinfo=UTC)
SUNDAY = CLOCK_SYNC_WEEKDAYS.index("sun")
INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN


def _reading(offset_s: float, *, dst: bool | None = False, now=NOW) -> ClockReading:
    """Return a controller reading that is offset_s ahead of HA at now."""
    wall = now.astimezone(CHICAGO).replace(tzinfo=None)
    return ClockReading(
        controller=wall + timedelta(seconds=offset_s), received_utc=now, dst=dst
    )


# =============================================================================
# Pure helpers
# =============================================================================


class TestFindNextTransition:
    """find_next_transition steps and bisects to the exact second."""

    def test_chicago_spring_forward(self):
        """From 2026-11-10 the next change is 2027-03-14 08:00 UTC (-6 h to -5 h)."""
        transition = find_next_transition(CHICAGO, NOW)
        assert transition.at_utc == datetime(2027, 3, 14, 8, 0, tzinfo=UTC)
        assert transition.offset_before == timedelta(hours=-6)
        assert transition.offset_after == timedelta(hours=-5)

    def test_chicago_fall_back(self):
        """From 2027-03-15 the next change is 2027-11-07 07:00 UTC (-5 h to -6 h)."""
        transition = find_next_transition(CHICAGO, datetime(2027, 3, 15, tzinfo=UTC))
        assert transition.at_utc == datetime(2027, 11, 7, 7, 0, tzinfo=UTC)
        assert transition.offset_before == timedelta(hours=-5)
        assert transition.offset_after == timedelta(hours=-6)

    @pytest.mark.parametrize("zone", ["UTC", "America/Phoenix"])
    def test_zone_without_dst(self, zone):
        """A zone with no DST has no transition."""
        assert find_next_transition(ZoneInfo(zone), NOW) is None

    def test_lord_howe_half_hour_change(self):
        """Lord Howe changes its offset by 30 minutes."""
        transition = find_next_transition(LORD_HOWE, NOW)
        change = transition.offset_before - transition.offset_after
        assert abs(change) == timedelta(minutes=30)


class TestDstJobRunTime:
    """The DST job runs after the repeated window, plus the settle time."""

    def test_chicago_fall_back(self):
        """02:05 CST, 5 min after the repeated hour."""
        transition = find_next_transition(CHICAGO, datetime(2027, 3, 15, tzinfo=UTC))
        assert dst_job_run_time(transition) == datetime(2027, 11, 7, 8, 5, tzinfo=UTC)

    def test_chicago_spring_forward(self):
        """03:05 CDT, 5 min after the jump."""
        transition = find_next_transition(CHICAGO, NOW)
        assert dst_job_run_time(transition) == datetime(2027, 3, 14, 8, 5, tzinfo=UTC)

    def test_lord_howe_fall_back(self):
        """Transition plus the 30 min repeated window plus 5 min."""
        transition = find_next_transition(LORD_HOWE, NOW)
        assert transition.offset_before > transition.offset_after
        assert dst_job_run_time(transition) == transition.at_utc + timedelta(minutes=35)
        assert DST_JOB_SETTLE == timedelta(minutes=5)


class TestIsRepeatedFallBackHour:
    """Only the second pass of the repeated hour is detected."""

    def test_first_pass(self):
        """01:30 CDT, the first pass, is not detected."""
        local = datetime(2027, 11, 7, 6, 30, tzinfo=UTC).astimezone(CHICAGO)
        assert is_repeated_fall_back_hour(local) is False

    def test_second_pass(self):
        """01:30 CST, the second pass, is detected."""
        local = REPEATED_HOUR_SECOND_PASS.astimezone(CHICAGO)
        assert is_repeated_fall_back_hour(local) is True

    def test_after_repeated_hour(self):
        """02:30 CST is not detected."""
        local = datetime(2027, 11, 7, 8, 30, tzinfo=UTC).astimezone(CHICAGO)
        assert is_repeated_fall_back_hour(local) is False

    @pytest.mark.parametrize("hour", range(0, 24, 3))
    def test_phoenix_never(self, hour):
        """A zone without DST never has a repeated hour."""
        local = datetime(2027, 11, 7, hour, 30, tzinfo=UTC).astimezone(PHOENIX)
        assert is_repeated_fall_back_hour(local) is False


class TestIsScheduledDay:
    """Weekly and monthly-first schedules."""

    def test_weekly(self):
        """Weekly Sunday matches 2026-11-15, not 2026-11-16."""
        assert is_scheduled_day(date(2026, 11, 15), CLOCK_SYNC_FREQ_WEEKLY, SUNDAY)
        assert not is_scheduled_day(date(2026, 11, 16), CLOCK_SYNC_FREQ_WEEKLY, SUNDAY)

    def test_monthly_first(self):
        """Monthly-first Sunday matches 2026-11-01, not 2026-11-08."""
        assert is_scheduled_day(
            date(2026, 11, 1), CLOCK_SYNC_FREQ_MONTHLY_FIRST, SUNDAY
        )
        assert not is_scheduled_day(
            date(2026, 11, 8), CLOCK_SYNC_FREQ_MONTHLY_FIRST, SUNDAY
        )


class TestOffsetSeconds:
    """Controller wall time minus HA wall time."""

    def test_controller_behind(self):
        """Controller 17:09:29 against HA 17:17:41 local is -492 s."""
        reading = ClockReading(
            controller=datetime(2026, 11, 10, 17, 9, 29), received_utc=NOW, dst=None
        )
        assert offset_seconds(reading, CHICAGO) == -492

    def test_second_pass_of_repeated_hour(self):
        """A reading on the second pass compares against CST wall time."""
        reading = ClockReading(
            controller=datetime(2027, 11, 7, 1, 30, 5),
            received_utc=REPEATED_HOUR_SECOND_PASS,
            dst=False,
        )
        assert offset_seconds(reading, CHICAGO) == 5


def test_settings_defaults():
    """Missing options give the documented defaults."""
    assert ClockSyncSettings.from_options({}) == ClockSyncSettings(
        enabled=False,
        timezone=CLOCK_SYNC_TZ_AUTO,
        frequency=CLOCK_SYNC_FREQ_WEEKLY,
        weekday=SUNDAY,
        time_of_day=time(4, 0, 0),
        manage_dst=False,
    )


# =============================================================================
# ClockSyncManager
# =============================================================================


def _make_manager(options=None, connected=True):
    """Return a manager with a mocked hass, entry, coordinator, and client."""
    hass = MagicMock()
    hass.config.time_zone = "America/Chicago"
    entry = MagicMock()
    entry.options = {CONF_CONTROLLER_ID: "test_controller", **(options or {})}
    client = MagicMock()
    client.read_clock = AsyncMock(side_effect=[_reading(-492), _reading(0)])
    client.set_clock = AsyncMock()
    client.read_dst = AsyncMock(return_value=False)
    client.send_dst = AsyncMock(return_value=True)
    coordinator = MagicMock()
    coordinator.client = client
    coordinator.connected = connected
    coordinator.controller_id = "test_controller"
    return ClockSyncManager(hass, entry, coordinator), client, entry


@pytest.fixture
def frozen_now():
    """Freeze clock_sync's utcnow at NOW."""
    with patch.object(clock_sync.dt_util, "utcnow", return_value=NOW) as mock_now:
        yield mock_now


class TestManagerSync:
    """async_sync with a mocked client."""

    async def test_call_order(self, frozen_now):
        """Read, set, read, and set_clock gets a callable."""
        manager, client, _ = _make_manager()
        await manager.async_sync(raise_errors=True)
        assert [name for name, _, _ in client.mock_calls] == [
            "read_clock",
            "set_clock",
            "read_clock",
        ]
        assert callable(client.set_clock.await_args.args[0])

    async def test_disconnected_scheduled_sets_pending(self, frozen_now):
        """A scheduled run while disconnected becomes pending."""
        manager, client, _ = _make_manager(connected=False)
        await manager.async_sync(raise_errors=False)
        assert manager._pending is True
        client.read_clock.assert_not_awaited()

    async def test_disconnected_button_raises(self, frozen_now):
        """A button press while disconnected raises not_connected."""
        manager, _, _ = _make_manager(connected=False)
        with pytest.raises(HomeAssistantError) as exc_info:
            await manager.async_sync(raise_errors=True)
        assert exc_info.value.translation_key == "not_connected"
        assert manager._pending is False

    def test_pending_runs_once_on_reconnect(self):
        """The coordinator listener runs the pending sync once."""
        manager, _, entry = _make_manager()
        manager._pending = True
        manager._handle_coordinator_update()
        manager._handle_coordinator_update()
        assert entry.async_create_background_task.call_count == 1
        assert manager._pending is False
        entry.async_create_background_task.call_args.args[1].close()

    async def test_repeated_hour_scheduled_skips(self, caplog):
        """A scheduled run in the repeated hour skips and logs a WARNING."""
        manager, client, _ = _make_manager()
        with (
            patch.object(
                clock_sync.dt_util, "utcnow", return_value=REPEATED_HOUR_SECOND_PASS
            ),
            caplog.at_level(logging.WARNING),
        ):
            await manager.async_sync(raise_errors=False)
        client.set_clock.assert_not_awaited()
        assert any(
            r.levelno == logging.WARNING and "repeated fall-back hour" in r.message
            for r in caplog.records
        )
        assert manager._pending is False

    async def test_repeated_hour_button_raises(self):
        """A button press in the repeated hour raises a translated error."""
        manager, client, _ = _make_manager()
        with (
            patch.object(
                clock_sync.dt_util, "utcnow", return_value=REPEATED_HOUR_SECOND_PASS
            ),
            pytest.raises(HomeAssistantError) as exc_info,
        ):
            await manager.async_sync(raise_errors=True)
        assert exc_info.value.translation_key == "clock_repeated_fall_back_hour"
        client.set_clock.assert_not_awaited()

    async def test_large_post_offset_retries_once(self, frozen_now):
        """A post offset of 3 s retries the set once."""
        manager, client, _ = _make_manager()
        client.read_clock.side_effect = [_reading(-492), _reading(3), _reading(3)]
        await manager.async_sync(raise_errors=True)
        assert client.set_clock.await_count == 2

    async def test_small_post_offset_does_not_retry(self, frozen_now):
        """A post offset of 1 s does not retry."""
        manager, client, _ = _make_manager()
        client.read_clock.side_effect = [_reading(-492), _reading(1)]
        await manager.async_sync(raise_errors=True)
        assert client.set_clock.await_count == 1

    async def test_manual_dst_rejected_stops_dst_commands(self, frozen_now):
        """A rejected DST command disables the DST step until reload."""
        manager, client, _ = _make_manager({CONF_CLOCK_SYNC_MANAGE_DST: True})
        client.read_dst.return_value = True  # Controller DST on, zone off at NOW
        client.send_dst.return_value = False
        await manager.async_sync(raise_errors=True)
        client.send_dst.assert_awaited_once_with(
            start=False, timeout=CLOCK_REPLY_TIMEOUT_S
        )
        assert manager._manual_dst_rejected is True

        client.read_dst.reset_mock()
        client.read_clock.side_effect = [_reading(0), _reading(0)]
        await manager.async_sync(raise_errors=True)
        client.read_dst.assert_not_awaited()

    async def test_matching_dst_sends_no_command(self, frozen_now):
        """No DST command is sent when RDST matches the zone."""
        manager, client, _ = _make_manager({CONF_CLOCK_SYNC_MANAGE_DST: True})
        await manager.async_sync(raise_errors=True)
        client.read_dst.assert_awaited_once()
        client.send_dst.assert_not_awaited()

    async def test_manage_dst_off_skips_dst(self, frozen_now):
        """With manage DST off, no DST command is read or sent."""
        manager, client, _ = _make_manager()
        await manager.async_sync(raise_errors=True)
        client.read_dst.assert_not_awaited()
        client.send_dst.assert_not_awaited()

    async def test_timeout_keeps_values(self, frozen_now):
        """A reply timeout leaves last_sync and last_offset unchanged."""
        manager, client, _ = _make_manager()
        manager.last_sync = NOW - timedelta(days=7)
        manager.last_offset = 4
        client.read_clock.side_effect = HomeworksTimeout("RST2")
        await manager.async_sync(raise_errors=False)
        assert manager.last_sync == NOW - timedelta(days=7)
        assert manager.last_offset == 4
        assert manager._pending is False

    async def test_timeout_button_raises(self, frozen_now):
        """A button press with a reply timeout raises clock_reply_timeout."""
        manager, client, _ = _make_manager()
        client.read_clock.side_effect = HomeworksTimeout("RST2")
        with pytest.raises(HomeAssistantError) as exc_info:
            await manager.async_sync(raise_errors=True)
        assert exc_info.value.translation_key == "clock_reply_timeout"
        assert exc_info.value.translation_placeholders == {"command": "RST2"}

    async def test_stores_pre_sync_offset(self, frozen_now):
        """last_offset is the pre-sync drift and the listeners are told."""
        manager, _, _ = _make_manager()
        listener = MagicMock()
        manager.async_add_listener(listener)
        await manager.async_sync(raise_errors=True)
        assert manager.last_offset == -492
        assert manager.last_sync == NOW
        listener.assert_called_once()


class TestManagerQuery:
    """async_query reads without setting."""

    async def test_query_stores_measured_offset(self, frozen_now):
        """The measured offset is stored and last_sync does not change."""
        manager, client, _ = _make_manager()
        client.read_clock.side_effect = [_reading(7)]
        await manager.async_query()
        assert manager.last_offset == 7
        assert manager.last_sync is None
        client.set_clock.assert_not_awaited()


class TestManagerStart:
    """async_start registers the schedule only when enabled."""

    def test_disabled_registers_listener_only(self):
        """With the schedule off, only the coordinator listener is added."""
        manager, _, entry = _make_manager()
        with patch.object(clock_sync, "async_track_time_change") as track_time:
            manager.async_start()
        track_time.assert_not_called()
        assert entry.async_on_unload.call_count == 1

    def test_enabled_with_dst_arms_both_jobs(self, frozen_now):
        """The daily job and the DST job are armed."""
        manager, _, _ = _make_manager(
            {CONF_CLOCK_SYNC_ENABLED: True, CONF_CLOCK_SYNC_MANAGE_DST: True}
        )
        with (
            patch.object(clock_sync, "async_track_time_change") as track_time,
            patch.object(clock_sync, "async_track_point_in_utc_time") as track_point,
        ):
            manager.async_start()
        assert track_time.call_args.kwargs == {"hour": 4, "minute": 0, "second": 0}
        assert track_point.call_args.args[2] == datetime(2027, 3, 14, 8, 5, tzinfo=UTC)


# =============================================================================
# HA client read_clock
# =============================================================================


def _date_msg(day: date) -> ProcessorDateMessage:
    return ProcessorDateMessage(raw="", timestamp=NOW, date=day)


def _time_msg() -> ProcessorTimeMessage:
    return ProcessorTimeMessage(raw="", timestamp=NOW, hour=23, minute=59, second=59)


class TestReadClock:
    """read_clock repeats once when it crosses midnight."""

    def _client(self, replies):
        client = HomeworksClient(HomeworksClientConfig(host="127.0.0.1", port=23))
        client._client.request = AsyncMock(side_effect=replies)
        return client

    async def test_one_pass(self):
        """Equal dates give one pass."""
        day = date(2026, 11, 10)
        client = self._client([_date_msg(day), _time_msg(), _date_msg(day)])
        reading = await client.read_clock(include_dst=False, timeout=1.0)
        assert reading.controller == datetime(2026, 11, 10, 23, 59, 59)
        assert reading.received_utc == NOW
        assert reading.dst is None
        assert client._client.request.await_count == 3

    async def test_midnight_crossing_repeats(self):
        """A midnight crossing gives a second pass."""
        day1, day2 = date(2026, 11, 10), date(2026, 11, 11)
        client = self._client(
            [
                _date_msg(day1),
                _time_msg(),
                _date_msg(day2),
                _date_msg(day2),
                _time_msg(),
                _date_msg(day2),
            ]
        )
        reading = await client.read_clock(include_dst=False, timeout=1.0)
        assert reading.controller.date() == day2
        assert client._client.request.await_count == 6

    async def test_crossing_twice_raises(self):
        """Crossing midnight twice raises."""
        days = [date(2026, 11, d) for d in (10, 11, 12)]
        client = self._client(
            [
                _date_msg(days[0]),
                _time_msg(),
                _date_msg(days[1]),
                _date_msg(days[1]),
                _time_msg(),
                _date_msg(days[2]),
            ]
        )
        with pytest.raises(HomeworksException):
            await client.read_clock(include_dst=False, timeout=1.0)


# =============================================================================
# Entities
# =============================================================================


@pytest.fixture
def clock_entities(mock_coordinator):
    """Return the 4 clock entities and the connection sensor."""
    from custom_components.homeworks_hwi.button import (
        HomeworksClockQueryButton,
        HomeworksClockSyncButton,
    )
    from custom_components.homeworks_hwi.sensor import (
        HomeworksClockOffsetSensor,
        HomeworksConnectionSensor,
        HomeworksLastClockSyncSensor,
    )

    manager = MagicMock()
    manager.async_sync = AsyncMock()
    manager.async_query = AsyncMock()
    entities = {
        "last_sync": HomeworksLastClockSyncSensor(manager, "test_controller"),
        "offset": HomeworksClockOffsetSensor(manager, "test_controller"),
        "sync": HomeworksClockSyncButton(manager, "test_controller"),
        "query": HomeworksClockQueryButton(manager, "test_controller"),
    }
    connection = HomeworksConnectionSensor(mock_coordinator, "test_controller")
    return entities, connection, manager


class TestClockEntities:
    """Unique ids, device, and categories of the clock entities."""

    def test_unique_ids(self, clock_entities):
        """The unique_ids have no .v2 suffix."""
        entities, _, _ = clock_entities
        unique_ids = {key: entity.unique_id for key, entity in entities.items()}
        assert unique_ids == {
            "last_sync": "homeworks.test_controller.clock.last_sync",
            "offset": "homeworks.test_controller.clock.offset",
            "sync": "homeworks.test_controller.clock.sync",
            "query": "homeworks.test_controller.clock.query",
        }
        assert not any(uid.endswith(".v2") for uid in unique_ids.values())

    def test_attach_to_controller_device(self, clock_entities):
        """All 4 attach to the existing controller device."""
        entities, connection, _ = clock_entities
        for entity in entities.values():
            assert entity.device_info["identifiers"] == {
                (DOMAIN, "test_controller.controller.v2")
            }
            assert (
                entity.device_info["identifiers"]
                == connection.device_info["identifiers"]
            )

    def test_categories_and_enabled(self, clock_entities):
        """Sensors are diagnostic and enabled; sync is config, query diagnostic."""
        entities, _, _ = clock_entities
        assert entities["last_sync"].entity_category == EntityCategory.DIAGNOSTIC
        assert entities["offset"].entity_category == EntityCategory.DIAGNOSTIC
        assert entities["sync"].entity_category == EntityCategory.CONFIG
        assert entities["query"].entity_category == EntityCategory.DIAGNOSTIC
        assert entities["last_sync"].entity_registry_enabled_default is True
        assert entities["offset"].entity_registry_enabled_default is True

    async def test_buttons_await_manager(self, clock_entities):
        """Pressing the buttons awaits the manager."""
        entities, _, manager = clock_entities
        await entities["sync"].async_press()
        manager.async_sync.assert_awaited_once_with(raise_errors=True)
        await entities["query"].async_press()
        manager.async_query.assert_awaited_once_with()

    async def test_buttons_created_with_schedule_off(self, mock_hass):
        """Both clock buttons exist when clock_sync_enabled is False."""
        from custom_components.homeworks_hwi.button import (
            HomeworksClockQueryButton,
            HomeworksClockSyncButton,
            async_setup_entry,
        )

        entry = MagicMock()
        entry.options = {
            CONF_CONTROLLER_ID: "test_controller",
            CONF_CLOCK_SYNC_ENABLED: False,
        }
        added = []
        await async_setup_entry(mock_hass, entry, added.extend)
        assert {type(e) for e in added} == {
            HomeworksClockSyncButton,
            HomeworksClockQueryButton,
        }


def test_new_translation_keys_in_both_files():
    """strings.json and en.json have the same new keys."""
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text("utf-8"))
    english = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text("utf-8")
    )
    for data in (strings, english):
        assert "time_sync" in data["options"]["step"]
        assert "time_sync" in data["options"]["step"]["init"]["menu_options"]
        assert "zone_has_no_dst" in data["options"]["error"]
        assert {"clock_sync_frequency", "clock_sync_weekday"} <= data["selector"].keys()
        assert {
            "clock_reply_timeout",
            "clock_read_failed",
            "clock_repeated_fall_back_hour",
            "not_connected",
        } <= data["exceptions"].keys()
        assert {"last_clock_sync", "processor_clock_offset"} <= data["entity"][
            "sensor"
        ].keys()
        assert {"sync_controller_clock", "query_controller_clock"} == data["entity"][
            "button"
        ].keys()
    assert strings == english

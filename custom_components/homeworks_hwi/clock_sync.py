"""Keep the HWI processor clock in step with Home Assistant.

Pure helpers (no hass argument) come first so they can be unit tested
directly. ClockSyncManager owns the schedule, the sync and query routines,
and the last values shown by the clock sensors.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import (
    Callable,
    Mapping,
)
from dataclasses import dataclass
from datetime import (
    UTC,
    date,
    datetime,
    time,
    timedelta,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
)
from zoneinfo import ZoneInfo

from homeassistant.core import (
    CALLBACK_TYPE,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_LAST_ATTEMPT,
    ATTR_LAST_ERROR,
    ATTR_OFFSET_AFTER,
    ATTR_OFFSET_BEFORE,
    ATTR_SYNCED_AT,
    ATTR_TRIGGER,
    CLOCK_REPLY_TIMEOUT_S,
    CLOCK_SYNC_FREQ_MONTHLY_FIRST,
    CLOCK_SYNC_FREQ_WEEKLY,
    CLOCK_SYNC_MAX_RETRIES,
    CLOCK_SYNC_RETRY_THRESHOLD_S,
    CLOCK_SYNC_STATUS_FAILED,
    CLOCK_SYNC_STATUS_NEVER_SYNCED,
    CLOCK_SYNC_STATUS_SKIPPED,
    CLOCK_SYNC_STATUS_SUCCESS,
    CLOCK_SYNC_STATUS_SYNCING,
    CLOCK_SYNC_STATUSES,
    CLOCK_SYNC_TRIGGER_BUTTON,
    CLOCK_SYNC_TRIGGER_DST_TRANSITION,
    CLOCK_SYNC_TRIGGER_RECONNECT,
    CLOCK_SYNC_TRIGGER_SCHEDULED,
    CLOCK_SYNC_TZ_AUTO,
    CLOCK_SYNC_WEEKDAYS,
    CONF_CLOCK_SYNC_ENABLED,
    CONF_CLOCK_SYNC_FREQUENCY,
    CONF_CLOCK_SYNC_MANAGE_DST,
    CONF_CLOCK_SYNC_TIME,
    CONF_CLOCK_SYNC_TIMEZONE,
    CONF_CLOCK_SYNC_WEEKDAY,
    DEFAULT_CLOCK_SYNC_ENABLED,
    DEFAULT_CLOCK_SYNC_MANAGE_DST,
    DEFAULT_CLOCK_SYNC_TIME,
    DEFAULT_CLOCK_SYNC_WEEKDAY,
    DOMAIN,
    DST_JOB_SETTLE,
    DST_SEARCH_HORIZON,
    DST_SEARCH_STEP,
)
from .hwi_protocol import (
    HomeworksException,
    HomeworksTimeout,
)
from .hwi_protocol.commands import (
    request_dst_state,
    request_time_with_seconds,
)
from .models import ClockReading

if TYPE_CHECKING:
    from . import HomeworksHWIConfigEntry
    from .client import HomeworksClient
    from .coordinator import HomeworksCoordinator

_LOGGER = logging.getLogger(__name__)

# Option values used when an entry has no clock sync options yet
CLOCK_SYNC_OPTION_DEFAULTS: Final[Mapping[str, Any]] = {
    CONF_CLOCK_SYNC_ENABLED: DEFAULT_CLOCK_SYNC_ENABLED,
    CONF_CLOCK_SYNC_TIMEZONE: CLOCK_SYNC_TZ_AUTO,
    CONF_CLOCK_SYNC_FREQUENCY: CLOCK_SYNC_FREQ_WEEKLY,
    CONF_CLOCK_SYNC_WEEKDAY: DEFAULT_CLOCK_SYNC_WEEKDAY,
    CONF_CLOCK_SYNC_TIME: DEFAULT_CLOCK_SYNC_TIME,
    CONF_CLOCK_SYNC_MANAGE_DST: DEFAULT_CLOCK_SYNC_MANAGE_DST,
}

# Commands whose timeout can mean the firmware lacks them
_FIRMWARE_DEPENDENT_COMMANDS = frozenset(
    {request_time_with_seconds(), request_dst_state()}
)

# Monthly-first: the chosen weekday in days 1-7 of the month
_FIRST_WEEK_LAST_DAY = 7


# =============================================================================
# Pure helpers
# =============================================================================


@dataclass(frozen=True)
class ClockSyncSettings:
    """Clock sync options of one config entry."""

    enabled: bool
    timezone: str
    frequency: str
    weekday: int
    time_of_day: time
    manage_dst: bool

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> ClockSyncSettings:
        """Build the settings from entry options, applying the defaults."""
        merged = {**CLOCK_SYNC_OPTION_DEFAULTS, **options}
        return cls(
            enabled=bool(merged[CONF_CLOCK_SYNC_ENABLED]),
            timezone=str(merged[CONF_CLOCK_SYNC_TIMEZONE]),
            frequency=str(merged[CONF_CLOCK_SYNC_FREQUENCY]),
            weekday=CLOCK_SYNC_WEEKDAYS.index(merged[CONF_CLOCK_SYNC_WEEKDAY]),
            time_of_day=time.fromisoformat(merged[CONF_CLOCK_SYNC_TIME]),
            manage_dst=bool(merged[CONF_CLOCK_SYNC_MANAGE_DST]),
        )


def resolve_timezone(option: str, ha_time_zone: str) -> ZoneInfo:
    """`auto` returns HA's zone. Any other value returns `ZoneInfo(option)`."""
    if option == CLOCK_SYNC_TZ_AUTO:
        return ZoneInfo(ha_time_zone)
    return ZoneInfo(option)


def is_scheduled_day(local_day: date, frequency: str, weekday: int) -> bool:
    """Weekly: the weekday matches. Monthly-first: the weekday matches and `day <= 7`."""
    if local_day.weekday() != weekday:
        return False
    if frequency == CLOCK_SYNC_FREQ_MONTHLY_FIRST:
        return local_day.day <= _FIRST_WEEK_LAST_DAY
    return True


@dataclass(frozen=True)
class DstTransition:
    """One change of the UTC offset of a zone."""

    at_utc: datetime
    offset_before: timedelta
    offset_after: timedelta


def _utc_offset(tz: ZoneInfo, instant: datetime) -> timedelta:
    """Return the UTC offset of `tz` at `instant`."""
    offset = instant.astimezone(tz).utcoffset()
    return offset if offset is not None else timedelta(0)


def find_next_transition(
    tz: ZoneInfo, after_utc: datetime, horizon: timedelta = DST_SEARCH_HORIZON
) -> DstTransition | None:
    """Step `DST_SEARCH_STEP` until `utcoffset()` changes, then bisect to 1 s.

    Return the first UTC instant with the new offset. CPU only, about 9000
    steps, so it is fine on the event loop.
    """
    offset_before = _utc_offset(tz, after_utc)
    end = after_utc + horizon
    low = after_utc
    while low < end:
        high = low + DST_SEARCH_STEP
        if _utc_offset(tz, high) != offset_before:
            # Bisect in whole seconds so the result is an exact second
            low_s = int(low.timestamp())
            high_s = int(high.timestamp())
            while high_s - low_s > 1:
                mid_s = (low_s + high_s) // 2
                mid = datetime.fromtimestamp(mid_s, UTC)
                if _utc_offset(tz, mid) == offset_before:
                    low_s = mid_s
                else:
                    high_s = mid_s
            at_utc = datetime.fromtimestamp(high_s, UTC)
            return DstTransition(
                at_utc=at_utc,
                offset_before=offset_before,
                offset_after=_utc_offset(tz, at_utc),
            )
        low = high
    return None


def dst_job_run_time(transition: DstTransition) -> datetime:
    """Return when the DST job runs: after the repeated window, plus a settle time."""
    return (
        transition.at_utc
        + max(timedelta(0), transition.offset_before - transition.offset_after)
        + DST_JOB_SETTLE
    )


def is_repeated_fall_back_hour(local_time: datetime) -> bool:
    """Return True if `local_time` is on the second pass of the repeated hour.

    The wall-clock hour repeats on the fall-back day. PEP 495 marks the
    second pass with the datetime `fold` attribute, and `astimezone()` sets
    it to 1 only on that second pass.
    """
    # PEP 495 attribute: 1 only on the second pass of a repeated wall time
    return local_time.fold == 1


def offset_seconds(reading: ClockReading, tz: ZoneInfo) -> float:
    """Return the controller clock offset in seconds. Positive means ahead."""
    ha_wall_time = reading.received_utc.astimezone(tz).replace(tzinfo=None)
    return (reading.controller - ha_wall_time).total_seconds()


# =============================================================================
# Manager
# =============================================================================


class ClockSyncManager:
    """Owns the schedule, the sync and query routines, and the last values shown by the sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeworksHWIConfigEntry,
        coordinator: HomeworksCoordinator,
    ) -> None:
        """Initialize the manager from the entry options."""
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._settings = ClockSyncSettings.from_options(entry.options)
        self._lock = asyncio.Lock()
        self._pending = False
        self._manual_dst_rejected = False
        self._dst_unsub: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []
        self.last_offset: float | None = None
        # Status of the last sync attempt, shown by the "Last clock sync" sensor
        self.status = CLOCK_SYNC_STATUS_NEVER_SYNCED
        self.synced_at: datetime | None = None
        self.last_attempt: datetime | None = None
        self.trigger: str | None = None
        self.offset_before: int | None = None
        self.offset_after: int | None = None
        self.last_error: str | None = None

    @property
    def _tz(self) -> ZoneInfo:
        """Return the zone the controller clock follows."""
        return resolve_timezone(self._settings.timezone, self._hass.config.time_zone)

    @callback
    def async_start(self) -> None:
        """Register the coordinator listener and, if enabled, the schedule."""
        self._entry.async_on_unload(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        if not self._settings.enabled:
            return
        sync_time = self._settings.time_of_day
        self._entry.async_on_unload(
            async_track_time_change(
                self._hass,
                self._handle_time,
                hour=sync_time.hour,
                minute=sync_time.minute,
                second=sync_time.second,
            )
        )
        if self._settings.manage_dst:
            self._arm_dst_job()
            self._entry.async_on_unload(self._cancel_dst_job)

    @callback
    def _arm_dst_job(self) -> None:
        """Schedule a sync shortly after the next DST transition."""
        transition = find_next_transition(self._tz, dt_util.utcnow())
        if transition is None:
            self._dst_unsub = None
            return
        self._dst_unsub = async_track_point_in_utc_time(
            self._hass, self._handle_dst_job, dst_job_run_time(transition)
        )

    @callback
    def _cancel_dst_job(self) -> None:
        """Cancel the pending DST job."""
        if self._dst_unsub is not None:
            self._dst_unsub()
            self._dst_unsub = None

    @callback
    def _handle_time(self, now: datetime) -> None:
        """Run the daily check and sync on a scheduled day."""
        if is_scheduled_day(
            dt_util.as_local(now).date(),
            self._settings.frequency,
            self._settings.weekday,
        ):
            self._start_background(CLOCK_SYNC_TRIGGER_SCHEDULED)

    @callback
    def _handle_dst_job(self, now: datetime) -> None:
        """Sync after a DST transition and arm the next one."""
        self._start_background(CLOCK_SYNC_TRIGGER_DST_TRANSITION)
        self._arm_dst_job()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Run a sync that was missed while the controller was disconnected."""
        if self._pending and self._coordinator.connected and not self._lock.locked():
            self._pending = False
            self._start_background(CLOCK_SYNC_TRIGGER_RECONNECT)

    def _start_background(self, trigger: str) -> None:
        """Start an automatic sync as an entry-scoped background task."""
        self._entry.async_create_background_task(
            self._hass,
            self.async_sync(trigger=trigger),
            name=f"homeworks_{self._coordinator.controller_id}_clock_sync",
        )

    def _connected_client(self) -> HomeworksClient | None:
        """Return the client if the controller is connected."""
        client = self._coordinator.client
        if client is None or not self._coordinator.connected:
            return None
        return client

    async def async_sync(self, *, trigger: str) -> None:
        """Set the controller clock to HA time (ST, then SD).

        An automatic run logs problems. A button press raises a translated
        HomeAssistantError after the status is written. No path leaves the
        status at syncing.
        """
        async with self._lock:
            self._begin_attempt(trigger)
            try:
                await self._async_sync_attempt(
                    raise_errors=trigger == CLOCK_SYNC_TRIGGER_BUTTON
                )
            except Exception as err:
                if self.status == CLOCK_SYNC_STATUS_SYNCING:
                    self._finish_attempt(
                        CLOCK_SYNC_STATUS_FAILED, f"Unexpected error: {err}"
                    )
                raise
            finally:
                if self.status == CLOCK_SYNC_STATUS_SYNCING:
                    self._finish_attempt(CLOCK_SYNC_STATUS_FAILED, "Interrupted")

    async def _async_sync_attempt(self, *, raise_errors: bool) -> None:
        """Run one sync attempt and record its result."""
        client = self._connected_client()
        if client is None:
            self._finish_attempt(CLOCK_SYNC_STATUS_SKIPPED, "Controller not connected")
            if raise_errors:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="not_connected"
                )
            self._pending = True
            _LOGGER.info("Clock sync skipped, controller not connected")
            return

        tz = self._tz
        target = dt_util.utcnow().astimezone(tz)
        if is_repeated_fall_back_hour(target):
            self._finish_attempt(CLOCK_SYNC_STATUS_SKIPPED, "Repeated fall-back hour")
            if raise_errors:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="clock_repeated_fall_back_hour",
                )
            _LOGGER.warning("Clock sync skipped, repeated fall-back hour in %s", tz)
            return

        try:
            before = await client.read_clock(
                include_dst=False, timeout=CLOCK_REPLY_TIMEOUT_S
            )
            pre_offset = offset_seconds(before, tz)
            if self._settings.manage_dst and not self._manual_dst_rejected:
                await self._async_align_dst(client, bool(target.dst()))
            after, post_offset = await self._async_set_and_read(client, tz)
            for _retry in range(CLOCK_SYNC_MAX_RETRIES):
                if abs(post_offset) <= CLOCK_SYNC_RETRY_THRESHOLD_S:
                    break
                after, post_offset = await self._async_set_and_read(client, tz)
        except HomeworksException as err:
            self._finish_attempt(CLOCK_SYNC_STATUS_FAILED, _clock_error_text(err))
            self._handle_clock_error(err, raise_errors)
            return

        if abs(post_offset) > CLOCK_SYNC_RETRY_THRESHOLD_S:
            _LOGGER.warning(
                "Controller clock still off by %+.1f s after sync", post_offset
            )
        if after.dst != bool(dt_util.utcnow().astimezone(tz).dst()):
            _LOGGER.warning("Controller DST state differs from %s", tz)

        self.last_offset = round(pre_offset)
        self._finish_attempt(
            CLOCK_SYNC_STATUS_SUCCESS, offsets=(round(pre_offset), round(post_offset))
        )
        _LOGGER.info(
            "Controller clock synced: offset %+.1f s before, %+.1f s after",
            pre_offset,
            post_offset,
        )

    @callback
    def _begin_attempt(self, trigger: str) -> None:
        """Show syncing before the first command is sent."""
        self.status = CLOCK_SYNC_STATUS_SYNCING
        self.last_attempt = dt_util.utcnow()
        self.trigger = trigger
        self._notify_listeners()

    @callback
    def _finish_attempt(
        self,
        status: str,
        error: str | None = None,
        *,
        offsets: tuple[int, int] | None = None,
    ) -> None:
        """Record the result of the attempt. Offsets change only on success."""
        self.status = status
        self.last_error = error
        if offsets is not None:
            self.synced_at = dt_util.utcnow()
            self.offset_before, self.offset_after = offsets
        self._notify_listeners()

    @property
    def status_attributes(self) -> dict[str, Any]:
        """Return the attributes of the "Last clock sync" sensor."""
        return {
            ATTR_SYNCED_AT: _isoformat(self.synced_at),
            ATTR_LAST_ATTEMPT: _isoformat(self.last_attempt),
            ATTR_TRIGGER: self.trigger,
            ATTR_OFFSET_BEFORE: self.offset_before,
            ATTR_OFFSET_AFTER: self.offset_after,
            ATTR_LAST_ERROR: self.last_error,
        }

    async def _async_align_dst(self, client: HomeworksClient, expected: bool) -> None:
        """Send STARTDST/ENDDST if the controller DST state differs from the zone."""
        active = await client.read_dst(timeout=CLOCK_REPLY_TIMEOUT_S)
        if active == expected:
            return
        accepted = await client.send_dst(start=expected, timeout=CLOCK_REPLY_TIMEOUT_S)
        if not accepted:
            self._manual_dst_rejected = True
            _LOGGER.warning(
                "Database has automatic DST, DST commands disabled until reload"
            )

    async def _async_set_and_read(
        self, client: HomeworksClient, tz: ZoneInfo
    ) -> tuple[ClockReading, float]:
        """Set the clock, then read it back. Return the reading and its offset."""
        await client.set_clock(
            lambda: dt_util.utcnow().astimezone(tz), timeout=CLOCK_REPLY_TIMEOUT_S
        )
        after = await client.read_clock(include_dst=True, timeout=CLOCK_REPLY_TIMEOUT_S)
        return after, offset_seconds(after, tz)

    async def async_query(self) -> None:
        """Read the controller clock and store its offset. Does not set it."""
        async with self._lock:
            client = self._connected_client()
            if client is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="not_connected"
                )
            tz = self._tz
            try:
                reading = await client.read_clock(
                    include_dst=True, timeout=CLOCK_REPLY_TIMEOUT_S
                )
            except HomeworksException as err:
                self._handle_clock_error(err, raise_errors=True)
                return

            self.last_offset = round(offset_seconds(reading, tz))
            self._notify_listeners()
            _LOGGER.info(
                "Controller clock offset %+d s, controller DST %s",
                self.last_offset,
                reading.dst,
            )

    def _handle_clock_error(self, err: HomeworksException, raise_errors: bool) -> None:
        """Log a failed clock exchange and, for a button, raise a translated error."""
        if isinstance(err, HomeworksTimeout):
            if err.command in _FIRMWARE_DEPENDENT_COMMANDS:
                _LOGGER.warning(
                    "Controller did not answer %s, check HELP for firmware support",
                    err.command,
                )
            else:
                _LOGGER.warning("Controller did not answer %s", err.command)
            if raise_errors:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="clock_reply_timeout",
                    translation_placeholders={"command": err.command},
                ) from err
            return
        _LOGGER.warning("Controller clock exchange failed: %s", err)
        if raise_errors:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="clock_read_failed"
            ) from err

    @callback
    def async_add_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback for new values. Return a function that removes it."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def _notify_listeners(self) -> None:
        """Tell the sensors that the values changed."""
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def restore_offset(self, last_offset: float) -> None:
        """Take the offset the offset sensor restored after a restart."""
        self.last_offset = last_offset

    @callback
    def restore_status(self, state: str, attributes: Mapping[str, Any]) -> None:
        """Take the status the status sensor restored after a restart.

        A restart during a run leaves syncing, which is restored as failed.
        """
        if state not in CLOCK_SYNC_STATUSES:
            return
        self.synced_at = _parse_isoformat(attributes.get(ATTR_SYNCED_AT))
        self.last_attempt = _parse_isoformat(attributes.get(ATTR_LAST_ATTEMPT))
        self.trigger = attributes.get(ATTR_TRIGGER)
        self.offset_before = attributes.get(ATTR_OFFSET_BEFORE)
        self.offset_after = attributes.get(ATTR_OFFSET_AFTER)
        self.last_error = attributes.get(ATTR_LAST_ERROR)
        if state == CLOCK_SYNC_STATUS_SYNCING:
            state = CLOCK_SYNC_STATUS_FAILED
            self.last_error = "Interrupted by restart"
        self.status = state


def _clock_error_text(err: HomeworksException) -> str:
    """Return a short text for the last_error attribute."""
    if isinstance(err, HomeworksTimeout):
        return f"No reply to {err.command} within {CLOCK_REPLY_TIMEOUT_S} s"
    return str(err) or type(err).__name__


def _isoformat(value: datetime | None) -> str | None:
    """Return an ISO datetime attribute value, or None."""
    return value.isoformat() if value is not None else None


def _parse_isoformat(value: Any) -> datetime | None:
    """Parse a restored ISO datetime attribute, or return None."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None

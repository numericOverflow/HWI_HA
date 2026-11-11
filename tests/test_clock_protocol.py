"""Tests for the controller clock protocol: parsing, commands, and request().

Protocol layer only, no Home Assistant needed. Reply strings are the exact
hardware replies from the clock sync discovery test (2026-11-10).
"""

import asyncio
from datetime import (
    date,
    datetime,
)

import pytest

from custom_components.homeworks_hwi.hwi_protocol import (
    DstChangedMessage,
    DstManualUnsupportedMessage,
    DstStateMessage,
    HomeworksClient,
    HomeworksConnectionLost,
    HomeworksException,
    HomeworksTimeout,
    KLSMessage,
    MessageParser,
    ProcessorDateMessage,
    ProcessorTimeMessage,
    UnknownMessage,
)
from custom_components.homeworks_hwi.hwi_protocol.commands import (
    end_dst,
    format_clock_date,
    format_clock_time,
    request_dst_state,
    request_time_with_seconds,
    start_dst,
)

REQUEST_TIMEOUT_S = 1.0
SHORT_TIMEOUT_S = 0.2
# Transport connect waits up to 1.2 s for a login prompt
CONNECT_TIMEOUT_S = 5.0


def _parse_one(line: str):
    """Feed one CRLF-terminated line and return the single parsed message."""
    messages = MessageParser().feed(f"{line}\r\n".encode())
    assert len(messages) == 1
    return messages[0]


# =============================================================================
# Parsing
# =============================================================================


class TestClockReplyParsing:
    """Each hardware string gives the right typed message and fields."""

    @pytest.mark.parametrize(
        ("line", "hour", "minute", "second"),
        [
            ("Processor Time: 11:58", 11, 58, None),
            ("Processor Time: 17:09:29", 17, 9, 29),
            ("Processor Time: 01:00:07", 1, 0, 7),
            ("processor time:   17:09:29  ", 17, 9, 29),
            ("PROCESSOR TIME:1:05", 1, 5, None),
        ],
    )
    def test_processor_time(self, line, hour, minute, second):
        """ST ack and RST2 reply parse to ProcessorTimeMessage."""
        msg = _parse_one(line)
        assert isinstance(msg, ProcessorTimeMessage)
        assert (msg.hour, msg.minute, msg.second) == (hour, minute, second)

    def test_st_ack_has_no_second(self):
        """The ST ack has HH:MM only, so second is None."""
        msg = _parse_one("Processor Time: 11:58")
        assert msg.second is None

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Processor Date: Monday 11/09/2026", date(2026, 11, 9)),
            ("Processor Date: Sunday 03/14/2027", date(2027, 3, 14)),
            ("processor date:  sunday   03/14/2027 ", date(2027, 3, 14)),
            ("Processor Date: 03/14/2027", date(2027, 3, 14)),
        ],
    )
    def test_processor_date(self, line, expected):
        """RSD reply and SD ack parse to ProcessorDateMessage."""
        msg = _parse_one(line)
        assert isinstance(msg, ProcessorDateMessage)
        assert msg.date == expected

    @pytest.mark.parametrize(
        ("line", "active"),
        [
            ("DST = False", False),
            ("DST = True", True),
            ("dst=true", True),
            ("DST  =  FALSE ", False),
        ],
    )
    def test_dst_state(self, line, active):
        """RDST reply parses to DstStateMessage."""
        msg = _parse_one(line)
        assert isinstance(msg, DstStateMessage)
        assert msg.active is active

    @pytest.mark.parametrize(
        "line",
        [
            "Database does not support manual DST configuration",
            "database does not support MANUAL dst configuration",
        ],
    )
    def test_dst_manual_unsupported(self, line):
        """The STARTDST/ENDDST rejection parses to DstManualUnsupportedMessage."""
        assert isinstance(_parse_one(line), DstManualUnsupportedMessage)

    @pytest.mark.parametrize(
        ("line", "started"),
        [
            ("Daylight Savings Time Started", True),
            ("Daylight Savings Time Ended", False),
            ("daylight savings time started ", True),
        ],
    )
    def test_dst_changed(self, line, started):
        """The STARTDST/ENDDST acceptance parses to DstChangedMessage."""
        msg = _parse_one(line)
        assert isinstance(msg, DstChangedMessage)
        assert msg.started is started

    @pytest.mark.parametrize(
        "line",
        [
            "All Timeclocks Enabled",
            "TCD: Timeclock Disabled",
            "TCE: All Timeclocks Enabled",
            "Today's Sunrise: 06:44",
            "The time on processor 01 is 14:04:46",
        ],
    )
    def test_other_lines_stay_unknown(self, line):
        """Timeclock, sunrise, and Boot replies are not clock messages."""
        assert isinstance(_parse_one(line), UnknownMessage)

    def test_invalid_date_is_dropped(self):
        """An impossible date is logged and dropped, without an exception."""
        messages = MessageParser().feed(b"Processor Date: Friday 13/45/2027\r\n")
        assert messages == []

    def test_kls_in_same_feed_still_parses(self):
        """A KLS line between clock replies still parses as KLSMessage."""
        data = (
            b"Processor Time: 17:09:29\r\n"
            b"KLS, [02:06:03], 000000000121111110000000\r\n"
            b"Processor Date: Monday 11/09/2026\r\n"
        )
        messages = MessageParser().feed(data)
        assert [type(m) for m in messages] == [
            ProcessorTimeMessage,
            KLSMessage,
            ProcessorDateMessage,
        ]
        assert messages[1].address == "[02:06:03]"


# =============================================================================
# Commands
# =============================================================================


class TestClockCommands:
    """Clock command builders and formatters."""

    def test_format_clock_time(self):
        """ST time is 24 h HH:MM:SS."""
        assert format_clock_time(datetime(2027, 3, 14, 1, 59, 52)) == "01:59:52"

    def test_format_clock_date(self):
        """SD date is MM/DD/YYYY with leading zeros."""
        assert format_clock_date(date(2027, 1, 5)) == "01/05/2027"

    def test_dst_commands(self):
        """The DST commands have no arguments."""
        assert request_dst_state() == "RDST"
        assert start_dst() == "STARTDST"
        assert end_dst() == "ENDDST"


# =============================================================================
# request() against the fake controller
# =============================================================================


@pytest.fixture
async def started_client(fake_controller):
    """Return a started protocol client connected to the fake controller."""
    received: list = []
    connected = asyncio.Event()
    client = HomeworksClient(
        "127.0.0.1",
        fake_controller.port,
        callback=received.append,
        reconnect_callback=connected.set,
    )
    client.received = received
    await client.start()
    await asyncio.wait_for(connected.wait(), CONNECT_TIMEOUT_S)
    yield client
    await client.stop()


class TestRequest:
    """request() sends a command and returns the typed reply."""

    async def test_returns_reply(self, started_client):
        """RST2 returns the simulated clock time."""
        reply = await started_client.request(
            request_time_with_seconds(), (ProcessorTimeMessage,), REQUEST_TIMEOUT_S
        )
        assert isinstance(reply, ProcessorTimeMessage)
        assert (reply.hour, reply.minute, reply.second) == (17, 9, 29)

    async def test_skips_interleaved_kls(self, started_client, fake_controller):
        """A KLS before the reply is skipped and still reaches the callback."""
        fake_controller.clock_reply_noise = True
        reply = await started_client.request(
            request_time_with_seconds(), (ProcessorTimeMessage,), REQUEST_TIMEOUT_S
        )
        assert isinstance(reply, ProcessorTimeMessage)
        assert any(isinstance(m, KLSMessage) for m in started_client.received)

    async def test_sequential_requests_get_own_reply(
        self, started_client, fake_controller
    ):
        """Two requests of the same type each get their own reply."""
        first = await started_client.request(
            request_time_with_seconds(), (ProcessorTimeMessage,), REQUEST_TIMEOUT_S
        )
        fake_controller.clock = datetime(2026, 11, 10, 1, 0, 7)
        second = await started_client.request(
            request_time_with_seconds(), (ProcessorTimeMessage,), REQUEST_TIMEOUT_S
        )
        assert (first.hour, first.second) == (17, 29)
        assert (second.hour, second.second) == (1, 7)

    async def test_no_reply_times_out(self, started_client, fake_controller):
        """No reply raises HomeworksTimeout and leaves no waiter."""
        fake_controller.clock_silent = True
        with pytest.raises(HomeworksTimeout) as exc_info:
            await started_client.request(
                request_time_with_seconds(), (ProcessorTimeMessage,), SHORT_TIMEOUT_S
            )
        assert exc_info.value.command == "RST2"
        assert started_client._waiters == []

    async def test_disconnect_while_waiting(self, started_client, fake_controller):
        """A dropped connection fails the pending request."""
        fake_controller.clock_silent = True
        pending = asyncio.create_task(
            started_client.request(
                request_time_with_seconds(), (ProcessorTimeMessage,), REQUEST_TIMEOUT_S
            )
        )
        await asyncio.sleep(SHORT_TIMEOUT_S)
        await fake_controller.simulate_disconnect()
        with pytest.raises(HomeworksConnectionLost):
            await pending
        assert started_client._waiters == []

    async def test_before_start_raises(self):
        """request() needs the read loop."""
        client = HomeworksClient("127.0.0.1", 23)
        with pytest.raises(HomeworksException):
            await client.request(
                request_time_with_seconds(), (ProcessorTimeMessage,), SHORT_TIMEOUT_S
            )

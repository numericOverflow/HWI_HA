"""Tests for TX/RX communication logging and credential redaction."""

import logging
from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest

from custom_components.homeworks_hwi.hwi_protocol.protocol import MessageParser
from custom_components.homeworks_hwi.hwi_protocol.transport import (
    HomeworksTransport,
    redact_command,
)
from tests.fake_controller import FakeHomeworksController

INTEGRATION_LOGGER = "custom_components.homeworks_hwi"
USERNAME = "hwiuser"
PASSWORD = "S3cr3t-Pw-9f2"


@pytest.fixture
def debug_log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture DEBUG logs of the integration."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    return caplog


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the formatted log messages."""
    return [record.getMessage() for record in caplog.records]


def _transport_with_mock_writer() -> HomeworksTransport:
    """Return a transport with a mocked stream writer."""
    transport = HomeworksTransport("127.0.0.1", 23)
    writer = MagicMock()
    writer.drain = AsyncMock()
    transport._writer = writer
    return transport


class TestRedactCommand:
    """Tests for redact_command()."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("LOGIN, lutron", "LOGIN, <password_redacted>"),
            ("LOGIN, lutron, 2:7:1", "LOGIN, <password_redacted>, 2:7:1"),
            (" login,secret", " login, <password_redacted>"),
            ("LOGIN", "LOGIN"),
            ("LOGOUT", "LOGOUT"),
            ("RKLS, [02:06:03]", "RKLS, [02:06:03]"),
        ],
    )
    def test_redact_command(self, command: str, expected: str) -> None:
        """Only the password field of a LOGIN command is replaced."""
        assert redact_command(command) == expected


class TestTransportTxLogging:
    """Tests for TX logging in HomeworksTransport.write()."""

    async def test_plain_command_logged(self, debug_log) -> None:
        """A normal command is logged as sent."""
        transport = _transport_with_mock_writer()

        assert await transport.write("RKLS, [02:06:03]")

        assert "TX: RKLS, [02:06:03]" in _messages(debug_log)

    async def test_login_command_redacted(self, debug_log) -> None:
        """A LOGIN password is redacted in the log but sent unchanged."""
        transport = _transport_with_mock_writer()
        command = f"LOGIN, {PASSWORD}, 2:7:1"

        assert await transport.write(command)

        assert "TX: LOGIN, <password_redacted>, 2:7:1" in _messages(debug_log)
        assert PASSWORD not in debug_log.text
        transport._writer.write.assert_called_once_with(
            command.encode("utf-8") + b"\r\n"
        )

    async def test_log_as_overrides_command(self, debug_log) -> None:
        """The log_as text is logged instead of the command."""
        transport = _transport_with_mock_writer()

        assert await transport.write("anything", log_as="X")

        assert "TX: X" in _messages(debug_log)
        assert "anything" not in debug_log.text


class TestLoginLogging:
    """Tests for logging during the connect-time login."""

    async def test_login_credentials_not_logged(self, debug_log) -> None:
        """The login credentials are replaced with placeholders."""
        controller = FakeHomeworksController(
            require_login=True,
            credentials=f"{USERNAME}, {PASSWORD}".encode(),
        )
        await controller.start()
        transport = HomeworksTransport(
            "127.0.0.1", controller.port, credentials=f"{USERNAME}, {PASSWORD}"
        )
        try:
            await transport.connect()
            assert transport.connected
        finally:
            await transport.close()
            await controller.stop()

        assert "TX: <user_redacted>, <password_redacted>" in _messages(debug_log)
        assert USERNAME not in debug_log.text
        assert PASSWORD not in debug_log.text

    async def test_connect_rx_logged(self, debug_log) -> None:
        """The login prompt and the login response are logged."""
        controller = FakeHomeworksController(require_login=True)
        await controller.start()
        transport = HomeworksTransport(
            "127.0.0.1", controller.port, credentials="test, test"
        )
        try:
            await transport.connect()
        finally:
            await transport.close()
            await controller.stop()

        messages = _messages(debug_log)
        assert "RX (connect): b'LOGIN: '" in messages
        assert "RX (connect): b'login successful\\r\\n'" in messages


class TestRxLogging:
    """Tests for per-line RX logging."""

    async def test_transport_read_does_not_log_chunks(self, debug_log) -> None:
        """A transport read does not log the raw chunk."""
        transport = HomeworksTransport("127.0.0.1", 23)
        reader = MagicMock()
        reader.read = AsyncMock(return_value=b"DL, [01:01:00:01:01], 50\r\n")
        transport._reader = reader

        assert await transport.read() == b"DL, [01:01:00:01:01], 50\r\n"

        assert "Received:" not in debug_log.text
        assert not any(m.startswith("RX") for m in _messages(debug_log))

    def test_complete_line_logged_once(self, debug_log) -> None:
        """A complete line is logged once."""
        line = "KLS, [02:06:03], 000000000000000000000000"

        MessageParser().feed(f"{line}\r\n".encode())

        rx_lines = [m for m in _messages(debug_log) if m.startswith("RX: ")]
        assert rx_lines == [f"RX: {line}"]

    def test_empty_line_not_logged(self, debug_log) -> None:
        """An empty line is not logged."""
        MessageParser().feed(b"\r\n")

        assert not any(m.startswith("RX") for m in _messages(debug_log))

    def test_unparseable_line_logged_with_warning(self, debug_log) -> None:
        """A line that fails to parse is logged and still produces a warning."""
        MessageParser().feed(b"KLS\xff\r\n")

        assert "RX: KLS\N{REPLACEMENT CHARACTER}" in _messages(debug_log)
        assert any(
            record.levelno == logging.WARNING
            and record.getMessage().startswith("Invalid message encoding")
            for record in debug_log.records
        )

    def test_partial_line_logged_on_reset(self, debug_log) -> None:
        """Unterminated data is logged when the parser is reset."""
        parser = MessageParser()
        parser.feed(b"partial")

        assert not any(m.startswith("RX") for m in _messages(debug_log))

        parser.reset()

        assert "RX (discarded partial): b'partial'" in _messages(debug_log)

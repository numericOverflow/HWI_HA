"""Tests for TX/RX communication logging and credential redaction."""

import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from custom_components.homeworks_hwi.hwi_protocol.transport import HomeworksTransport
from custom_components.homeworks_hwi.hwi_protocol.transport import redact_command
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

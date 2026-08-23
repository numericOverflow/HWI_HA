"""Tests for the Homeworks async client."""

import pytest
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)


@pytest.fixture
async def fake_controller():
    """Create and start a fake controller."""
    from tests.fake_controller import FakeHomeworksController
    controller = FakeHomeworksController(port=0)
    await controller.start()
    yield controller
    await controller.stop()


class TestHomeworksClientIntegration:
    """Integration tests for HomeworksClient."""

    @pytest.mark.asyncio
    async def test_client_connect_to_fake_controller(self, fake_controller):
        """Test that the HA client wrapper can connect to a fake controller."""
        from custom_components.homeworks_hwi.client import (
            HomeworksClient,
            HomeworksClientConfig,
        )

        config = HomeworksClientConfig(
            host="127.0.0.1",
            port=fake_controller.port,
        )
        client = HomeworksClient(config)

        connected = await client.connect()
        assert connected is True
        assert client.connected is True

        await client.stop()
        assert client.connected is False


class TestReconnectAnnouncement:
    """Tests that a reconnect is announced without waiting for traffic.

    Before this, HW_CONNECTION_RESTORED was only emitted from
    _handle_message, so on a quiet system the resync waited for unrelated
    inbound traffic. CCO relays can move during an outage
    (L232/cco_kls_state.htm implementation note 2).
    """

    def _make_client(self, message_callback):
        from custom_components.homeworks_hwi.client import (
            HomeworksClient,
            HomeworksClientConfig,
        )

        config = HomeworksClientConfig(host="127.0.0.1", port=23)
        return HomeworksClient(config, message_callback=message_callback)

    def test_reconnect_callback_emits_connection_restored(self):
        """_handle_reconnect fires the restored event with no messages read."""
        from custom_components.homeworks_hwi.client import HW_CONNECTION_RESTORED

        callback = MagicMock()
        client = self._make_client(callback)

        client._handle_reconnect()

        callback.assert_called_once_with(HW_CONNECTION_RESTORED, [])
        assert client.health.connected is True
        assert client.health.reconnect_count == 1

    def test_reconnect_callback_wired_into_protocol_client(self):
        """The protocol client holds the wrapper's reconnect hook."""
        callback = MagicMock()
        client = self._make_client(callback)

        assert client._client._reconnect_callback == client._handle_reconnect

    def test_subsequent_message_does_not_double_count_reconnect(self):
        """Announcing early must not make the next message re-announce."""
        from custom_components.homeworks_hwi.client import HW_CONNECTION_RESTORED

        callback = MagicMock()
        client = self._make_client(callback)
        client._client = MagicMock()
        client._client.connected = True

        client._handle_reconnect()
        callback.reset_mock()

        client._handle_message(MagicMock())

        restored = [
            c for c in callback.call_args_list
            if c.args and c.args[0] == HW_CONNECTION_RESTORED
        ]
        assert restored == []
        assert client.health.reconnect_count == 1


class TestCoordinatorReconnectSweep:
    """Tests that the coordinator re-polls on the restored event."""

    def test_connection_restored_schedules_poll(self):
        """HW_CONNECTION_RESTORED launches the full state sweep."""
        from custom_components.homeworks_hwi.client import HW_CONNECTION_RESTORED
        from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator

        with patch.object(HomeworksCoordinator, "__init__", lambda self, *a, **kw: None):
            coord = HomeworksCoordinator.__new__(HomeworksCoordinator)
            coord.hass = MagicMock()
            coord._controller_id = "test"
            coord.config_entry = MagicMock()
            # async_create_background_task is mocked, so the "coroutine" it
            # receives is never awaited — use a plain sentinel to avoid an
            # un-awaited coroutine warning.
            coord._safe_poll_all_states = MagicMock(return_value=object())

            coord._handle_message(HW_CONNECTION_RESTORED, [])

            coord._safe_poll_all_states.assert_called_once()
            coord.config_entry.async_create_background_task.assert_called_once()

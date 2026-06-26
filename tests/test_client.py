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

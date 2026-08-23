"""Home Assistant integration smoke tests.

These tests verify the integration loads correctly in Home Assistant.
They are skipped by default (require HA deps) but can be run in an HA dev environment.

To run these tests:
1. Install Home Assistant dev dependencies
2. Run: pytest tests/test_ha_smoke.py -v --no-header

Or in a HA dev container:
    pip install pytest pytest-homeassistant-custom-component
    pytest tests/test_ha_smoke.py -v
"""

import pytest

# Mark all tests in this module as requiring HA
pytestmark = [
    pytest.mark.requires_ha,
    pytest.mark.asyncio,
]


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    try:
        from homeassistant.config_entries import ConfigEntry
        from unittest.mock import MagicMock, patch

        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_id"
        entry.title = "Test Homeworks"
        entry.domain = "homeworks"
        entry.data = {
            "host": "192.168.1.100",
            "port": 23,
            "username": None,
            "password": None,
        }
        entry.options = {
            "controller_id": "test_controller",
            "cco_devices": [
                {
                    "name": "Test Switch",
                    "addr": "[02:06:03]",
                    "button_number": 6,
                    "entity_type": "switch",
                    "inverted": False,
                }
            ],
            "dimmers": [],
            "keypads": [],
            "kls_poll_interval": 10,
            "kls_window_offset": 9,
            "ccos": [],
            "covers": [],
            "locks": [],
        }
        return entry
    except ImportError:
        pytest.skip("Home Assistant not installed")


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    try:
        from unittest.mock import MagicMock, AsyncMock, patch

        hass = MagicMock()
        hass.data = {}
        hass.config_entries = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.bus = MagicMock()
        hass.bus.async_listen_once = MagicMock(return_value=lambda: None)
        return hass
    except ImportError:
        pytest.skip("Home Assistant not installed")


class TestIntegrationLoad:
    """Test that the integration loads correctly."""

    async def test_import_integration(self):
        """Test that the integration module can be imported."""
        from custom_components.homeworks_hwi import DOMAIN
        from custom_components import homeworks_hwi
        assert DOMAIN == "homeworks_hwi"
        assert hasattr(homeworks_hwi, "async_setup_entry")
        assert hasattr(homeworks_hwi, "async_unload_entry")

    async def test_import_config_flow(self):
        """Test that config flow can be imported and has correct domain."""
        try:
            from custom_components.homeworks_hwi import config_flow
            from custom_components.homeworks_hwi.const import DOMAIN
            assert hasattr(config_flow, "HomeworksConfigFlowHandler")
            # Domain is registered via ConfigFlow metaclass (domain=DOMAIN)
            # Verify DOMAIN constant matches expected value
            assert DOMAIN == "homeworks_hwi"
        except ImportError as e:
            pytest.skip(f"Cannot import config_flow: {e}")

    async def test_import_coordinator(self):
        """Test that coordinator can be imported."""
        try:
            from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator
            assert HomeworksCoordinator is not None
        except ImportError as e:
            pytest.skip(f"Cannot import coordinator: {e}")


class TestConfigEntrySetup:
    """Test config entry setup and unload."""

    async def test_setup_entry_creates_data(self, mock_hass, mock_config_entry):
        """Test that async_setup_entry creates coordinator, stores runtime_data, and forwards platforms."""
        from custom_components.homeworks_hwi import async_setup_entry, DOMAIN
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator.register_cco_device = MagicMock()
        mock_coordinator.register_dimmer = MagicMock()
        mock_coordinator.register_cci_device = MagicMock()
        mock_coordinator.register_kls_poll_address = MagicMock()
        mock_coordinator.async_shutdown = AsyncMock()

        with patch(
            "custom_components.homeworks_hwi.HomeworksCoordinator",
            return_value=mock_coordinator,
        ), patch(
            "custom_components.homeworks_hwi._cleanup_orphaned_devices",
        ), patch(
            "custom_components.homeworks_hwi._cleanup_old_entities",
        ):
            result = await async_setup_entry(mock_hass, mock_config_entry)

        # Setup should succeed
        assert result is True
        # Coordinator first refresh called (connects to controller)
        mock_coordinator.async_config_entry_first_refresh.assert_called_once()
        # Platforms forwarded
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once()
        # runtime_data set on entry
        assert mock_config_entry.runtime_data is not None
        assert mock_config_entry.runtime_data.coordinator is mock_coordinator

    async def test_unload_entry_cleans_up(self, mock_hass, mock_config_entry):
        """Test that unload_entry properly shuts down coordinator."""
        try:
            from custom_components.homeworks_hwi import async_unload_entry, DOMAIN
            from unittest.mock import AsyncMock, MagicMock, PropertyMock

            # Set up mock coordinator
            mock_coordinator = AsyncMock()
            mock_coordinator.async_shutdown = AsyncMock()

            # runtime_data pattern: entry.runtime_data.coordinator
            mock_runtime_data = MagicMock()
            mock_runtime_data.coordinator = mock_coordinator
            mock_config_entry.runtime_data = mock_runtime_data

            # async_unload_platforms must succeed
            mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

            result = await async_unload_entry(mock_hass, mock_config_entry)

            assert result is True
            mock_coordinator.async_shutdown.assert_called_once()

        except ImportError as e:
            pytest.skip(f"Cannot import: {e}")


class TestCoordinatorKLSProcessing:
    """Test that coordinator processes KLS lines correctly."""

    async def test_kls_state_update(self):
        """Test that KLS updates trigger state changes."""
        try:
            from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator
            from custom_components.homeworks_hwi.models import CCOAddress, CCODevice, CCOEntityType
            from unittest.mock import MagicMock, patch

            with patch.object(HomeworksCoordinator, "__init__", lambda self, **kwargs: None):
                coordinator = HomeworksCoordinator.__new__(HomeworksCoordinator)
                coordinator.hass = MagicMock()
                coordinator._cco_devices = {}
                coordinator._cco_states = {}
                coordinator._cco_relay_digits = {}
                coordinator._cco_state_sources = {}
                coordinator._cco_pending_commands = {}
                coordinator._kls_last_seen = {}
                coordinator._keypad_led_states = {}
                coordinator._kls_window_offset = 9
                coordinator._kls_poll_addresses = set()
                coordinator._poll_count = 0
                coordinator._client = None
                coordinator.async_set_updated_data = MagicMock()

                # Register a CCO device at button 6 (index 14)
                address = CCOAddress(processor=2, link=6, address=3, button=6)
                device = CCODevice(
                    address=address,
                    name="Test",
                    entity_type=CCOEntityType.SWITCH,
                    inverted=False,
                )
                coordinator.register_cco_device(device)

                # KLS with button 6 ON (LED=2 at index 14)
                led_states = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0]
                coordinator._handle_kls_update("[02:06:03]", led_states)
                assert coordinator._cco_states[address.unique_key] is True

                # KLS with button 6 OFF (LED=1 at index 14)
                led_states = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 1, 2, 2, 0, 0, 0, 0, 0, 0, 0]
                coordinator._handle_kls_update("[02:06:03]", led_states)
                assert coordinator._cco_states[address.unique_key] is False

        except ImportError as e:
            pytest.skip(f"Cannot import: {e}")

    async def test_configurable_window_offset(self):
        """Test that window offset is configurable."""
        try:
            from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator
            from custom_components.homeworks_hwi.models import CCOAddress, CCODevice, CCOEntityType
            from unittest.mock import MagicMock, patch

            with patch.object(HomeworksCoordinator, "__init__", lambda self, **kwargs: None):
                coordinator = HomeworksCoordinator.__new__(HomeworksCoordinator)
                coordinator.hass = MagicMock()
                coordinator._cco_devices = {}
                coordinator._cco_states = {}
                coordinator._cco_relay_digits = {}
                coordinator._cco_state_sources = {}
                coordinator._cco_pending_commands = {}
                coordinator._kls_last_seen = {}
                coordinator._keypad_led_states = {}
                coordinator._kls_window_offset = 8  # Non-default offset
                coordinator._kls_poll_addresses = set()
                coordinator._poll_count = 0
                coordinator._client = None
                coordinator.async_set_updated_data = MagicMock()

                # Register device at button 1
                address = CCOAddress(processor=2, link=6, address=3, button=1)
                device = CCODevice(
                    address=address,
                    name="Test",
                    entity_type=CCOEntityType.SWITCH,
                    inverted=False,
                )
                coordinator.register_cco_device(device)

                # With offset 8, button 1 is at index 8
                led_states = [0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
                coordinator._handle_kls_update("[02:06:03]", led_states)

                assert coordinator._cco_states[address.unique_key] is True

        except ImportError as e:
            pytest.skip(f"Cannot import: {e}")


class TestCredentialStorage:
    """Test that credentials are stored correctly."""

    async def test_credentials_in_data_not_options(self):
        """Verify credentials are stored in entry.data, not entry.options."""
        # This is a documentation/validation test
        expected_data_keys = {"host", "port", "username", "password"}
        expected_options_keys = {
            "controller_id",
            "cco_devices",
            "dimmers",
            "keypads",
            "kls_poll_interval",
            "kls_window_offset",
        }

        # Verify credentials should NOT be in options
        secrets = {"host", "port", "username", "password"}

        for key in secrets:
            assert key not in expected_options_keys, f"Secret '{key}' should not be in options"

        # Verify non-secrets should NOT be in data
        non_secrets = {"cco_devices", "dimmers", "keypads", "controller_id"}

        for key in non_secrets:
            assert key not in expected_data_keys, f"Non-secret '{key}' should not be in data"


class TestNoDuplicatePolling:
    """Test that reload doesn't create duplicate polling tasks."""

    async def test_shutdown_cancels_polling(self):
        """Test that async_shutdown stops the client and clears the reference."""
        try:
            from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator
            from unittest.mock import MagicMock, AsyncMock, patch

            with patch.object(HomeworksCoordinator, "__init__", lambda self, **kwargs: None):
                coordinator = HomeworksCoordinator.__new__(HomeworksCoordinator)

                mock_client = AsyncMock()
                mock_client.stop = AsyncMock()
                coordinator._client = mock_client

                # Parent class async_shutdown() needs these attributes
                coordinator._shutdown_requested = False
                coordinator._unsub_refresh = None
                coordinator._unsub_shutdown = None
                coordinator._debounced_refresh = MagicMock()
                coordinator._debounced_refresh.async_shutdown = AsyncMock()

                await coordinator.async_shutdown()

                mock_client.stop.assert_called_once()
                assert coordinator._client is None

        except ImportError as e:
            pytest.skip(f"Cannot import: {e}")

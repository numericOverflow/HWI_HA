"""Pytest configuration for Homeworks HWI integration tests.

All imports use the full package path: custom_components.homeworks_hwi.xxx
The repo root is on sys.path (via pyproject.toml pythonpath = ["."]) so
the package is importable as 'custom_components.homeworks_hwi'.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "requires_ha: mark test as requiring Home Assistant"
    )


# =============================================================================
# Protocol-Layer Fixtures (always available)
# =============================================================================


@pytest.fixture
async def fake_controller():
    """Create and start a fake Homeworks controller on a random port."""
    from tests.fake_controller import FakeHomeworksController

    controller = FakeHomeworksController(port=0)
    await controller.start()
    yield controller
    await controller.stop()


@pytest.fixture
def sample_kls_string():
    """Return a sample 24-digit KLS string with known button states.

    Window (indices 9-16): 22211211
    Button states: OFF, OFF, OFF, ON, ON, OFF, ON, ON
    """
    return "000000000222112110000000"


@pytest.fixture
def sample_kls_all_on():
    """KLS string with all 8 CCO buttons ON."""
    return "000000000111111110000000"


@pytest.fixture
def sample_kls_all_off():
    """KLS string with all 8 CCO buttons OFF."""
    return "000000000222222220000000"


@pytest.fixture
def cco_address_factory():
    """Factory for creating CCOAddress instances."""
    from custom_components.homeworks_hwi.models import CCOAddress

    def _make(processor=2, link=6, address=3, button=6):
        return CCOAddress(processor=processor, link=link, address=address, button=button)

    return _make


@pytest.fixture
def cco_device_factory(cco_address_factory):
    """Factory for creating CCODevice instances."""
    from custom_components.homeworks_hwi.models import CCODevice, CCOEntityType

    def _make(
        processor=2,
        link=6,
        address=3,
        button=6,
        name="Test Device",
        entity_type=CCOEntityType.SWITCH,
        inverted=False,
        area=None,
    ):
        addr = cco_address_factory(processor, link, address, button)
        return CCODevice(
            address=addr,
            name=name,
            entity_type=entity_type,
            inverted=inverted,
            area=area,
        )

    return _make


# =============================================================================
# HA Mock Fixtures (for integration tests)
# =============================================================================


@pytest.fixture
def mock_hass():
    """Create a minimal mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_loaded_entries = MagicMock(return_value=[])
    hass.bus = MagicMock()
    hass.bus.async_listen_once = MagicMock(return_value=lambda: None)
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    hass.loop = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock ConfigEntry with standard test data."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Test Homeworks"
    entry.domain = "homeworks_hwi"
    entry.version = 1
    entry.data = {
        "host": "192.168.1.100",
        "port": 23,
        "username": "testuser",
        "password": "testpass",
    }
    entry.options = {
        "controller_id": "test_controller",
        "cco_devices": [
            {
                "name": "Kitchen Light",
                "addr": "[02:06:03]",
                "button_number": 6,
                "entity_type": "switch",
                "inverted": False,
            },
            {
                "name": "Living Room Fan",
                "addr": "[02:06:03]",
                "button_number": 4,
                "entity_type": "fan",
                "inverted": False,
            },
            {
                "name": "Bedroom Light",
                "addr": "[02:06:04]",
                "button_number": 1,
                "entity_type": "light",
                "inverted": False,
            },
            {
                "name": "Front Door Lock",
                "addr": "[02:06:05]",
                "button_number": 1,
                "entity_type": "lock",
                "inverted": False,
            },
            {
                "name": "Garage Cover",
                "addr": "[02:06:05]",
                "button_number": 2,
                "entity_type": "cover",
                "inverted": False,
            },
            {
                "name": "HVAC Zone 1",
                "addr": "[02:06:06]",
                "button_number": 1,
                "entity_type": "climate",
                "inverted": False,
            },
        ],
        "dimmers": [
            {
                "name": "Dining Room",
                "addr": "[01:01:00:02:04]",
                "rate": 1.0,
            },
        ],
        "keypads": [
            {
                "name": "Entry Keypad",
                "addr": "[02:08:02]",
                "buttons": [
                    {"number": 1, "name": "All On"},
                    {"number": 2, "name": "All Off"},
                ],
            },
        ],
        "cci_devices": [
            {
                "name": "Front Door",
                "addr": "[02:05:01]",
                "input_number": 1,
                "device_class": "door",
            },
        ],
        "rpm_covers": [
            {
                "name": "Master Shade",
                "addr": "[01:04:01:01:01]",
            },
        ],
        "qed_covers": [
            {
                "name": "Living Room Shade",
                "addr": "[01:04:01:01]",
            },
        ],
        "kls_poll_interval": 10,
        "kls_window_offset": 9,
        "ccos": [],
        "covers": [],
        "locks": [],
    }
    entry.runtime_data = None
    return entry


@pytest.fixture
def mock_config_entry_legacy():
    """Create a mock ConfigEntry with legacy v1 format (for migration tests)."""
    entry = MagicMock()
    entry.entry_id = "legacy_entry_456"
    entry.title = "Legacy Homeworks"
    entry.domain = "homeworks_hwi"
    entry.version = 1
    entry.data = {
        "host": "192.168.1.200",
        "port": 23,
        "username": None,
        "password": None,
    }
    entry.options = {
        "controller_id": "legacy_controller",
        "ccos": [
            {
                "name": "Old Switch",
                "addr": "[02:06:03]",
                "relay_number": 6,
                "inverted": False,
            },
        ],
        "covers": [
            {
                "name": "Old Cover",
                "addr": "[02:06:04]",
                "inverted": False,
            },
        ],
        "locks": [
            {
                "name": "Old Lock",
                "addr": "[02:06:05]",
                "relay_number": 1,
                "inverted": False,
            },
        ],
        "dimmers": [],
        "keypads": [],
        "kls_poll_interval": 10,
        "kls_window_offset": 9,
    }
    return entry


@pytest.fixture
def mock_coordinator():
    """Create a mock HomeworksCoordinator with common test state."""
    coordinator = MagicMock()
    coordinator.connected = True
    coordinator.controller_id = "test_controller"
    coordinator.update_interval = MagicMock(total_seconds=MagicMock(return_value=10))
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_request_refresh = AsyncMock()

    # State caches
    coordinator._cco_states = {}
    coordinator._cco_devices = {}
    coordinator._dimmer_states = {}
    coordinator._keypad_led_states = {}
    coordinator._kls_poll_addresses = set()
    coordinator._dimmer_addresses = set()
    coordinator._cci_states = {}
    coordinator._cci_devices = {}
    coordinator._button_callbacks = {}
    coordinator._cci_callbacks = {}

    # Methods
    coordinator.register_cco_device = MagicMock()
    coordinator.unregister_cco_device = MagicMock()
    coordinator.register_dimmer = MagicMock()
    coordinator.unregister_dimmer = MagicMock()
    coordinator.register_kls_poll_address = MagicMock()
    coordinator.get_cco_state = MagicMock(return_value=False)
    coordinator.get_dimmer_level = MagicMock(return_value=0)
    coordinator.get_keypad_led_states = MagicMock(return_value=[0] * 24)
    coordinator.async_cco_close = AsyncMock(return_value=True)
    coordinator.async_cco_open = AsyncMock(return_value=True)
    coordinator.async_fade_dim = AsyncMock(return_value=True)
    coordinator.async_stop_dim = AsyncMock(return_value=True)
    coordinator.async_motor_cover_up = AsyncMock(return_value=True)
    coordinator.async_motor_cover_down = AsyncMock(return_value=True)
    coordinator.async_motor_cover_stop = AsyncMock(return_value=True)
    coordinator.async_keypad_button_press = AsyncMock(return_value=True)
    coordinator.async_keypad_button_release = AsyncMock(return_value=True)
    coordinator.async_request_keypad_led_states = AsyncMock(return_value=True)
    coordinator.async_request_dimmer_level = AsyncMock(return_value=True)

    # Health
    health = MagicMock()
    health.connected = True
    health.last_message_time = None
    health.last_kls_time = None
    health.reconnect_count = 0
    health.poll_failure_count = 0
    health.parse_error_count = 0
    health.last_error = None
    coordinator.health = health

    return coordinator

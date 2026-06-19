"""Tests for HomeworksCoordinator lifecycle, state engine, and callbacks.

Tests the coordinator's core responsibilities:
- Device registration/unregistration
- KLS state engine (CCO state derivation from LED strings)
- Dimmer state tracking
- CCI state derivation from button events
- Button event dispatch
- Connection state management
- Polling behavior

NOTE: These tests require Home Assistant to be installed since the coordinator
imports from homeassistant.helpers.update_coordinator.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import timedelta

from models import CCOAddress, CCODevice, CCOEntityType, normalize_address

# All coordinator tests require HA since coordinator.py imports homeassistant
pytestmark = pytest.mark.requires_ha


def _import_coordinator():
    """Import coordinator, skip if HA not available."""
    try:
        from coordinator import HomeworksCoordinator
        return HomeworksCoordinator
    except ImportError:
        pytest.skip("Home Assistant not installed")


def _make_bare_coordinator():
    """Create a coordinator instance bypassing __init__."""
    HomeworksCoordinator = _import_coordinator()
    with patch.object(HomeworksCoordinator, "__init__", lambda self, *a, **kw: None):
        coord = HomeworksCoordinator.__new__(HomeworksCoordinator)
        coord._cco_devices = {}
        coord._cco_states = {}
        coord._kls_poll_addresses = set()
        coord._keypad_led_states = {}
        coord._dimmer_states = {}
        coord._dimmer_addresses = set()
        coord._cci_devices = {}
        coord._cci_states = {}
        coord._cci_callbacks = {}
        coord._button_callbacks = {}
        coord._kls_window_offset = 9
        coord._poll_count = 0
        coord._client = None
        coord.hass = MagicMock()
        coord.async_set_updated_data = MagicMock()
        return coord


# =============================================================================
# Device Registration Tests
# =============================================================================


class TestCCODeviceRegistration:
    """Tests for CCO device registration and unregistration."""

    def test_register_cco_device_adds_to_registry(self, cco_device_factory):
        """Registering a CCO device adds it to the device and state caches."""
        coord = _make_bare_coordinator()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)

        assert device.address.unique_key in coord._cco_devices
        assert device.address.unique_key in coord._cco_states
        assert coord._cco_states[device.address.unique_key] is False
        assert "[02:06:03]" in coord._kls_poll_addresses

    def test_register_multiple_cco_devices_same_address(self, cco_device_factory):
        """Multiple CCO devices on same keypad address share KLS polling."""
        coord = _make_bare_coordinator()
        device1 = cco_device_factory(button=1)
        device2 = cco_device_factory(button=6)
        coord.register_cco_device(device1)
        coord.register_cco_device(device2)

        assert len(coord._cco_devices) == 2
        assert len(coord._kls_poll_addresses) == 1  # Same KLS address

    def test_unregister_cco_device_removes_from_caches(self, cco_device_factory):
        """Unregistering a CCO device removes it from device and state caches."""
        coord = _make_bare_coordinator()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)
        coord.unregister_cco_device(device.address)

        assert device.address.unique_key not in coord._cco_devices
        assert device.address.unique_key not in coord._cco_states


class TestDimmerRegistration:
    """Tests for dimmer registration and unregistration."""

    def test_register_dimmer(self):
        """Registering a dimmer adds it to tracking sets."""
        coord = _make_bare_coordinator()
        coord.register_dimmer("1:1:0:2:4")

        assert "[01:01:00:02:04]" in coord._dimmer_addresses
        assert coord._dimmer_states["[01:01:00:02:04]"] == 0

    def test_unregister_dimmer(self):
        """Unregistering a dimmer removes it from tracking."""
        coord = _make_bare_coordinator()
        coord.register_dimmer("1:1:0:2:4")
        coord.unregister_dimmer("1:1:0:2:4")

        assert "[01:01:00:02:04]" not in coord._dimmer_addresses
        assert "[01:01:00:02:04]" not in coord._dimmer_states


class TestCCIDeviceRegistration:
    """Tests for CCI device registration."""

    def test_register_cci_device(self):
        """Registering a CCI device adds it to the registry."""
        coord = _make_bare_coordinator()
        mock_device = MagicMock()
        coord.register_cci_device("[02:05:01]", 1, mock_device)

        key = (2, 5, 1, 1)
        assert key in coord._cci_devices
        assert coord._cci_states[key] is False

    def test_unregister_cci_device(self):
        """Unregistering a CCI device removes it."""
        coord = _make_bare_coordinator()
        mock_device = MagicMock()
        coord.register_cci_device("[02:05:01]", 1, mock_device)
        coord.unregister_cci_device("[02:05:01]", 1)

        key = (2, 5, 1, 1)
        assert key not in coord._cci_devices
        assert key not in coord._cci_states


# =============================================================================
# KLS State Engine Tests
# =============================================================================


class TestKLSStateEngine:
    """Tests for the KLS → CCO state derivation engine."""

    def _make_coordinator_with_device(self, button=6, inverted=False):
        """Helper to create a coordinator with one registered device."""
        coord = _make_bare_coordinator()
        device = CCODevice(
            address=CCOAddress(processor=2, link=6, address=3, button=button),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
            inverted=inverted,
        )
        coord.register_cco_device(device)
        return coord, device

    def test_kls_update_turns_device_on(self):
        """KLS with LED=1 at correct index sets device ON."""
        coord, device = self._make_coordinator_with_device(button=6)

        # Button 6 at index 14 (offset 9 + button 6 - 1 = 14)
        # LED=1 means relay closed = ON
        led_states = [0] * 24
        led_states[14] = 1  # Button 6 = ON

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord._cco_states[device.address.unique_key] is True
        coord.async_set_updated_data.assert_called_once()

    def test_kls_update_turns_device_off(self):
        """KLS with LED=2 at correct index sets device OFF."""
        coord, device = self._make_coordinator_with_device(button=6)

        # First turn on
        led_states_on = [0] * 24
        led_states_on[14] = 1
        coord._handle_kls_update("[02:06:03]", led_states_on)

        # Then turn off (LED=2 = relay open)
        coord.async_set_updated_data.reset_mock()
        led_states_off = [0] * 24
        led_states_off[14] = 2
        coord._handle_kls_update("[02:06:03]", led_states_off)

        assert coord._cco_states[device.address.unique_key] is False

    def test_kls_update_inverted_device(self):
        """Inverted device interprets LED=1 as OFF and LED=2 as ON."""
        coord, device = self._make_coordinator_with_device(button=6, inverted=True)

        led_states = [0] * 24
        led_states[14] = 1  # Normally ON, but inverted = OFF

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord._cco_states[device.address.unique_key] is False

    def test_kls_update_no_change_no_notification(self):
        """No state change → no notification to listeners."""
        coord, device = self._make_coordinator_with_device(button=6)

        # Both updates have same state (OFF by default, OFF via digit 2)
        led_states = [0] * 24
        led_states[14] = 2  # OFF (relay open)
        coord._handle_kls_update("[02:06:03]", led_states)

        # State was already False (default), so no change notification
        coord.async_set_updated_data.assert_not_called()

    def test_kls_update_unrelated_address_ignored(self):
        """KLS update for unregistered address does not affect registered devices."""
        coord, device = self._make_coordinator_with_device(button=6)

        led_states = [0] * 24
        led_states[14] = 1  # ON

        # Different address
        coord._handle_kls_update("[02:06:99]", led_states)

        assert coord._cco_states[device.address.unique_key] is False

    def test_kls_update_multiple_devices_same_address(self):
        """KLS update correctly updates multiple devices on same keypad."""
        coord = _make_bare_coordinator()

        dev1 = CCODevice(
            address=CCOAddress(2, 6, 3, 4), name="Dev4", entity_type=CCOEntityType.SWITCH
        )
        dev2 = CCODevice(
            address=CCOAddress(2, 6, 3, 6), name="Dev6", entity_type=CCOEntityType.SWITCH
        )
        coord.register_cco_device(dev1)
        coord.register_cco_device(dev2)

        # Button 4 at index 12 = ON (LED=1), Button 6 at index 14 = OFF (LED=2)
        led_states = [0] * 24
        led_states[12] = 1  # Button 4 ON
        led_states[14] = 2  # Button 6 OFF

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord._cco_states[dev1.address.unique_key] is True
        assert coord._cco_states[dev2.address.unique_key] is False


# =============================================================================
# Dimmer State Tests
# =============================================================================


class TestDimmerStateTracking:
    """Tests for dimmer level state management."""

    def test_dimmer_update_changes_state(self):
        """Dimmer level update updates the state cache."""
        coord = _make_bare_coordinator()
        coord._dimmer_states["[01:01:00:02:04]"] = 0
        coord._dimmer_addresses = {"[01:01:00:02:04]"}

        coord._handle_dimmer_update("[01:01:00:02:04]", 75)

        assert coord._dimmer_states["[01:01:00:02:04]"] == 75

    def test_dimmer_update_same_level_no_notification(self):
        """Dimmer update with same level does not notify."""
        coord = _make_bare_coordinator()
        coord._dimmer_states["[01:01:00:02:04]"] = 50
        coord._dimmer_addresses = {"[01:01:00:02:04]"}

        coord._handle_dimmer_update("[01:01:00:02:04]", 50)

        coord.async_set_updated_data.assert_not_called()

    def test_get_dimmer_level_returns_cached(self):
        """get_dimmer_level returns the cached value."""
        coord = _make_bare_coordinator()
        coord._dimmer_states["[01:01:00:02:04]"] = 80

        assert coord.get_dimmer_level("[01:01:00:02:04]") == 80

    def test_get_dimmer_level_unregistered_returns_zero(self):
        """get_dimmer_level for unknown address returns 0."""
        coord = _make_bare_coordinator()

        assert coord.get_dimmer_level("[99:99:99]") == 0


# =============================================================================
# CCI Button Event → State Tests
# =============================================================================


class TestCCIStateDerivation:
    """Tests for CCI state derivation from button hold/release events."""

    def _make_coordinator_with_cci(self):
        """Helper to create coordinator with registered CCI device."""
        coord = _make_bare_coordinator()
        mock_device = MagicMock()
        coord.register_cci_device("[02:05:01]", 1, mock_device)
        return coord

    def test_kbh_sets_cci_on(self):
        """KBH (hold) event sets CCI state to ON."""
        coord = self._make_coordinator_with_cci()
        coord._handle_cci_button_event("[02:05:01]", 1, True)

        key = (2, 5, 1, 1)
        assert coord._cci_states[key] is True

    def test_kbr_sets_cci_off(self):
        """KBR (release) event sets CCI state to OFF."""
        coord = self._make_coordinator_with_cci()
        coord._handle_cci_button_event("[02:05:01]", 1, True)
        coord._handle_cci_button_event("[02:05:01]", 1, False)

        key = (2, 5, 1, 1)
        assert coord._cci_states[key] is False

    def test_cci_event_unregistered_device_ignored(self):
        """CCI event for unregistered device does nothing."""
        coord = self._make_coordinator_with_cci()
        coord._handle_cci_button_event("[02:05:01]", 99, True)

        assert (2, 5, 1, 99) not in coord._cci_states

    def test_cci_callback_invoked_on_state_change(self):
        """Registered CCI callback is called on state change."""
        coord = self._make_coordinator_with_cci()

        callback_mock = MagicMock()
        key = (2, 5, 1, 1)
        coord._cci_callbacks[key] = [callback_mock]

        coord._handle_cci_button_event("[02:05:01]", 1, True)

        callback_mock.assert_called_once_with(True)


# =============================================================================
# Button Event Dispatch Tests
# =============================================================================


class TestButtonEventDispatch:
    """Tests for keypad button event callback dispatch."""

    def test_button_callback_dispatched(self):
        """Registered button callback receives events."""
        coord = _make_bare_coordinator()
        cb = MagicMock()
        coord._button_callbacks["[02:08:02]"] = [cb]

        coord._dispatch_button_event("[02:08:02]", 1, "pressed")

        cb.assert_called_once_with("[02:08:02]", 1, "pressed")

    def test_button_callback_unregistered_address_no_error(self):
        """Button event for unregistered address does not raise."""
        coord = _make_bare_coordinator()
        # Should not raise
        coord._dispatch_button_event("[99:99:99]", 1, "pressed")

    def test_register_button_callback_returns_unregister(self):
        """register_button_callback returns a callable that unregisters."""
        coord = _make_bare_coordinator()
        cb = MagicMock()
        unregister = coord.register_button_callback("[02:08:02]", cb)

        assert "[02:08:02]" in coord._button_callbacks
        assert cb in coord._button_callbacks["[02:08:02]"]

        unregister()

        assert "[02:08:02]" not in coord._button_callbacks

    def test_register_cci_callback_returns_unregister(self):
        """register_cci_callback returns a callable that unregisters."""
        coord = _make_bare_coordinator()
        cb = MagicMock()
        unregister = coord.register_cci_callback("[02:05:01]", 1, cb)

        key = (2, 5, 1, 1)
        assert key in coord._cci_callbacks
        assert cb in coord._cci_callbacks[key]

        unregister()

        assert key not in coord._cci_callbacks


# =============================================================================
# Optimistic Update Tests
# =============================================================================


class TestOptimisticUpdates:
    """Tests for optimistic state updates after commands."""

    def _make_coordinator_with_client(self):
        """Helper to create coordinator with mocked client."""
        coord = _make_bare_coordinator()

        client = AsyncMock()
        client.connected = True
        client.cco_close = AsyncMock(return_value=True)
        client.cco_open = AsyncMock(return_value=True)
        client.motor_cover_up = AsyncMock(return_value=True)
        client.motor_cover_down = AsyncMock(return_value=True)
        client.motor_cover_stop = AsyncMock(return_value=True)
        coord._client = client

        return coord

    @pytest.mark.asyncio
    async def test_cco_close_optimistic_on(self, cco_device_factory):
        """async_cco_close sets optimistic state to True."""
        coord = self._make_coordinator_with_client()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)

        result = await coord.async_cco_close(device.address)

        assert result is True
        assert coord._cco_states[device.address.unique_key] is True

    @pytest.mark.asyncio
    async def test_cco_open_optimistic_off(self, cco_device_factory):
        """async_cco_open sets optimistic state to False."""
        coord = self._make_coordinator_with_client()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)
        coord._cco_states[device.address.unique_key] = True

        result = await coord.async_cco_open(device.address)

        assert result is True
        assert coord._cco_states[device.address.unique_key] is False

    @pytest.mark.asyncio
    async def test_motor_cover_up_optimistic_level(self):
        """async_motor_cover_up sets dimmer to RPM_MOTOR_UP value."""
        # RPM_MOTOR_UP = 16 (defined in coordinator.py)
        RPM_MOTOR_UP = 16

        coord = self._make_coordinator_with_client()
        coord._dimmer_states["[01:04:01:01:01]"] = 0

        result = await coord.async_motor_cover_up("[01:04:01:01:01]")

        assert result is True
        assert coord._dimmer_states["[01:04:01:01:01]"] == RPM_MOTOR_UP

    @pytest.mark.asyncio
    async def test_motor_cover_down_optimistic_level(self):
        """async_motor_cover_down sets dimmer to RPM_MOTOR_DOWN value."""
        # RPM_MOTOR_DOWN = 35 (defined in coordinator.py)
        RPM_MOTOR_DOWN = 35

        coord = self._make_coordinator_with_client()
        coord._dimmer_states["[01:04:01:01:01]"] = 0

        result = await coord.async_motor_cover_down("[01:04:01:01:01]")

        assert result is True
        assert coord._dimmer_states["[01:04:01:01:01]"] == RPM_MOTOR_DOWN

    @pytest.mark.asyncio
    async def test_command_when_disconnected_returns_false(self, cco_device_factory):
        """Commands return False when client is None."""
        coord = _make_bare_coordinator()
        coord._client = None

        device = cco_device_factory(button=6)
        result = await coord.async_cco_close(device.address)

        assert result is False


# =============================================================================
# Connection State Tests
# =============================================================================


class TestConnectionState:
    """Tests for connection state properties."""

    def test_connected_true_when_client_connected(self):
        """connected returns True when client exists and is connected."""
        coord = _make_bare_coordinator()
        coord._client = MagicMock()
        coord._client.connected = True

        assert coord.connected is True

    def test_connected_false_when_no_client(self):
        """connected returns False when client is None."""
        coord = _make_bare_coordinator()
        coord._client = None

        assert coord.connected is False

    def test_connected_false_when_client_disconnected(self):
        """connected returns False when client exists but is disconnected."""
        coord = _make_bare_coordinator()
        coord._client = MagicMock()
        coord._client.connected = False

        assert coord.connected is False

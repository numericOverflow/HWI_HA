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
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
    call,
)
from datetime import timedelta

from custom_components.homeworks_hwi.models import (
    CCOAddress,
    CCODevice,
    CCOEntityType,
    normalize_address,
)
from custom_components.homeworks_hwi.hwi_protocol.messages import (
    CCO_RELAY_CLOSED_DIGIT,
    CCO_RELAY_OPEN_DIGIT,
)
from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator

# A relay-window digit with no documented meaning. Digit 0 is explicitly
# "UNDOCUMENTED & UNDISCOVERED" per L232/cco_kls_state.htm, so it must decode
# to unknown rather than OFF.
CCO_RELAY_UNDOCUMENTED_DIGIT = 0


def _make_bare_coordinator():
    """Create a coordinator instance bypassing __init__."""
    with patch.object(HomeworksCoordinator, "__init__", lambda self, *a, **kw: None):
        coord = HomeworksCoordinator.__new__(HomeworksCoordinator)
        coord._cco_devices = {}
        coord._cco_states = {}
        coord._cco_relay_digits = {}
        coord._cco_state_sources = {}
        coord._cco_pending_commands = {}
        coord._kls_last_seen = {}
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
        # Monotonic clock used for KLS timestamps and command-mismatch ages.
        coord.hass.loop.time = MagicMock(return_value=1000.0)
        coord.async_set_updated_data = MagicMock()
        return coord


# =============================================================================
# Poll Address Pre-registration Tests
# =============================================================================


class TestPreregisterPollAddresses:
    """Tests for seeding KLS poll addresses from config before first refresh.

    Entities only register in async_added_to_hass, which runs after
    async_config_entry_first_refresh(), so without pre-registration the
    startup sweep would send nothing and every CCO would sit unknown until a
    later poll tick (L232/cco_kls_state.htm implementation note 2).
    """

    def _coord_with_options(self, options):
        coord = _make_bare_coordinator()
        coord.config_entry = MagicMock()
        coord.config_entry.options = options
        coord._preregister_poll_addresses_from_options()
        return coord

    def test_cco_addresses_preregistered(self):
        coord = self._coord_with_options(
            {"cco_devices": [{"addr": "[02:06:03]"}]}
        )

        assert coord._kls_poll_addresses == {"[02:06:03]"}

    def test_relay_suffix_stripped(self):
        """Polling is per module address, so any ",relay" suffix is dropped."""
        coord = self._coord_with_options(
            {"cco_devices": [{"addr": "[02:06:03],6"}]}
        )

        assert coord._kls_poll_addresses == {"[02:06:03]"}

    def test_one_address_per_module(self):
        """8 relays on one board produce a single RKLS target, not eight."""
        coord = self._coord_with_options(
            {
                "cco_devices": [
                    {"addr": f"2:6:3,{relay}"} for relay in range(1, 9)
                ]
            }
        )

        assert coord._kls_poll_addresses == {"[02:06:03]"}

    def test_keypads_preregistered_alongside_ccos(self):
        coord = self._coord_with_options(
            {
                "cco_devices": [{"addr": "2:6:3,1"}],
                "keypads": [{"addr": "2:6:4"}],
            }
        )

        assert coord._kls_poll_addresses == {"[02:06:03]", "[02:06:04]"}

    def test_missing_and_unparsable_addresses_skipped(self):
        """A bad entry must not abort pre-registration of the good ones."""
        coord = self._coord_with_options(
            {
                "cco_devices": [
                    {},
                    {"addr": "not-an-address"},
                    {"addr": "2:6:3,1"},
                ]
            }
        )

        assert coord._kls_poll_addresses == {"[02:06:03]"}

    def test_no_options_is_safe(self):
        coord = self._coord_with_options({})

        assert coord._kls_poll_addresses == set()


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
        # Unknown, not False: a CCO relay latches and holds its position
        # across power loss, so "off" would be a guess.
        assert coord._cco_states[device.address.unique_key] is None
        assert coord._cco_state_sources[device.address.unique_key] == "unknown"
        assert "[02:06:03]" in coord._kls_poll_addresses

    def test_register_cco_device_preserves_known_state(self, cco_device_factory):
        """Re-registering must not wipe a state already learned from KLS."""
        coord = _make_bare_coordinator()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)
        coord._cco_states[device.address.unique_key] = True

        coord.register_cco_device(device)

        assert coord._cco_states[device.address.unique_key] is True

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
        """KLS with CLOSED digit at correct index sets device ON."""
        coord, device = self._make_coordinator_with_device(button=6)

        # Button 6 at index 14 (offset 9 + button 6 - 1 = 14)
        led_states = [0] * 24
        led_states[14] = CCO_RELAY_CLOSED_DIGIT  # Button 6 = ON

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord._cco_states[device.address.unique_key] is True
        coord.async_set_updated_data.assert_called_once()

    def test_kls_update_turns_device_off(self):
        """KLS with OPEN digit at correct index sets device OFF."""
        coord, device = self._make_coordinator_with_device(button=6)

        # First turn on
        led_states_on = [0] * 24
        led_states_on[14] = CCO_RELAY_CLOSED_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states_on)

        # Then turn off
        coord.async_set_updated_data.reset_mock()
        led_states_off = [0] * 24
        led_states_off[14] = CCO_RELAY_OPEN_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states_off)

        assert coord._cco_states[device.address.unique_key] is False

    def test_kls_update_inverted_device(self):
        """Inverted device interprets CLOSED digit as OFF."""
        coord, device = self._make_coordinator_with_device(button=6, inverted=True)

        led_states = [0] * 24
        led_states[14] = CCO_RELAY_CLOSED_DIGIT  # Normally ON, but inverted = OFF

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord._cco_states[device.address.unique_key] is False

    def test_kls_update_no_change_no_notification(self):
        """Identical repeat KLS → no notification to listeners.

        Notification is driven by "did anything change", where "anything" is
        either a derived CCO state or the raw LED string (LED binary sensors
        need the latter even on keypads with no CCO devices). A repeat of the
        exact same KLS changes neither.
        """
        coord, device = self._make_coordinator_with_device(button=6)

        led_states = [0] * 24
        led_states[14] = CCO_RELAY_OPEN_DIGIT

        # First KLS is new LED data, so it does notify.
        coord._handle_kls_update("[02:06:03]", led_states)
        coord.async_set_updated_data.assert_called_once()

        # Identical repeat: neither CCO state nor LED string changed.
        coord.async_set_updated_data.reset_mock()
        coord._handle_kls_update("[02:06:03]", list(led_states))

        coord.async_set_updated_data.assert_not_called()

    def test_kls_update_led_change_without_cco_change_notifies(self):
        """An LED-only change notifies so LED binary sensors get written.

        A keypad LED can change (scene tracked by the processor moved) while no
        CCO relay state changes at all. LED sensors must still be updated on the
        pushed KLS rather than waiting for the next poll.
        """
        coord, device = self._make_coordinator_with_device(button=6)

        led_states = [0] * 24
        led_states[14] = CCO_RELAY_OPEN_DIGIT  # device now known OFF
        coord._handle_kls_update("[02:06:03]", led_states)
        coord.async_set_updated_data.reset_mock()

        # Flip LED 1 (index 0) — outside the CCO button window, so no CCO change.
        led_states_2 = list(led_states)
        led_states_2[0] = 1
        coord._handle_kls_update("[02:06:03]", led_states_2)

        assert coord._cco_states[device.address.unique_key] is False
        coord.async_set_updated_data.assert_called_once()

    def test_get_keypad_led_states_unknown_returns_none(self):
        """A keypad with no KLS seen yet is unknown, not fabricated all-off."""
        coord = _make_bare_coordinator()

        assert coord.get_keypad_led_states("[02:06:03]") is None

    def test_get_keypad_led_states_returns_cached(self):
        """After a KLS, the cached LED list is returned for the normalized address."""
        coord = _make_bare_coordinator()
        led_states = [0] * 24
        led_states[3] = 2
        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord.get_keypad_led_states("[2:6:3]") == led_states

    def test_kls_update_unrelated_address_ignored(self):
        """KLS update for unregistered address does not affect registered devices."""
        coord, device = self._make_coordinator_with_device(button=6)

        led_states = [0] * 24
        led_states[14] = CCO_RELAY_CLOSED_DIGIT

        # Different address
        coord._handle_kls_update("[02:06:99]", led_states)

        assert coord._cco_states[device.address.unique_key] is None

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

        # Button 4 at index 12 = ON, Button 6 at index 14 = OFF
        led_states = [0] * 24
        led_states[12] = CCO_RELAY_CLOSED_DIGIT  # Button 4 ON
        led_states[14] = CCO_RELAY_OPEN_DIGIT  # Button 6 OFF

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord._cco_states[dev1.address.unique_key] is True
        assert coord._cco_states[dev2.address.unique_key] is False


class TestCCOUnknownState:
    """Tests that an undecodable relay digit surfaces as unknown, not OFF."""

    def _coord_with_device(self, button=6):
        coord = _make_bare_coordinator()
        device = CCODevice(
            address=CCOAddress(processor=2, link=6, address=3, button=button),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
        )
        coord.register_cco_device(device)
        return coord, device

    def test_fresh_device_state_is_unknown(self):
        """Before any KLS, get_cco_state returns None."""
        coord, device = self._coord_with_device()

        assert coord.get_cco_state(device.address) is None

    def test_undocumented_digit_stays_unknown(self):
        """An all-zero relay window must not be read as OFF.

        This is the signature of a wrong window offset; coercing it to OFF
        produced a rock-solid fake "off" that never self-corrected.
        """
        coord, device = self._coord_with_device()
        led_states = [0] * 24  # index 14 = 0 = undocumented

        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord.get_cco_state(device.address) is None
        assert coord._cco_state_sources[device.address.unique_key] == "unknown"
        assert coord._cco_relay_digits[device.address.unique_key] == 0

    def test_known_state_reverting_to_undocumented_digit_becomes_unknown(self):
        """A digit that stops being decodable clears the previously known state."""
        coord, device = self._coord_with_device()
        led_states_on = [0] * 24
        led_states_on[14] = CCO_RELAY_CLOSED_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states_on)
        assert coord.get_cco_state(device.address) is True

        led_states_bad = [0] * 24
        led_states_bad[14] = 3  # Flash2 for a keypad LED; undefined for a relay
        coord._handle_kls_update("[02:06:03]", led_states_bad)

        assert coord.get_cco_state(device.address) is None

    def test_cco_unknown_count(self):
        """cco_unknown_count reports only the endpoints still awaiting KLS."""
        coord = _make_bare_coordinator()
        dev1 = CCODevice(
            address=CCOAddress(2, 6, 3, 4), name="Dev4", entity_type=CCOEntityType.SWITCH
        )
        dev2 = CCODevice(
            address=CCOAddress(2, 6, 3, 6), name="Dev6", entity_type=CCOEntityType.SWITCH
        )
        coord.register_cco_device(dev1)
        coord.register_cco_device(dev2)
        assert coord.cco_unknown_count == 2

        led_states = [0] * 24
        led_states[12] = CCO_RELAY_CLOSED_DIGIT  # relay 4 only
        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord.cco_unknown_count == 1

    def test_get_cco_diagnostics(self):
        """Diagnostics expose the offset, index, raw digit, and state source."""
        coord, device = self._coord_with_device(button=6)
        led_states = [0] * 24
        led_states[14] = CCO_RELAY_CLOSED_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states)

        diag = coord.get_cco_diagnostics(device.address)

        assert diag["kls_window_offset"] == 9
        assert diag["kls_index"] == 14
        assert diag["kls_raw_digit"] == CCO_RELAY_CLOSED_DIGIT
        assert diag["state_source"] == "kls"

    def test_kls_last_seen_ages(self):
        """Only addresses that have answered appear, aged from the loop clock."""
        coord = _make_bare_coordinator()
        coord.hass.loop.time.return_value = 1000.0
        coord._handle_kls_update("[02:06:03]", [0] * 24)

        coord.hass.loop.time.return_value = 1012.5
        ages = coord.kls_last_seen_ages()

        assert ages == {"[02:06:03]": 12.5}


class TestCCOCommandMismatch:
    """Tests for optimistic state and command/feedback disagreement."""

    def _coord_with_device(self, button=6):
        coord = _make_bare_coordinator()
        device = CCODevice(
            address=CCOAddress(processor=2, link=6, address=3, button=button),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
        )
        coord.register_cco_device(device)
        return coord, device

    def test_optimistic_state_recorded(self):
        """Commanding a relay sets an optimistic state pending confirmation."""
        coord, device = self._coord_with_device()

        coord._record_optimistic_state(device.address.unique_key, True)

        assert coord.get_cco_state(device.address) is True
        assert coord._cco_state_sources[device.address.unique_key] == "optimistic"
        assert device.address.unique_key in coord._cco_pending_commands

    def test_kls_wins_over_contradicting_command(self, caplog):
        """Processor feedback overrides our optimistic guess and logs it."""
        coord, device = self._coord_with_device()
        coord._record_optimistic_state(device.address.unique_key, True)

        # Processor reports the relay open despite the close command.
        led_states = [0] * 24
        led_states[14] = CCO_RELAY_OPEN_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord.get_cco_state(device.address) is False
        assert coord._cco_state_sources[device.address.unique_key] == "kls"
        assert "reports" in caplog.text

    def test_matching_kls_clears_pending_without_warning(self, caplog):
        """Confirmation is not a mismatch."""
        coord, device = self._coord_with_device()
        coord._record_optimistic_state(device.address.unique_key, True)

        led_states = [0] * 24
        led_states[14] = CCO_RELAY_CLOSED_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord.get_cco_state(device.address) is True
        assert device.address.unique_key not in coord._cco_pending_commands
        assert "reports" not in caplog.text

    def test_stale_pending_command_is_not_a_mismatch(self, caplog):
        """A relay changed at a keypad long after our command is normal."""
        coord, device = self._coord_with_device()
        coord._record_optimistic_state(device.address.unique_key, True)

        # Well past CCO_COMMAND_MISMATCH_WINDOW.
        coord.hass.loop.time.return_value = 1000.0 + 60.0
        led_states = [0] * 24
        led_states[14] = CCO_RELAY_OPEN_DIGIT
        coord._handle_kls_update("[02:06:03]", led_states)

        assert coord.get_cco_state(device.address) is False
        assert "reports" not in caplog.text


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
    async def test_cco_turn_on_optimistic(self, cco_device_factory):
        """async_cco_turn_on sets optimistic state to True."""
        coord = self._make_coordinator_with_client()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)

        result = await coord.async_cco_turn_on(device)

        assert result is True
        assert coord._cco_states[device.address.unique_key] is True

    @pytest.mark.asyncio
    async def test_cco_turn_off_optimistic(self, cco_device_factory):
        """async_cco_turn_off sets optimistic state to False."""
        coord = self._make_coordinator_with_client()
        device = cco_device_factory(button=6)
        coord.register_cco_device(device)
        coord._cco_states[device.address.unique_key] = True

        result = await coord.async_cco_turn_off(device)

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
        result = await coord.async_cco_turn_on(device)

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

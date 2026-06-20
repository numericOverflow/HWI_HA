"""Tests for entity registration/unregistration lifecycle.

Verifies that:
- Creating an entity fully populates all coordinator registries
- Removing an entity leaves NO leftovers in any registry
- Each entity type (CCO, dimmer, CCI, keypad/button) is covered
"""

import pytest
from unittest.mock import MagicMock, patch

from custom_components.homeworks_hwi.models import (
    CCOAddress,
    CCODevice,
    CCOEntityType,
    normalize_address,
)
from custom_components.homeworks_hwi.coordinator import HomeworksCoordinator


def _make_bare_coordinator():
    """Create a coordinator instance bypassing __init__."""

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
# CCO Device Lifecycle — Full Registration & Clean Removal
# =============================================================================


class TestCCODeviceLifecycle:
    """Verify CCO device register/unregister touches all expected registries."""

    def _make_device(self, proc=2, link=6, addr=3, button=6, inverted=False):
        return CCODevice(
            address=CCOAddress(proc, link, addr, button),
            name=f"Test CCO {proc}:{link}:{addr},{button}",
            entity_type=CCOEntityType.SWITCH,
            inverted=inverted,
        )

    def test_register_populates_all_registries(self):
        """After register: device in _cco_devices, state in _cco_states, KLS addr polled."""
        coord = _make_bare_coordinator()
        device = self._make_device()

        coord.register_cco_device(device)

        # Device registry
        assert device.address.unique_key in coord._cco_devices
        assert coord._cco_devices[device.address.unique_key] is device

        # State cache (defaults to False/OFF)
        assert device.address.unique_key in coord._cco_states
        assert coord._cco_states[device.address.unique_key] is False

        # KLS polling address
        assert "[02:06:03]" in coord._kls_poll_addresses

    def test_unregister_removes_device_and_state(self):
        """After unregister: device and state caches are empty."""
        coord = _make_bare_coordinator()
        device = self._make_device()
        coord.register_cco_device(device)

        coord.unregister_cco_device(device.address)

        assert device.address.unique_key not in coord._cco_devices
        assert device.address.unique_key not in coord._cco_states

    def test_unregister_nonexistent_is_safe(self):
        """Unregistering a device that was never registered does not raise."""
        coord = _make_bare_coordinator()
        addr = CCOAddress(9, 9, 9, 9)

        # Should not raise
        coord.unregister_cco_device(addr)

    def test_register_multiple_same_kls_address(self):
        """Multiple CCO devices on same keypad share one KLS poll entry."""
        coord = _make_bare_coordinator()
        dev1 = self._make_device(button=1)
        dev2 = self._make_device(button=6)
        dev3 = self._make_device(button=8)

        coord.register_cco_device(dev1)
        coord.register_cco_device(dev2)
        coord.register_cco_device(dev3)

        assert len(coord._cco_devices) == 3
        assert len(coord._cco_states) == 3
        # All on same keypad [02:06:03] — only 1 KLS address
        assert len(coord._kls_poll_addresses) == 1

    def test_register_different_kls_addresses(self):
        """CCO devices on different keypads create separate KLS poll entries."""
        coord = _make_bare_coordinator()
        dev1 = self._make_device(proc=2, link=6, addr=3, button=1)
        dev2 = self._make_device(proc=2, link=6, addr=4, button=1)
        dev3 = self._make_device(proc=2, link=7, addr=1, button=1)

        coord.register_cco_device(dev1)
        coord.register_cco_device(dev2)
        coord.register_cco_device(dev3)

        assert len(coord._kls_poll_addresses) == 3
        assert "[02:06:03]" in coord._kls_poll_addresses
        assert "[02:06:04]" in coord._kls_poll_addresses
        assert "[02:07:01]" in coord._kls_poll_addresses

    def test_unregister_all_leaves_empty_registries(self):
        """After removing all devices, all CCO registries are empty."""
        coord = _make_bare_coordinator()
        devices = [
            self._make_device(button=1),
            self._make_device(button=2),
            self._make_device(button=3),
        ]
        for d in devices:
            coord.register_cco_device(d)

        for d in devices:
            coord.unregister_cco_device(d.address)

        assert len(coord._cco_devices) == 0
        assert len(coord._cco_states) == 0

    @pytest.mark.parametrize("entity_type", [
        CCOEntityType.SWITCH,
        CCOEntityType.LIGHT,
        CCOEntityType.COVER,
        CCOEntityType.LOCK,
        CCOEntityType.FAN,
        CCOEntityType.CLIMATE,
    ])
    def test_all_entity_types_register_identically(self, entity_type):
        """All 6 CCO entity types follow the same registration pattern."""
        coord = _make_bare_coordinator()
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name=f"Test {entity_type.name}",
            entity_type=entity_type,
        )

        coord.register_cco_device(device)

        assert device.address.unique_key in coord._cco_devices
        assert device.address.unique_key in coord._cco_states
        assert "[02:06:03]" in coord._kls_poll_addresses

        coord.unregister_cco_device(device.address)

        assert device.address.unique_key not in coord._cco_devices
        assert device.address.unique_key not in coord._cco_states


# =============================================================================
# Dimmer Device Lifecycle
# =============================================================================


class TestDimmerLifecycle:
    """Verify dimmer register/unregister touches all expected registries."""

    def test_register_populates_address_and_state(self):
        """After register: address in _dimmer_addresses, level=0 in _dimmer_states."""
        coord = _make_bare_coordinator()

        coord.register_dimmer("1:1:0:2:4")

        assert "[01:01:00:02:04]" in coord._dimmer_addresses
        assert "[01:01:00:02:04]" in coord._dimmer_states
        assert coord._dimmer_states["[01:01:00:02:04]"] == 0

    def test_unregister_removes_address_and_state(self):
        """After unregister: both _dimmer_addresses and _dimmer_states are clean."""
        coord = _make_bare_coordinator()
        coord.register_dimmer("1:1:0:2:4")

        coord.unregister_dimmer("1:1:0:2:4")

        assert "[01:01:00:02:04]" not in coord._dimmer_addresses
        assert "[01:01:00:02:04]" not in coord._dimmer_states

    def test_unregister_nonexistent_is_safe(self):
        """Unregistering an unknown dimmer does not raise."""
        coord = _make_bare_coordinator()
        coord.unregister_dimmer("[99:99:99:99:99]")
        # No assertion needed — just must not raise

    def test_register_multiple_dimmers(self):
        """Multiple dimmers each get their own address and state entries."""
        coord = _make_bare_coordinator()
        addrs = ["1:1:0:2:1", "1:1:0:2:2", "1:1:0:2:3"]

        for a in addrs:
            coord.register_dimmer(a)

        assert len(coord._dimmer_addresses) == 3
        assert len(coord._dimmer_states) == 3

    def test_unregister_all_dimmers_leaves_empty(self):
        """After removing all dimmers, registries are empty."""
        coord = _make_bare_coordinator()
        addrs = ["1:1:0:2:1", "1:1:0:2:2", "1:1:0:2:3"]
        for a in addrs:
            coord.register_dimmer(a)

        for a in addrs:
            coord.unregister_dimmer(a)

        assert len(coord._dimmer_addresses) == 0
        assert len(coord._dimmer_states) == 0

    def test_address_normalization_on_register(self):
        """Different address formats normalize to the same entry."""
        coord = _make_bare_coordinator()

        coord.register_dimmer("1:1:0:2:4")  # Bare
        # Re-registering with normalized form should overwrite, not duplicate
        coord.register_dimmer("[01:01:00:02:04]")

        assert len(coord._dimmer_addresses) == 1
        assert len(coord._dimmer_states) == 1

    def test_unregister_with_different_format(self):
        """Unregister works regardless of address format used."""
        coord = _make_bare_coordinator()
        coord.register_dimmer("1:1:0:2:4")

        # Unregister with full normalized format
        coord.unregister_dimmer("[01:01:00:02:04]")

        assert len(coord._dimmer_addresses) == 0
        assert len(coord._dimmer_states) == 0


# =============================================================================
# CCI Device Lifecycle
# =============================================================================


class TestCCIDeviceLifecycle:
    """Verify CCI device register/unregister touches all expected registries."""

    def test_register_populates_device_and_state(self):
        """After register: device in _cci_devices, state=False in _cci_states."""
        coord = _make_bare_coordinator()
        mock_device = MagicMock(name="FrontDoorCCI")

        coord.register_cci_device("[02:05:01]", 1, mock_device)

        key = (2, 5, 1, 1)
        assert key in coord._cci_devices
        assert coord._cci_devices[key] is mock_device
        assert key in coord._cci_states
        assert coord._cci_states[key] is False

    def test_unregister_removes_device_and_state(self):
        """After unregister: _cci_devices and _cci_states are clean."""
        coord = _make_bare_coordinator()
        coord.register_cci_device("[02:05:01]", 1, MagicMock())

        coord.unregister_cci_device("[02:05:01]", 1)

        key = (2, 5, 1, 1)
        assert key not in coord._cci_devices
        assert key not in coord._cci_states

    def test_unregister_nonexistent_is_safe(self):
        """Unregistering unknown CCI does not raise."""
        coord = _make_bare_coordinator()
        coord.unregister_cci_device("[99:99:99]", 99)

    def test_multiple_inputs_same_address(self):
        """Multiple CCI inputs on same address each get separate entries."""
        coord = _make_bare_coordinator()
        coord.register_cci_device("[02:05:01]", 1, MagicMock())
        coord.register_cci_device("[02:05:01]", 2, MagicMock())
        coord.register_cci_device("[02:05:01]", 3, MagicMock())

        assert len(coord._cci_devices) == 3
        assert (2, 5, 1, 1) in coord._cci_devices
        assert (2, 5, 1, 2) in coord._cci_devices
        assert (2, 5, 1, 3) in coord._cci_devices

    def test_unregister_one_preserves_others(self):
        """Removing one CCI input does not affect others on same address."""
        coord = _make_bare_coordinator()
        coord.register_cci_device("[02:05:01]", 1, MagicMock())
        coord.register_cci_device("[02:05:01]", 2, MagicMock())

        coord.unregister_cci_device("[02:05:01]", 1)

        assert (2, 5, 1, 1) not in coord._cci_devices
        assert (2, 5, 1, 2) in coord._cci_devices

    def test_unregister_all_leaves_empty(self):
        """After removing all CCI devices, registries are empty."""
        coord = _make_bare_coordinator()
        coord.register_cci_device("[02:05:01]", 1, MagicMock())
        coord.register_cci_device("[02:05:01]", 2, MagicMock())
        coord.register_cci_device("[02:05:02]", 1, MagicMock())

        coord.unregister_cci_device("[02:05:01]", 1)
        coord.unregister_cci_device("[02:05:01]", 2)
        coord.unregister_cci_device("[02:05:02]", 1)

        assert len(coord._cci_devices) == 0
        assert len(coord._cci_states) == 0


# =============================================================================
# Callback Lifecycle (Button + CCI)
# =============================================================================


class TestCallbackLifecycle:
    """Verify callback register/unregister leaves no orphan entries."""

    def test_button_callback_register_creates_entry(self):
        """Registering a button callback adds it to _button_callbacks."""
        coord = _make_bare_coordinator()
        cb = MagicMock()

        unregister = coord.register_button_callback("[02:08:02]", cb)

        assert "[02:08:02]" in coord._button_callbacks
        assert cb in coord._button_callbacks["[02:08:02]"]
        assert callable(unregister)

    def test_button_callback_unregister_removes_entry(self):
        """Calling unregister removes the callback AND the key if empty."""
        coord = _make_bare_coordinator()
        cb = MagicMock()
        unregister = coord.register_button_callback("[02:08:02]", cb)

        unregister()

        assert "[02:08:02]" not in coord._button_callbacks

    def test_button_multiple_callbacks_partial_unregister(self):
        """Unregistering one callback preserves others on same address."""
        coord = _make_bare_coordinator()
        cb1 = MagicMock()
        cb2 = MagicMock()
        unreg1 = coord.register_button_callback("[02:08:02]", cb1)
        coord.register_button_callback("[02:08:02]", cb2)

        unreg1()

        assert "[02:08:02]" in coord._button_callbacks
        assert cb1 not in coord._button_callbacks["[02:08:02]"]
        assert cb2 in coord._button_callbacks["[02:08:02]"]

    def test_button_all_callbacks_removed_cleans_key(self):
        """Removing all callbacks for an address removes the dict key."""
        coord = _make_bare_coordinator()
        cb1 = MagicMock()
        cb2 = MagicMock()
        unreg1 = coord.register_button_callback("[02:08:02]", cb1)
        unreg2 = coord.register_button_callback("[02:08:02]", cb2)

        unreg1()
        unreg2()

        assert "[02:08:02]" not in coord._button_callbacks

    def test_cci_callback_register_creates_entry(self):
        """Registering a CCI callback adds it to _cci_callbacks."""
        coord = _make_bare_coordinator()
        cb = MagicMock()

        unregister = coord.register_cci_callback("[02:05:01]", 1, cb)

        key = (2, 5, 1, 1)
        assert key in coord._cci_callbacks
        assert cb in coord._cci_callbacks[key]
        assert callable(unregister)

    def test_cci_callback_unregister_removes_entry(self):
        """Calling unregister removes the callback AND key if empty."""
        coord = _make_bare_coordinator()
        cb = MagicMock()
        unregister = coord.register_cci_callback("[02:05:01]", 1, cb)

        unregister()

        key = (2, 5, 1, 1)
        assert key not in coord._cci_callbacks

    def test_cci_multiple_callbacks_partial_unregister(self):
        """Unregistering one CCI callback preserves others."""
        coord = _make_bare_coordinator()
        cb1 = MagicMock()
        cb2 = MagicMock()
        unreg1 = coord.register_cci_callback("[02:05:01]", 1, cb1)
        coord.register_cci_callback("[02:05:01]", 1, cb2)

        unreg1()

        key = (2, 5, 1, 1)
        assert key in coord._cci_callbacks
        assert cb1 not in coord._cci_callbacks[key]
        assert cb2 in coord._cci_callbacks[key]


# =============================================================================
# Cross-Entity: Shared KLS Address Cleanup
# =============================================================================


class TestSharedKLSAddressCleanup:
    """Verify KLS address handling when multiple CCO devices share a keypad."""

    def test_kls_address_persists_while_devices_remain(self):
        """KLS address stays in poll set while at least one device uses it."""
        coord = _make_bare_coordinator()
        dev1 = CCODevice(
            address=CCOAddress(2, 6, 3, 1), name="Dev1", entity_type=CCOEntityType.SWITCH
        )
        dev2 = CCODevice(
            address=CCOAddress(2, 6, 3, 6), name="Dev2", entity_type=CCOEntityType.LIGHT
        )

        coord.register_cco_device(dev1)
        coord.register_cco_device(dev2)

        # Remove one — KLS address should remain (dev2 still uses it)
        coord.unregister_cco_device(dev1.address)

        assert "[02:06:03]" in coord._kls_poll_addresses
        assert len(coord._cco_devices) == 1

    def test_mixed_entity_types_share_kls(self):
        """Switch + Cover + Fan on same keypad all share one KLS address."""
        coord = _make_bare_coordinator()
        devices = [
            CCODevice(address=CCOAddress(2, 6, 3, 1), name="Switch", entity_type=CCOEntityType.SWITCH),
            CCODevice(address=CCOAddress(2, 6, 3, 2), name="Cover", entity_type=CCOEntityType.COVER),
            CCODevice(address=CCOAddress(2, 6, 3, 3), name="Fan", entity_type=CCOEntityType.FAN),
        ]

        for d in devices:
            coord.register_cco_device(d)

        assert len(coord._kls_poll_addresses) == 1
        assert len(coord._cco_devices) == 3

        # Remove all
        for d in devices:
            coord.unregister_cco_device(d.address)

        assert len(coord._cco_devices) == 0
        assert len(coord._cco_states) == 0

    def test_independent_kls_addresses_dont_interfere(self):
        """Removing a device on one keypad doesn't affect another keypad's polling."""
        coord = _make_bare_coordinator()
        dev_a = CCODevice(
            address=CCOAddress(2, 6, 3, 1), name="Keypad A", entity_type=CCOEntityType.SWITCH
        )
        dev_b = CCODevice(
            address=CCOAddress(2, 6, 4, 1), name="Keypad B", entity_type=CCOEntityType.SWITCH
        )

        coord.register_cco_device(dev_a)
        coord.register_cco_device(dev_b)

        assert "[02:06:03]" in coord._kls_poll_addresses
        assert "[02:06:04]" in coord._kls_poll_addresses

        coord.unregister_cco_device(dev_a.address)

        # Keypad B still polled
        assert "[02:06:04]" in coord._kls_poll_addresses
        assert len(coord._cco_devices) == 1

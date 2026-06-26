"""Tests for Homeworks data models.

These tests run WITHOUT Home Assistant dependencies.
"""

import pytest
from datetime import datetime, timedelta

# Direct import from models.py (no HA deps)
from models import (
    CCOAddress,
    CCODevice,
    CCOEntityType,
    KLSState,
    ControllerHealth,
    CCO_BUTTON_WINDOW_OFFSET,
    normalize_address,
    parse_kls_address,
)


class TestNormalizeAddress:
    """Tests for address normalization."""

    def test_simple_address(self):
        assert normalize_address("1:2:3") == "[01:02:03]"

    def test_address_with_brackets(self):
        assert normalize_address("[1:2:3]") == "[01:02:03]"

    def test_already_normalized(self):
        assert normalize_address("[01:02:03]") == "[01:02:03]"

    def test_4_part_address(self):
        assert normalize_address("1:2:3:4") == "[01:02:03:04]"

    def test_5_part_address(self):
        assert normalize_address("1:2:3:4:5") == "[01:02:03:04:05]"


class TestCCOAddress:
    """Tests for CCOAddress parsing."""

    def test_from_string_comma_format(self):
        addr = CCOAddress.from_string("2:6:3,6")
        assert addr.processor == 2
        assert addr.link == 6
        assert addr.address == 3
        assert addr.button == 6

    def test_from_string_bracketed(self):
        addr = CCOAddress.from_string("[02:06:03],6")
        assert addr.processor == 2
        assert addr.link == 6
        assert addr.address == 3
        assert addr.button == 6

    def test_from_string_colon_format(self):
        addr = CCOAddress.from_string("2:6:3:6")
        assert addr.processor == 2
        assert addr.link == 6
        assert addr.address == 3
        assert addr.button == 6

    def test_to_kls_address(self):
        addr = CCOAddress(processor=2, link=6, address=3, button=6)
        assert addr.to_kls_address() == "[02:06:03]"

    def test_to_command_address(self):
        addr = CCOAddress(processor=2, link=6, address=3, button=6)
        assert addr.to_command_address() == "[2:6:3]"

    def test_unique_key(self):
        addr = CCOAddress(processor=2, link=6, address=3, button=6)
        assert addr.unique_key == (2, 6, 3, 6)

    def test_str(self):
        addr = CCOAddress(processor=2, link=6, address=3, button=6)
        assert str(addr) == "2:6:3,6"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            CCOAddress.from_string("invalid")
        with pytest.raises(ValueError):
            CCOAddress.from_string("1:2")


class TestCCODevice:
    """Tests for CCODevice."""

    def test_interpret_state_on(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
        )
        assert device.interpret_state(2) is True

    def test_interpret_state_off(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
        )
        assert device.interpret_state(1) is False

    def test_interpret_state_zero(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
        )
        assert device.interpret_state(0) is False

    def test_interpret_state_inverted(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
            inverted=True,
        )
        # Inverted: digit 2 (normally ON) = OFF, digit 1 (normally OFF) = ON
        assert device.interpret_state(2) is False
        assert device.interpret_state(1) is True

    def test_unique_id(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 1),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
        )
        assert device.unique_id == "cco_2_6_3_1"


class TestKLSState:
    """Tests for KLSState parsing with button window."""

    def test_window_offset_constant(self):
        assert CCO_BUTTON_WINDOW_OFFSET == 9

    def test_get_cco_state_sample_1(self):
        """Button 6 should be ON in sample 1 (digit 2 = relay closed)."""
        led_states = [int(c) for c in "000000000222112110000000"]
        kls = KLSState(address="[02:06:03]", led_states=led_states)
        assert kls.get_cco_state(6) is True

    def test_get_cco_state_sample_2(self):
        """Button 6 should be OFF in sample 2 (digit 1 = relay open)."""
        led_states = [int(c) for c in "000000000222111110000000"]
        kls = KLSState(address="[02:06:03]", led_states=led_states)
        assert kls.get_cco_state(6) is False

    def test_all_buttons_sample_1(self):
        """Test all 8 buttons with sample 1."""
        led_states = [int(c) for c in "000000000222112110000000"]
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        expected = {1: True, 2: True, 3: True, 4: False,
                    5: False, 6: True, 7: False, 8: False}

        for button, expected_state in expected.items():
            assert kls.get_cco_state(button) == expected_state

    def test_get_button_state_raw(self):
        """Test raw LED state access (1-indexed position)."""
        led_states = [1, 2, 3] + [0] * 21
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        assert kls.get_button_state(1) == 1
        assert kls.get_button_state(2) == 2
        assert kls.get_button_state(3) == 3

    def test_button_out_of_range(self):
        led_states = [1] * 24
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        assert kls.get_cco_state(0) is False
        assert kls.get_cco_state(9) is False

    def test_timestamp(self):
        kls = KLSState(address="[02:06:03]", led_states=[0] * 24)
        assert isinstance(kls.timestamp, datetime)


class TestParseKLSAddress:
    """Tests for KLS address parsing."""

    def test_parse_simple(self):
        proc, link, addr = parse_kls_address("[02:06:03]")
        assert (proc, link, addr) == (2, 6, 3)

    def test_parse_no_brackets(self):
        proc, link, addr = parse_kls_address("02:06:03")
        assert (proc, link, addr) == (2, 6, 3)

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            parse_kls_address("02:06")


class TestControllerHealth:
    """Tests for ControllerHealth tracking."""

    def test_initial_state(self):
        health = ControllerHealth()
        assert health.connected is False
        assert health.reconnect_count == 0
        assert health.poll_failure_count == 0

    def test_record_message(self):
        health = ControllerHealth()
        health.record_message()
        assert health.last_message_time is not None

    def test_record_kls(self):
        health = ControllerHealth()
        health.record_kls()
        assert health.last_kls_time is not None
        assert health.last_message_time is not None

    def test_record_reconnect(self):
        health = ControllerHealth()
        health.record_reconnect()
        health.record_reconnect()
        assert health.reconnect_count == 2

    def test_record_errors(self):
        health = ControllerHealth()
        health.record_poll_failure("timeout")
        assert health.poll_failure_count == 1
        assert health.last_error == "timeout"

        health.record_parse_error("invalid")
        assert health.parse_error_count == 1
        assert health.last_error == "invalid"

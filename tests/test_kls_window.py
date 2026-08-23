"""Comprehensive tests for KLS button window extraction.

These tests verify the CORRECT interpretation of the 8-digit button window
within the 24-digit KLS string.

The button window is at 0-indexed positions 9-16 (1-indexed positions 10-17).
For button N (1-8), read from index = 9 + (N-1).

Digit semantics for the CCO relay window (L232/cco_kls_state.htm, and
verified via telnet to a Lutron processor). These apply to CCO modules ONLY
— keypad LED digits use the different kls_mon.htm meanings:
    2 = ON (relay closed)
    1 = OFF (relay open) — the RESTING value; an idle relay reports 1, not 0
    0 = UNDOCUMENTED & UNDISCOVERED -> unknown (None)
    3 = not defined for the relay window -> unknown (None)

A CCO relay latches, so an undecodable digit must surface as None
("unknown"), never as a fabricated OFF.
"""

import pytest
from datetime import datetime, timedelta

from custom_components.homeworks_hwi.models import (
    KLSState,
    CCOAddress,
    CCODevice,
    CCOEntityType,
    CCO_BUTTON_WINDOW_OFFSET,
)
from custom_components.homeworks_hwi.hwi_protocol import KLSMessage, MessageParser


class TestButtonWindowExtraction:
    """Tests for extracting the 8-digit button window from KLS."""

    def test_window_offset_is_9(self):
        """Verify the button window starts at index 9."""
        assert CCO_BUTTON_WINDOW_OFFSET == 9

    def test_window_indices(self):
        """Verify the button window is at indices 9-16."""
        kls_string = "000000000222112110000000"
        window = kls_string[9:17]
        assert window == "22211211"
        assert len(window) == 8

    def test_button_6_index_calculation(self):
        """Verify button 6 is at index 14."""
        index = CCO_BUTTON_WINDOW_OFFSET + (6 - 1)
        assert index == 14


class TestSampleKLSLines:
    """Test with the exact sample KLS lines from the protocol."""

    def test_sample_1_button_6_off(self):
        """
        KLS, [02:06:03], 000000000222112110000000
        Button 6 = index 14 = digit '2' = ON (relay closed)
        """
        kls_string = "000000000222112110000000"
        led_states = [int(c) for c in kls_string]
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        # Verify raw digit
        assert led_states[14] == 2

        # Verify interpreted state
        assert kls.get_cco_state(6) is True

    def test_sample_2_button_6_on(self):
        """
        KLS, [02:06:03], 000000000222111110000000
        Button 6 = index 14 = digit '1' = OFF (relay open)
        """
        kls_string = "000000000222111110000000"
        led_states = [int(c) for c in kls_string]
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        # Verify raw digit
        assert led_states[14] == 1

        # Verify interpreted state
        assert kls.get_cco_state(6) is False

    def test_sample_1_all_buttons(self):
        """
        Window: 22211211
        Button states: ON, ON, ON, OFF, OFF, ON, OFF, OFF
        """
        kls_string = "000000000222112110000000"
        led_states = [int(c) for c in kls_string]
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        expected = {
            1: True,   # index 9, digit 2
            2: True,   # index 10, digit 2
            3: True,   # index 11, digit 2
            4: False,  # index 12, digit 1
            5: False,  # index 13, digit 1
            6: True,   # index 14, digit 2
            7: False,  # index 15, digit 1
            8: False,  # index 16, digit 1
        }

        for button, expected_state in expected.items():
            actual = kls.get_cco_state(button)
            assert actual == expected_state, \
                f"Button {button}: expected {expected_state}, got {actual}"

    def test_sample_2_all_buttons(self):
        """
        Window: 22211111
        Button states: ON, ON, ON, OFF, OFF, OFF, OFF, OFF
        """
        kls_string = "000000000222111110000000"
        led_states = [int(c) for c in kls_string]
        kls = KLSState(address="[02:06:03]", led_states=led_states)

        expected = {
            1: True, 2: True, 3: True, 4: False,
            5: False, 6: False, 7: False, 8: False,
        }

        for button, expected_state in expected.items():
            assert kls.get_cco_state(button) == expected_state


class TestDocumentedWorkedExamples:
    """The two worked examples from L232/cco_kls_state.htm, verbatim.

    Both use module [01:05:03] and show the relay window resting at all-1s,
    with exactly one digit moving to 2 when that relay closes.
    """

    def _states(self, kls_string):
        parser = MessageParser()
        messages = parser.feed(f"KLS, [01:05:03], {kls_string}\r\n".encode())
        msg = messages[0]
        return {relay: msg.get_cco_relay_state(relay) for relay in range(1, 9)}

    def test_example_1_relay_1_sequence(self):
        """Relay 1 is digit position 10 (index 9)."""
        # Start: relay 1 off
        states = self._states("000000000111111110000000")
        assert all(state is False for state in states.values())

        # Relay 1 turned ON by keypad command, broadcast by HWI
        states = self._states("000000000211111110000000")
        assert states[1] is True
        assert all(states[relay] is False for relay in range(2, 9))

        # Relay 1 turned OFF again
        states = self._states("000000000111111110000000")
        assert states[1] is False

    def test_example_2_relay_2_sequence(self):
        """Relay 2 is digit position 11 (index 10); relay 1 stays open at 1."""
        states = self._states("000000000111111110000000")
        assert states[2] is False

        # Relay 2 ON — only that digit moves
        states = self._states("000000000121111110000000")
        assert states[2] is True
        assert states[1] is False
        assert all(states[relay] is False for relay in range(3, 9))

        # Relay 2 OFF
        states = self._states("000000000111111110000000")
        assert states[2] is False


class TestMessageParserKLS:
    """Test KLS parsing through MessageParser."""

    def test_parse_sample_1(self):
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222112110000000\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, KLSMessage)
        assert msg.get_cco_relay_state(6) is True

    def test_parse_sample_2(self):
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222111110000000\r\n"
        messages = parser.feed(data)

        msg = messages[0]
        assert msg.get_cco_relay_state(6) is False


class TestCCODeviceInterpretation:
    """Test CCODevice state interpretation with button window."""

    def test_normal_device_sample_1(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
            inverted=False,
        )

        # Sample 1: button 6 digit = 2 = ON (relay closed)
        assert device.interpret_state(2) is True

    def test_normal_device_sample_2(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=CCOEntityType.SWITCH,
            inverted=False,
        )

        # Sample 2: button 6 digit = 1 = OFF (relay open)
        assert device.interpret_state(1) is False

    def test_inverted_device_sample_1(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Inverted",
            entity_type=CCOEntityType.SWITCH,
            inverted=True,
        )

        # Sample 1: button 6 digit = 2, normal=ON, inverted = OFF
        assert device.interpret_state(2) is False

    def test_inverted_device_sample_2(self):
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Inverted",
            entity_type=CCOEntityType.SWITCH,
            inverted=True,
        )

        # Sample 2: button 6 digit = 1, normal=OFF, inverted = ON
        assert device.interpret_state(1) is True


class TestPartialFrames:
    """Test partial/combined RS232 frame handling."""

    def test_fragmented_kls(self):
        parser = MessageParser()

        # Send in fragments
        assert len(parser.feed(b"KLS, [02:06")) == 0
        assert len(parser.feed(b":03], 000000")) == 0
        messages = parser.feed(b"000222112110000000\r\n")

        assert len(messages) == 1
        assert messages[0].get_cco_relay_state(6) is True

    def test_combined_messages(self):
        parser = MessageParser()
        data = (
            b"KLS, [02:06:03], 000000000222112110000000\r\n"
            b"KLS, [02:06:03], 000000000222111110000000\r\n"
        )
        messages = parser.feed(data)

        assert len(messages) == 2
        assert messages[0].get_cco_relay_state(6) is True
        assert messages[1].get_cco_relay_state(6) is False


class TestEdgeCases:
    """Edge case tests."""

    def test_button_0_returns_none(self):
        """Relay number below range is not a relay — unknown, not OFF."""
        kls = KLSState(address="[02:06:03]", led_states=[1] * 24)
        assert kls.get_cco_state(0) is None

    def test_button_9_returns_none(self):
        """Relay number above range is not a relay — unknown, not OFF."""
        kls = KLSState(address="[02:06:03]", led_states=[1] * 24)
        assert kls.get_cco_state(9) is None

    def test_all_zeros_means_unknown(self):
        """Digit 0 is undocumented for the relay window, so it decodes to None.

        An all-zero relay window is the signature of a wrong window offset;
        reporting OFF here would hide that misconfiguration forever.
        """
        kls = KLSState(address="[02:06:03]", led_states=[0] * 24)
        for button in range(1, 9):
            assert kls.get_cco_state(button) is None

    def test_window_all_ones_means_off(self):
        """Digit 1 is the resting value: relay open = OFF."""
        led_states = [0] * 9 + [1] * 8 + [0] * 7
        kls = KLSState(address="[02:06:03]", led_states=led_states)
        for button in range(1, 9):
            assert kls.get_cco_state(button) is False

    def test_digit_3_means_unknown(self):
        """Digit 3 is Flash2 for keypad LEDs but undefined for relays."""
        led_states = [0] * 9 + [3] * 8 + [0] * 7
        kls = KLSState(address="[02:06:03]", led_states=led_states)
        for button in range(1, 9):
            assert kls.get_cco_state(button) is None

    def test_index_past_end_of_string_returns_none(self):
        """A short KLS payload must not decode as OFF."""
        kls = KLSState(address="[02:06:03]", led_states=[1] * 10)
        assert kls.get_cco_relay_digit(1) == 1
        assert kls.get_cco_state(1) is False
        assert kls.get_cco_relay_digit(8) is None
        assert kls.get_cco_state(8) is None

    def test_inverted_device_leaves_unknown_unknown(self):
        """Inversion must not turn unknown into a confident state."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Inverted",
            entity_type=CCOEntityType.SWITCH,
            inverted=True,
        )
        assert device.interpret_state(0) is None
        assert device.interpret_state(3) is None

    def test_stale_state_detection(self):
        kls = KLSState(
            address="[02:06:03]",
            led_states=[0] * 24,
            timestamp=datetime.now() - timedelta(minutes=5),
        )
        age = datetime.now() - kls.timestamp
        assert age > timedelta(minutes=1)

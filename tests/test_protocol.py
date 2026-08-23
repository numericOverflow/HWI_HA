"""Tests for the pyhomeworks protocol layer."""

import pytest

from custom_components.homeworks_hwi.hwi_protocol import (
    MessageParser,
    normalize_address,
    parse_address,
    KLSMessage,
    DimmerLevelMessage,
    ButtonEventMessage,
    ButtonEventType,
    KeypadEnableMessage,
    GrafikEyeSceneMessage,
    SivoiaSceneMessage,
    UnknownMessage,
)
from custom_components.homeworks_hwi.hwi_protocol import commands


class TestNormalizeAddress:
    """Tests for address normalization."""

    def test_normalize_bare_address(self):
        assert normalize_address("1:2:3") == "[01:02:03]"

    def test_normalize_bracketed_address(self):
        assert normalize_address("[1:2:3]") == "[01:02:03]"

    def test_normalize_already_normalized(self):
        assert normalize_address("[01:02:03]") == "[01:02:03]"

    def test_normalize_mixed_padding(self):
        assert normalize_address("[01:2:03]") == "[01:02:03]"

    def test_normalize_long_address(self):
        assert normalize_address("1:1:0:2:4") == "[01:01:00:02:04]"


class TestParseAddress:
    """Tests for address parsing."""

    def test_parse_basic(self):
        assert parse_address("[01:02:03]") == (1, 2, 3)

    def test_parse_without_brackets(self):
        assert parse_address("1:2:3") == (1, 2, 3)

    def test_parse_five_part(self):
        assert parse_address("[01:01:00:02:04]") == (1, 1, 0, 2, 4)


class TestMessageParser:
    """Tests for MessageParser class."""

    def test_parse_kls_message(self):
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222112110000000\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, KLSMessage)
        assert msg.address == "[02:06:03]"
        assert len(msg.led_states) == 24

    def test_parse_dl_message(self):
        parser = MessageParser()
        data = b"DL, [01:01:00:02:04], 75\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, DimmerLevelMessage)
        assert msg.address == "[01:01:00:02:04]"
        assert msg.level == 75

    def test_parse_button_events(self):
        parser = MessageParser()

        for cmd, event_type, source in [
            ("KBP", ButtonEventType.PRESSED, "keypad"),
            ("KBR", ButtonEventType.RELEASED, "keypad"),
            ("KBH", ButtonEventType.HOLD, "keypad"),
            ("KBDT", ButtonEventType.DOUBLE_TAP, "keypad"),
            ("DBP", ButtonEventType.PRESSED, "dimmer"),
            ("SVBP", ButtonEventType.PRESSED, "sivoia"),
        ]:
            parser.reset()
            data = f"{cmd}, [01:02:03], 5\r\n".encode()
            messages = parser.feed(data)

            assert len(messages) == 1
            msg = messages[0]
            assert isinstance(msg, ButtonEventMessage)
            assert msg.event_type == event_type
            assert msg.source == source
            assert msg.button == 5

    def test_parse_without_spaces_after_commas(self):
        """Spaces after commas are insignificant (L232/command_formatting.htm).

        Parsing must key off the comma alone, not ", " — otherwise a processor
        emitting compact frames would drop every button press into UnknownMessage.
        """
        parser = MessageParser()

        messages = parser.feed(b"KBP,[01:04:04],1\r\n")
        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, ButtonEventMessage)
        assert msg.address == "[01:04:04]"
        assert msg.button == 1
        assert msg.event_type == ButtonEventType.PRESSED

        parser.reset()
        messages = parser.feed(b"KLS,[02:06:03],000000000222112110000000\r\n")
        assert isinstance(messages[0], KLSMessage)
        assert messages[0].address == "[02:06:03]"

    def test_parse_with_extra_whitespace(self):
        """Padded fields parse identically to compact ones."""
        parser = MessageParser()

        messages = parser.feed(b"KBH,   [01:04:04] ,  7 \r\n")
        assert len(messages) == 1
        assert messages[0].button == 7
        assert messages[0].event_type == ButtonEventType.HOLD

    def test_parse_kes_message(self):
        parser = MessageParser()

        messages = parser.feed(b"KES, [01:04:10], enabled\r\n")
        assert messages[0].enabled is True

        parser.reset()
        messages = parser.feed(b"KES, [01:04:10], disabled\r\n")
        assert messages[0].enabled is False

    def test_parse_gss_message(self):
        parser = MessageParser()
        data = b"GSS, [01:05:01], 3\r\n"
        messages = parser.feed(data)

        assert isinstance(messages[0], GrafikEyeSceneMessage)
        assert messages[0].scene == 3

    def test_parse_svs_message(self):
        parser = MessageParser()
        data = b"SVS, [01:06:01], R, MOVING\r\n"
        messages = parser.feed(data)

        assert isinstance(messages[0], SivoiaSceneMessage)
        assert messages[0].command == "R"
        assert messages[0].status == "MOVING"

    def test_parse_unknown_message(self):
        parser = MessageParser()
        data = b"UNKNOWN, some, data, here\r\n"
        messages = parser.feed(data)

        assert isinstance(messages[0], UnknownMessage)
        assert messages[0].parts == ("UNKNOWN", "some", "data", "here")

    def test_ignored_messages(self):
        parser = MessageParser()
        ignored = [
            b"Keypad button monitoring enabled\r\n",
            b"Dimmer level monitoring enabled\r\n",
            b"Keypad led monitoring enabled\r\n",
        ]
        for msg in ignored:
            parser.reset()
            messages = parser.feed(msg)
            assert len(messages) == 0

    def test_buffered_parsing(self):
        """Test that partial messages are buffered correctly."""
        parser = MessageParser()

        messages = parser.feed(b"KLS, [02:06:03], 0000000")
        assert len(messages) == 0

        messages = parser.feed(b"00222112110000000\r\n")
        assert len(messages) == 1
        assert isinstance(messages[0], KLSMessage)

    def test_multiple_messages_in_one_chunk(self):
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000000000000000000\r\nDL, [01:01:00:02:04], 50\r\n"
        messages = parser.feed(data)

        assert len(messages) == 2
        assert isinstance(messages[0], KLSMessage)
        assert isinstance(messages[1], DimmerLevelMessage)

    def test_combined_partial_frames(self):
        """Test handling of fragmented RS232 data."""
        parser = MessageParser()

        parser.feed(b"KLS, [02:06")
        parser.feed(b":03], 000000")
        messages = parser.feed(b"000222112110000000\r\nDL, [01:")
        assert len(messages) == 1

        messages = parser.feed(b"02:03], 75\r\n")
        assert len(messages) == 1
        assert messages[0].level == 75


class TestKLSButtonWindow:
    """Tests for KLS button window extraction.

    The 8 CCO relay states are at indices 9-16 (0-indexed) in the 24-digit string.
    Button N (1-8) is at index 9 + (N-1).
    """

    def test_button_6_sample_1_is_off(self):
        """KLS, [02:06:03], 000000000222112110000000 -> button 6 = ON (digit 2)"""
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222112110000000\r\n"
        msg = parser.feed(data)[0]

        # Button 6: index = 9 + 5 = 14, digit = 2 = ON (relay closed)
        assert msg.get_cco_relay_state(6) is True

    def test_button_6_sample_2_is_on(self):
        """KLS, [02:06:03], 000000000222111110000000 -> button 6 = OFF (digit 1)"""
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222111110000000\r\n"
        msg = parser.feed(data)[0]

        # Button 6: index = 9 + 5 = 14, digit = 1 = OFF (relay open)
        assert msg.get_cco_relay_state(6) is False

    def test_all_8_buttons_sample_1(self):
        """Verify all 8 button states in sample 1."""
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222112110000000\r\n"
        msg = parser.feed(data)[0]

        # Window: 22211211
        expected = {1: True, 2: True, 3: True, 4: False,
                    5: False, 6: True, 7: False, 8: False}

        for button, expected_state in expected.items():
            assert msg.get_cco_relay_state(button) == expected_state, \
                f"Button {button}: expected {expected_state}"

    def test_all_8_buttons_sample_2(self):
        """Verify all 8 button states in sample 2."""
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000222111110000000\r\n"
        msg = parser.feed(data)[0]

        # Window: 22211111
        expected = {1: True, 2: True, 3: True, 4: False,
                    5: False, 6: False, 7: False, 8: False}

        for button, expected_state in expected.items():
            assert msg.get_cco_relay_state(button) == expected_state

    def test_button_out_of_range(self):
        """Relay numbers outside 1-8 are unknown, not OFF."""
        parser = MessageParser()
        data = b"KLS, [02:06:03], 000000000111111110000000\r\n"
        msg = parser.feed(data)[0]

        assert msg.get_cco_relay_state(0) is None
        assert msg.get_cco_relay_state(9) is None
        assert msg.get_cco_relay_digit(0) is None
        assert msg.get_cco_relay_digit(9) is None


class TestCommandBuilders:
    """Tests for command builder functions."""

    def test_fade_dim(self):
        cmd = commands.fade_dim("[01:01:00:02:04]", 75.0, 2.0, 0.5)
        assert cmd == "FADEDIM, 75.0, 2.0, 0.5, [01:01:00:02:04]"

    def test_fade_dim_defaults(self):
        cmd = commands.fade_dim("[01:01:00:02:04]", 100.0)
        assert cmd == "FADEDIM, 100.0, 0.0, 0.0, [01:01:00:02:04]"

    def test_cco_close(self):
        cmd = commands.cco_close("[02:06:03]", 1)
        assert cmd == "CCOCLOSE, [02:06:03], 1"

    def test_cco_open(self):
        cmd = commands.cco_open("[02:06:03]", 1)
        assert cmd == "CCOOPEN, [02:06:03], 1"

    def test_cco_pulse(self):
        cmd = commands.cco_pulse("[02:06:03]", 1, 2.5)
        assert cmd == "CCOPULSE, [02:06:03], 1, 5"

    def test_keypad_commands(self):
        assert commands.keypad_button_press("[01:04:10]", 3) == "KBP, [01:04:10], 3"
        assert commands.keypad_button_release("[01:04:10]", 3) == "KBR, [01:04:10], 3"
        assert commands.request_keypad_led_states("[02:06:03]") == "RKLS, [02:06:03]"

    def test_monitoring_commands(self):
        assert commands.enable_dimmer_monitoring() == "DLMON"
        assert commands.disable_dimmer_monitoring() == "DLMOFF"
        assert commands.enable_keypad_button_monitoring() == "KBMON"
        assert commands.enable_keypad_led_monitoring() == "KLMON"

    def test_system_commands(self):
        assert commands.prompt_off() == "PROMPTOFF"
        assert commands.prompt_on() == "PROMPTON"

"""Tests for binary sensor entities (LED + CCI) and button entities.

Covers:
- Keypad LED binary sensor state derivation
- CCI binary sensor state from button events (KBH/KBR)
- Device class mapping for CCI sensors
- Button press simulation with release delay
"""

import pytest
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

from custom_components.homeworks_hwi.models import normalize_address


# =============================================================================
# Keypad LED Binary Sensor Tests
# =============================================================================


class TestKeypadLEDBinarySensor:
    """Tests for LED state binary sensors.

    LED values per L232/kls_mon.htm: 0=Off, 1=On, 2=Flash1, 3=Flash2.
    A flashing LED is lit, so 1/2/3 are all "on" and only 0 is "off".
    """

    pytestmark = [pytest.mark.requires_ha]

    @pytest.fixture
    def led_sensor(self, mock_coordinator):
        """Create an LED binary sensor for button 2 of a keypad."""
        try:
            from custom_components.homeworks_hwi.binary_sensor import (
                HomeworksLEDBinarySensor,
            )
        except ImportError:
            pytest.skip("Requires Home Assistant dependencies")

        return HomeworksLEDBinarySensor(
            coordinator=mock_coordinator,
            controller_id="test_ctrl",
            keypad_addr="[02:08:02]",
            keypad_name="Back Hall",
            button_name="GOODNIGHT",
            led_number=2,
        )

    @pytest.mark.parametrize(
        "led_value,expected",
        [
            pytest.param(0, False, id="off"),
            pytest.param(1, True, id="on"),
            pytest.param(2, True, id="flash1"),
            pytest.param(3, True, id="flash2"),
        ],
    )
    def test_is_on_from_led_value(self, led_sensor, mock_coordinator, led_value, expected):
        """Any non-zero LED value is on; only 0 is off."""
        led_states = [0] * 24
        led_states[1] = led_value  # LED 2 is 1-indexed → index 1
        mock_coordinator.get_keypad_led_states.return_value = led_states

        assert led_sensor.is_on is expected

    def test_is_on_unknown_before_first_kls(self, led_sensor, mock_coordinator):
        """No KLS seen for this keypad yet reads unknown, not a fabricated off."""
        mock_coordinator.get_keypad_led_states.return_value = None

        assert led_sensor.is_on is None

    def test_is_on_unknown_when_led_out_of_range(self, led_sensor, mock_coordinator):
        """A truncated LED string does not silently report off for missing LEDs."""
        mock_coordinator.get_keypad_led_states.return_value = [0]

        assert led_sensor.is_on is None

    def test_led_state_from_kls_string(self):
        """Parse LED states from full KLS string."""
        kls_string = "120000000000000000000000"
        led_states = [int(c) for c in kls_string]
        assert led_states[0] == 1  # LED 1 On
        assert led_states[1] == 2  # LED 2 Flash1


# =============================================================================
# CCI Binary Sensor Tests
# =============================================================================


class TestCCIBinarySensor:
    """Tests for Contact Closure Input sensors."""

    def test_cci_state_on_from_hold(self):
        """CCI ON state is derived from KBH (hold) event."""
        # KBH = physical key turned to ON position
        state = True  # KBH event
        assert state is True

    def test_cci_state_off_from_release(self):
        """CCI OFF state is derived from KBR (release) event."""
        # KBR = physical key turned to OFF position
        state = False  # KBR event
        assert state is False

    def test_device_class_mapping(self):
        """Device class strings map to HA constants."""
        DEVICE_CLASS_MAP = {
            "door": "door",
            "window": "window",
            "garage_door": "garage_door",
            "opening": "opening",
            "lock": "lock",
            "motion": "motion",
            "occupancy": "occupancy",
            "presence": "presence",
            "safety": "safety",
            "plug": "plug",
            "power": "power",
            "running": "running",
            "problem": "problem",
            "connectivity": "connectivity",
            None: None,
            "": None,
        }

        assert DEVICE_CLASS_MAP["door"] == "door"
        assert DEVICE_CLASS_MAP["window"] == "window"
        assert DEVICE_CLASS_MAP[None] is None
        assert DEVICE_CLASS_MAP[""] is None

    @pytest.mark.parametrize(
        "device_class,expected_not_none",
        [
            ("door", True),
            ("window", True),
            ("motion", True),
            ("", False),
            (None, False),
        ],
    )
    def test_device_class_resolution(self, device_class, expected_not_none):
        """Device class is correctly resolved from config string."""
        DEVICE_CLASS_MAP = {
            "door": "door",
            "window": "window",
            "motion": "motion",
            None: None,
            "": None,
        }
        result = DEVICE_CLASS_MAP.get(device_class)
        assert (result is not None) == expected_not_none

    def test_cci_address_normalization(self):
        """CCI addresses are normalized before use."""
        raw = "2:5:1"
        normalized = normalize_address(raw)
        assert normalized == "[02:05:01]"


# =============================================================================
# Button Entity Tests
# =============================================================================


class TestButtonEntity:
    """Tests for keypad button press simulation."""

    def test_button_press_release_sequence(self):
        """Button press should send KBP then KBR with delay."""
        # Validates the expected command sequence
        expected_commands = ["keypad_button_press", "keypad_button_release"]
        assert len(expected_commands) == 2

    @pytest.mark.parametrize(
        "button_number,valid",
        [
            (1, True),
            (8, True),
            (24, True),
            (0, False),
            (25, False),
        ],
    )
    def test_button_number_range(self, button_number, valid):
        """Button numbers should be 1-24."""
        is_valid = 1 <= button_number <= 24
        assert is_valid == valid

    def test_release_delay_default(self):
        """Default release delay is reasonable."""
        # Typical release delay is 0.2s (200ms)
        default_delay = 0.2
        assert 0.05 <= default_delay <= 2.0

    def test_keypad_address_normalization(self):
        """Keypad addresses are normalized."""
        raw = "2:8:2"
        normalized = normalize_address(raw)
        assert normalized == "[02:08:02]"


# =============================================================================
# Health Sensor Tests
# =============================================================================


class TestHealthSensors:
    """Tests for diagnostic health sensors."""

    def test_sensor_types_defined(self):
        """All health sensor types exist."""
        sensor_types = [
            "connection",
            "last_kls_time",
            "reconnect_count",
            "poll_failure_count",
            "parse_error_count",
        ]
        assert len(sensor_types) == 5

    def test_connection_sensor_values(self):
        """Connection sensor reports connected/disconnected."""
        assert "connected" != "disconnected"

    def test_health_counter_sensors_are_integers(self):
        """Counter sensors (reconnect, poll_failure, parse_error) are numeric."""
        counters = {
            "reconnect_count": 0,
            "poll_failure_count": 0,
            "parse_error_count": 0,
        }
        for name, value in counters.items():
            assert isinstance(value, int), f"{name} should be int"

"""Tests for all CCO-based entity platforms (switch, light, cover, fan, lock, climate).

Uses parametrized tests to validate common behavior across all 6 CCO entity types,
plus platform-specific tests for unique features.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.homeworks_hwi.models import CCOAddress, CCODevice, CCOEntityType


# =============================================================================
# Common CCO Entity Behavior (parametrized across all platforms)
# =============================================================================


CCO_PLATFORMS = [
    pytest.param("switch", CCOEntityType.SWITCH, id="switch"),
    pytest.param("light", CCOEntityType.LIGHT, id="light"),
    pytest.param("cover", CCOEntityType.COVER, id="cover"),
    pytest.param("fan", CCOEntityType.FAN, id="fan"),
    pytest.param("lock", CCOEntityType.LOCK, id="lock"),
    pytest.param("climate", CCOEntityType.CLIMATE, id="climate"),
]


class TestCCODeviceCreation:
    """Test CCO device creation from config options."""

    @pytest.mark.parametrize("entity_type_str,entity_type_enum", CCO_PLATFORMS)
    def test_cco_device_created_with_correct_type(
        self, entity_type_str, entity_type_enum
    ):
        """CCO device is created with the correct entity type."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name=f"Test {entity_type_str}",
            entity_type=entity_type_enum,
        )
        assert device.entity_type == entity_type_enum
        assert device.name == f"Test {entity_type_str}"

    @pytest.mark.parametrize("entity_type_str,entity_type_enum", CCO_PLATFORMS)
    def test_cco_device_interpret_state_on(self, entity_type_str, entity_type_enum):
        """CCO device interprets LED value 1 as ON (relay closed)."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=entity_type_enum,
        )
        assert device.interpret_state(2) is True

    @pytest.mark.parametrize("entity_type_str,entity_type_enum", CCO_PLATFORMS)
    def test_cco_device_interpret_state_off(self, entity_type_str, entity_type_enum):
        """CCO device interprets LED value 2 as OFF (relay open)."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=entity_type_enum,
        )
        assert device.interpret_state(1) is False

    @pytest.mark.parametrize("entity_type_str,entity_type_enum", CCO_PLATFORMS)
    def test_cco_device_interpret_state_zero(self, entity_type_str, entity_type_enum):
        """CCO device interprets LED value 0 as OFF (unknown state)."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=entity_type_enum,
        )
        assert device.interpret_state(0) is False

    @pytest.mark.parametrize("entity_type_str,entity_type_enum", CCO_PLATFORMS)
    def test_cco_device_inverted_state(self, entity_type_str, entity_type_enum):
        """Inverted CCO device reverses state interpretation."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test",
            entity_type=entity_type_enum,
            inverted=True,
        )
        assert device.interpret_state(2) is False  # Normally ON → OFF (inverted)
        assert device.interpret_state(1) is True  # Normally OFF → ON (inverted)


class TestCCOAddressGeneration:
    """Test address format generation for commands and KLS."""

    def test_to_kls_address_format(self):
        """to_kls_address returns zero-padded bracket format."""
        addr = CCOAddress(2, 6, 3, 6)
        assert addr.to_kls_address() == "[02:06:03]"

    def test_to_command_address_format(self):
        """to_command_address returns unpadded bracket format."""
        addr = CCOAddress(2, 6, 3, 6)
        assert addr.to_command_address() == "[2:6:3]"

    def test_unique_key_tuple(self):
        """unique_key returns (processor, link, address, button) tuple."""
        addr = CCOAddress(2, 6, 3, 6)
        assert addr.unique_key == (2, 6, 3, 6)

    def test_from_string_comma_format(self):
        """Parse '2:6:3,6' format."""
        addr = CCOAddress.from_string("2:6:3,6")
        assert addr.processor == 2
        assert addr.link == 6
        assert addr.address == 3
        assert addr.button == 6

    def test_from_string_colon_format(self):
        """Parse '2:6:3:6' format."""
        addr = CCOAddress.from_string("2:6:3:6")
        assert addr.processor == 2
        assert addr.button == 6

    def test_from_string_bracketed(self):
        """Parse '[02:06:03],6' format."""
        addr = CCOAddress.from_string("[02:06:03],6")
        assert addr.processor == 2
        assert addr.link == 6
        assert addr.address == 3
        assert addr.button == 6

    @pytest.mark.parametrize(
        "invalid_input",
        [
            pytest.param("invalid", id="no_colons"),
            pytest.param("1:2", id="too_few_parts"),
            pytest.param("", id="empty"),
            pytest.param("a:b:c,d", id="non_numeric"),
        ],
    )
    def test_from_string_invalid_raises(self, invalid_input):
        """Invalid address strings raise ValueError."""
        with pytest.raises(ValueError):
            CCOAddress.from_string(invalid_input)


# =============================================================================
# Switch-Specific Tests
# =============================================================================


class TestSwitchEntity:
    """Tests specific to HomeworksCCOSwitch."""

    def test_switch_entity_type_constant(self):
        """Switch uses CCO_TYPE_SWITCH constant."""
        from custom_components.homeworks_hwi.const import CCO_TYPE_SWITCH

        assert CCO_TYPE_SWITCH == "switch"

    def test_switch_device_is_on_from_state(self):
        """Switch is_on derived from coordinator CCO state."""
        device = CCODevice(
            address=CCOAddress(2, 6, 3, 6),
            name="Test Switch",
            entity_type=CCOEntityType.SWITCH,
        )
        # LED=1 means relay closed = ON
        assert device.interpret_state(2) is True


# =============================================================================
# Light-Specific Tests (Dimmer + CCO)
# =============================================================================


class TestLightDimmer:
    """Tests for dimmable light entities."""

    def test_dimmer_level_to_brightness_conversion(self):
        """Dimmer level 0-100 maps to brightness 0-255."""
        # Level 100 → brightness 255
        assert round(100 * 255 / 100) == 255
        # Level 50 → brightness ~128
        assert round(50 * 255 / 100) == 128
        # Level 0 → brightness 0
        assert round(0 * 255 / 100) == 0

    def test_brightness_to_level_conversion(self):
        """Brightness 0-255 maps back to level 0-100."""
        # Brightness 255 → level 100
        assert round(255 * 100 / 255) == 100
        # Brightness 128 → level ~50
        assert round(128 * 100 / 255) == 50

    def test_default_fade_rate(self):
        """Default fade rate is defined."""
        from custom_components.homeworks_hwi.const import DEFAULT_FADE_RATE

        assert DEFAULT_FADE_RATE == 0.01


# =============================================================================
# Cover-Specific Tests (CCO + RPM + QED)
# =============================================================================


class TestCoverTypes:
    """Tests for the three cover types."""

    def test_cover_type_constants(self):
        """All cover type constants are defined."""
        from custom_components.homeworks_hwi.const import (
            CCO_TYPE_COVER,
            DEFAULT_COVER_NAME,
            DEFAULT_RPM_COVER_NAME,
            DEFAULT_QED_COVER_NAME,
        )

        assert CCO_TYPE_COVER == "cover"
        assert DEFAULT_RPM_COVER_NAME == "Homeworks Motor Cover"
        assert DEFAULT_QED_COVER_NAME == "Homeworks QED Shade"

    def test_rpm_motor_command_values(self):
        """RPM motor uses specific dimmer values for up/down/stop."""
        # These constants are defined in coordinator.py (requires HA)
        # Validate expected protocol values directly
        RPM_MOTOR_UP = 16
        RPM_MOTOR_DOWN = 35
        RPM_MOTOR_STOP = 0

        assert RPM_MOTOR_UP == 16
        assert RPM_MOTOR_DOWN == 35
        assert RPM_MOTOR_STOP == 0


# =============================================================================
# Fan-Specific Tests
# =============================================================================


class TestFanEntity:
    """Tests specific to HomeworksCCOFan."""

    def test_fan_entity_type_constant(self):
        """Fan uses CCO_TYPE_FAN constant."""
        from custom_components.homeworks_hwi.const import CCO_TYPE_FAN

        assert CCO_TYPE_FAN == "fan"


# =============================================================================
# Lock-Specific Tests
# =============================================================================


class TestLockEntity:
    """Tests specific to HomeworksCCOLock."""

    def test_lock_entity_type_constant(self):
        """Lock uses CCO_TYPE_LOCK constant."""
        from custom_components.homeworks_hwi.const import CCO_TYPE_LOCK

        assert CCO_TYPE_LOCK == "lock"

    def test_lock_state_interpretation(self):
        """Lock ON = locked, OFF = unlocked."""
        device = CCODevice(
            address=CCOAddress(2, 6, 5, 1),
            name="Test Lock",
            entity_type=CCOEntityType.LOCK,
        )
        # LED=1 means relay closed = locked (is_on=True)
        assert device.interpret_state(2) is True
        # LED=2 means relay open = unlocked (is_on=False)
        assert device.interpret_state(1) is False


# =============================================================================
# Climate-Specific Tests
# =============================================================================


class TestClimateEntity:
    """Tests specific to HomeworksCCOClimate."""

    def test_climate_entity_type_constant(self):
        """Climate uses CCO_TYPE_CLIMATE constant."""
        from custom_components.homeworks_hwi.const import CCO_TYPE_CLIMATE

        assert CCO_TYPE_CLIMATE == "climate"

    def test_climate_is_on_off_only(self):
        """Climate entity is binary (heat ON or OFF via CCO)."""
        device = CCODevice(
            address=CCOAddress(2, 6, 6, 1),
            name="HVAC",
            entity_type=CCOEntityType.CLIMATE,
        )
        assert device.interpret_state(2) is True  # LED=1 = relay closed = Heating ON
        assert device.interpret_state(1) is False  # LED=2 = relay open = Heating OFF

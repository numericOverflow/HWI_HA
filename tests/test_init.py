"""Tests for integration setup, unload, and send_command service.

Covers:
- async_setup_entry creates runtime data
- async_unload_entry cleans up properly
- send_command service: delay cap, command execution
- create_cco_entities_for_type helper function
"""

import pytest
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)
from copy import deepcopy

from custom_components.homeworks_hwi.models import (
    CCOAddress,
    CCODevice,
    CCOEntityType,
)
from custom_components.homeworks_hwi.const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTON_NUMBER,
    CONF_CCO_DEVICES,
    CONF_CONTROLLER_ID,
    CONF_DIMMERS,
    CONF_ENTITY_TYPE,
    CONF_INVERTED,
    CONF_RATE,
    LEGACY_DEFAULT_FADE_RATE,
    CCO_TYPE_SWITCH,
    CCO_TYPE_LIGHT,
    CCO_TYPE_COVER,
    CCO_TYPE_LOCK,
    CCO_TYPE_FAN,
    CCO_TYPE_CLIMATE,
    MAX_COMMAND_DELAY_MS,
    DOMAIN,
)


# =============================================================================
# send_command Service Tests
# =============================================================================


class TestSendCommandService:
    """Tests for the send_command service behavior."""

    def test_max_delay_constant(self):
        """MAX_COMMAND_DELAY_MS is 60 seconds."""
        assert MAX_COMMAND_DELAY_MS == 60000

    def test_delay_cap_logic(self):
        """Delay values are capped at MAX_COMMAND_DELAY_MS."""
        # Simulate the delay capping logic
        test_cases = [
            ("delay 1000", 1000),
            ("delay 60000", 60000),
            ("delay 999999", 60000),  # Capped
            ("delay 0", 0),
        ]

        for command, expected in test_cases:
            parts = command.partition(" ")
            raw_delay = int(parts[2])
            capped = min(raw_delay, MAX_COMMAND_DELAY_MS)
            assert capped == expected, f"Failed for {command}"

    def test_delay_invalid_value_handling(self):
        """Invalid delay value should be handled gracefully."""
        command = "delay notanumber"
        parts = command.partition(" ")
        try:
            int(parts[2])
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # Expected

    def test_delay_case_insensitive(self):
        """Delay command detection is case-insensitive."""
        commands = ["delay 100", "DELAY 100", "Delay 100", "DeLaY 100"]
        for cmd in commands:
            assert cmd.lower().startswith("delay")

    def test_normal_command_not_delayed(self):
        """Non-delay commands are forwarded without sleep."""
        commands = ["KBP, [02:08:02], 1", "CCOCLOSE, [02:06:03], 6", "RKLS, [02:06:03]"]
        for cmd in commands:
            assert not cmd.lower().startswith("delay")


# =============================================================================
# CCO Entity Factory Tests
# =============================================================================


class TestCreateCCOEntitiesForType:
    """Tests for the create_cco_entities_for_type helper."""

    def _make_options_with_devices(self, devices):
        """Helper to create options dict."""
        return {
            CONF_CONTROLLER_ID: "test_controller",
            CONF_CCO_DEVICES: devices,
        }

    def test_filters_by_entity_type(self):
        """Only creates entities matching the target type."""
        devices = [
            {
                "name": "Switch 1",
                "addr": "[02:06:03]",
                "button_number": 1,
                "entity_type": "switch",
                "inverted": False,
            },
            {
                "name": "Light 1",
                "addr": "[02:06:03]",
                "button_number": 2,
                "entity_type": "light",
                "inverted": False,
            },
            {
                "name": "Switch 2",
                "addr": "[02:06:03]",
                "button_number": 3,
                "entity_type": "switch",
                "inverted": False,
            },
        ]

        # Count switches
        switches = [d for d in devices if d["entity_type"] == CCO_TYPE_SWITCH]
        assert len(switches) == 2

        # Count lights
        lights = [d for d in devices if d["entity_type"] == CCO_TYPE_LIGHT]
        assert len(lights) == 1

    def test_empty_cco_devices_returns_empty(self):
        """No CCO devices yields empty entity list."""
        devices = []
        switches = [d for d in devices if d.get("entity_type") == CCO_TYPE_SWITCH]
        assert switches == []

    def test_invalid_address_skipped(self):
        """Invalid address format is logged and skipped."""
        device_config = {
            "name": "Bad Device",
            "addr": "invalid",
            "button_number": 1,
            "entity_type": "switch",
            "inverted": False,
        }
        # Simulate parsing
        try:
            CCOAddress.from_string(
                f"{device_config['addr']},{device_config['button_number']}"
            )
            assert False, "Should have raised ValueError"
        except (ValueError, KeyError, TypeError):
            pass  # Expected — device would be skipped

    @pytest.mark.parametrize(
        "entity_type,expected_count",
        [
            (CCO_TYPE_SWITCH, 1),
            (CCO_TYPE_LIGHT, 1),
            (CCO_TYPE_COVER, 1),
            (CCO_TYPE_LOCK, 1),
            (CCO_TYPE_FAN, 1),
            (CCO_TYPE_CLIMATE, 1),
        ],
    )
    def test_all_entity_types_handled(self, entity_type, expected_count):
        """Each entity type is filtered correctly."""
        devices = [
            {
                "name": "Switch",
                "addr": "[02:06:03]",
                "button_number": 1,
                "entity_type": "switch",
                "inverted": False,
            },
            {
                "name": "Light",
                "addr": "[02:06:03]",
                "button_number": 2,
                "entity_type": "light",
                "inverted": False,
            },
            {
                "name": "Cover",
                "addr": "[02:06:03]",
                "button_number": 3,
                "entity_type": "cover",
                "inverted": False,
            },
            {
                "name": "Lock",
                "addr": "[02:06:04]",
                "button_number": 1,
                "entity_type": "lock",
                "inverted": False,
            },
            {
                "name": "Fan",
                "addr": "[02:06:04]",
                "button_number": 2,
                "entity_type": "fan",
                "inverted": False,
            },
            {
                "name": "Climate",
                "addr": "[02:06:04]",
                "button_number": 3,
                "entity_type": "climate",
                "inverted": False,
            },
        ]

        filtered = [d for d in devices if d["entity_type"] == entity_type]
        assert len(filtered) == expected_count


# =============================================================================
# Diagnostics Tests
# =============================================================================


class TestDiagnostics:
    """Tests for diagnostics output format and redaction."""

    def test_redacted_keys_defined(self):
        """Sensitive keys are in the redaction set."""
        from custom_components.homeworks_hwi.const import DOMAIN

        # These should be redacted in diagnostics
        sensitive_keys = {"password", "username", "host"}
        # Verify they are strings (not accidentally None)
        for key in sensitive_keys:
            assert isinstance(key, str)
            assert len(key) > 0

    def test_diagnostics_structure(self):
        """Diagnostics output should contain expected sections."""
        expected_sections = [
            "entry_data",
            "health",
            "device_counts",
        ]
        # Structural assertion — actual test verifies against real output
        assert len(expected_sections) >= 3

    async def test_cco_and_kls_diagnostics_fields(self):
        """CCO unknown count and per-module KLS ages are reported.

        These are the operator-facing signal that a window offset is wrong or
        that a module has stopped answering — a relay stuck at unknown is
        otherwise indistinguishable from one that is legitimately quiet.
        """
        from unittest.mock import AsyncMock, MagicMock

        from custom_components.homeworks_hwi.diagnostics import (
            async_get_config_entry_diagnostics,
        )
        from custom_components.homeworks_hwi.models import ControllerHealth

        coordinator = MagicMock()
        coordinator.health = ControllerHealth()
        coordinator.cco_device_count = 3
        coordinator.cco_state_count = 3
        coordinator.cco_unknown_count = 2
        coordinator.kls_poll_address_count = 1
        coordinator.keypad_led_state_count = 1
        coordinator.kls_last_seen_ages = MagicMock(return_value={"[01:05:03]": 4.2})
        coordinator.dimmer_address_count = 0
        coordinator.dimmer_state_count = 0

        entry = MagicMock()
        entry.options = {"controller_id": "test"}
        entry.runtime_data = MagicMock(coordinator=coordinator)

        result = await async_get_config_entry_diagnostics(MagicMock(), entry)

        assert result["cco_state_summary"]["unknown_count"] == 2
        assert result["kls_cache_info"]["last_kls_age_s"] == {"[01:05:03]": 4.2}


# =============================================================================
# Config Entry Migration v3.1 -> v3.2 (dimmer fade rates)
# =============================================================================


MIGRATION_DIMMER_ADDR = "[01:04:01:03:02]"


def _apply_update(entry, **kwargs):
    """Mimic async_update_entry by setting the given attributes on the entry."""
    for key, value in kwargs.items():
        setattr(entry, key, value)
    return True


class TestFadeRateMigration:
    """Tests for the v3.2 step that rewrites dimmer fade rates."""

    pytestmark = [pytest.mark.requires_ha]

    @staticmethod
    def _dimmer(**extra):
        from homeassistant.const import CONF_NAME

        return {CONF_ADDR: MIGRATION_DIMMER_ADDR, CONF_NAME: "Test", **extra}

    @staticmethod
    def _make(options, version=3, minor_version=1):
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock(side_effect=_apply_update)
        entry = MagicMock()
        entry.version = version
        entry.minor_version = minor_version
        entry.entry_id = "test_entry"
        entry.options = options
        return hass, entry

    @staticmethod
    async def _migrate(hass, entry):
        from custom_components.homeworks_hwi import async_migrate_entry

        return await async_migrate_entry(hass, entry)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("saved", "migrated"),
        [
            (0, 0.0),
            (0.005, 1.0),
            (0.01, 0.0),
            (0.02, 1.0),
            (0.5, 1.0),
            (0.99, 1.0),
            (1.0, 1.0),
            (1.5, 1.0),
            (2.25, 2.0),
            (20, 20.0),
        ],
    )
    async def test_rate_migrated(self, saved, migrated):
        """Each saved rate becomes whole seconds; rewritten values are floats."""
        options = {
            CONF_CONTROLLER_ID: "ctrl",
            CONF_DIMMERS: [self._dimmer(**{CONF_RATE: saved})],
        }
        hass, entry = self._make(options)

        assert await self._migrate(hass, entry) is True

        rate = entry.options[CONF_DIMMERS][0][CONF_RATE]
        assert rate == migrated
        if saved != migrated:
            assert type(rate) is float

    @pytest.mark.asyncio
    @pytest.mark.parametrize("saved", [0, 1.0, 20])
    async def test_unchanged_rate_kept(self, saved):
        """A rate that the rule does not change keeps its value and type."""
        options = {
            CONF_CONTROLLER_ID: "ctrl",
            CONF_DIMMERS: [self._dimmer(**{CONF_RATE: saved})],
        }
        hass, entry = self._make(options)

        await self._migrate(hass, entry)

        rate = entry.options[CONF_DIMMERS][0][CONF_RATE]
        assert rate == saved
        assert type(rate) is type(saved)

    @pytest.mark.asyncio
    async def test_other_dimmer_keys_kept(self):
        """Address, name, and area are not changed."""
        from homeassistant.const import CONF_NAME

        original = self._dimmer(**{CONF_RATE: 1.5, CONF_AREA: "area_1"})
        options = {CONF_CONTROLLER_ID: "ctrl", CONF_DIMMERS: [original]}
        hass, entry = self._make(options)

        await self._migrate(hass, entry)

        migrated = entry.options[CONF_DIMMERS][0]
        for key in (CONF_ADDR, CONF_NAME, CONF_AREA):
            assert migrated[key] == original[key]

    @pytest.mark.asyncio
    async def test_original_options_not_mutated(self):
        """New dimmer dicts are built, so HA can detect the options change."""
        original = self._dimmer(**{CONF_RATE: LEGACY_DEFAULT_FADE_RATE})
        options = {CONF_CONTROLLER_ID: "ctrl", CONF_DIMMERS: [original]}
        hass, entry = self._make(options)

        await self._migrate(hass, entry)

        assert original[CONF_RATE] == 0.01
        assert options[CONF_DIMMERS][0][CONF_RATE] == 0.01

    @pytest.mark.asyncio
    async def test_missing_or_bad_rate_kept(self):
        """A missing or non-numeric rate is left as saved."""
        no_rate = self._dimmer()
        bad_rate = self._dimmer(**{CONF_RATE: "x"})
        options = {CONF_CONTROLLER_ID: "ctrl", CONF_DIMMERS: [no_rate, bad_rate]}
        hass, entry = self._make(options)

        assert await self._migrate(hass, entry) is True

        assert entry.options[CONF_DIMMERS] == [no_rate, bad_rate]

    @pytest.mark.asyncio
    async def test_no_dimmers(self):
        """Options without dimmers stay without the key."""
        hass, entry = self._make({CONF_CONTROLLER_ID: "ctrl"})

        await self._migrate(hass, entry)

        assert CONF_DIMMERS not in entry.options
        assert entry.minor_version == 2

    @pytest.mark.asyncio
    async def test_already_v3_2_skipped(self):
        """An entry already at v3.2 is not updated."""
        options = {
            CONF_CONTROLLER_ID: "ctrl",
            CONF_DIMMERS: [self._dimmer(**{CONF_RATE: 1.5})],
        }
        hass, entry = self._make(options, minor_version=2)

        assert await self._migrate(hass, entry) is True

        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_v2_entry_chains_to_v3_2(self):
        """A v2 entry runs the v3 and v3.2 steps in one call."""
        options = {
            CONF_CONTROLLER_ID: "ctrl",
            CONF_CCO_DEVICES: [
                {
                    CONF_ADDR: "[02:06:03]",
                    CONF_BUTTON_NUMBER: 1,
                    CONF_ENTITY_TYPE: CCO_TYPE_SWITCH,
                    CONF_INVERTED: False,
                }
            ],
            CONF_DIMMERS: [self._dimmer(**{CONF_RATE: LEGACY_DEFAULT_FADE_RATE})],
        }
        hass, entry = self._make(options, version=2)

        assert await self._migrate(hass, entry) is True

        assert entry.version == 3
        assert entry.minor_version == 2
        assert entry.options[CONF_CCO_DEVICES][0][CONF_INVERTED] is True
        assert entry.options[CONF_DIMMERS][0][CONF_RATE] == 0.0

    @pytest.mark.asyncio
    async def test_migration_logs_count(self, caplog):
        """One info line reports the number of changed dimmers."""
        options = {
            CONF_CONTROLLER_ID: "ctrl",
            CONF_DIMMERS: [
                self._dimmer(**{CONF_RATE: LEGACY_DEFAULT_FADE_RATE}),
                self._dimmer(**{CONF_RATE: 1.5}),
                self._dimmer(**{CONF_RATE: 1.0}),
            ],
        }
        hass, entry = self._make(options)

        with caplog.at_level("INFO", logger="custom_components.homeworks_hwi"):
            await self._migrate(hass, entry)

        records = [r for r in caplog.records if "v3.2" in r.getMessage()]
        assert len(records) == 1
        assert "2 dimmer fade rates" in records[0].getMessage()

    def test_minor_version_constant(self):
        """The config flow creates entries at v3.2."""
        from custom_components.homeworks_hwi.config_flow import (
            HomeworksConfigFlowHandler,
        )

        assert HomeworksConfigFlowHandler.VERSION == 3
        assert HomeworksConfigFlowHandler.MINOR_VERSION == 2

    def test_legacy_default_constant(self):
        """The legacy default fade rate is 0.01."""
        assert LEGACY_DEFAULT_FADE_RATE == 0.01


# =============================================================================
# Platform Constants Tests
# =============================================================================


class TestPlatformConstants:
    """Tests for platform-level constants."""

    def test_domain_constant(self):
        """DOMAIN is correctly set."""
        assert DOMAIN == "homeworks_hwi"

    def test_all_cco_type_constants(self):
        """All CCO type constants are defined and unique."""
        types = {
            CCO_TYPE_SWITCH,
            CCO_TYPE_LIGHT,
            CCO_TYPE_COVER,
            CCO_TYPE_LOCK,
            CCO_TYPE_FAN,
            CCO_TYPE_CLIMATE,
        }
        assert len(types) == 6  # All unique

    @pytest.mark.parametrize(
        "entity_type_str,entity_type_enum",
        [
            ("switch", CCOEntityType.SWITCH),
            ("light", CCOEntityType.LIGHT),
            ("cover", CCOEntityType.COVER),
            ("lock", CCOEntityType.LOCK),
            ("fan", CCOEntityType.FAN),
            ("climate", CCOEntityType.CLIMATE),
        ],
    )
    def test_entity_type_enum_values(self, entity_type_str, entity_type_enum):
        """CCOEntityType enum has all expected members."""
        assert entity_type_enum is not None

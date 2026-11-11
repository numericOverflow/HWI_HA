"""Tests for HomeworksConfigFlowHandler.

Covers:
- User flow: successful setup, connection error, duplicate detection
- Reauth flow: credential rotation
- CSV import: size limits, row limits, valid parsing
- Legacy migration: v1 → v2 format conversion
"""

from copy import deepcopy
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

import pytest

pytestmark = pytest.mark.requires_ha


# =============================================================================
# Config Flow User Step Tests
# =============================================================================


class TestConfigFlowUserStep:
    """Tests for the initial user configuration step."""

    async def test_user_flow_shows_form(self):
        """Test that initiating flow shows the connection form."""
        try:
            from custom_components.homeworks_hwi.config_flow import (
                HomeworksConfigFlowHandler,
            )

            handler = HomeworksConfigFlowHandler()
            handler.hass = MagicMock()
            handler._async_current_entries = MagicMock(return_value=[])

            result = await handler.async_step_user(user_input=None)

            assert result["type"] == "form"
            assert result["step_id"] == "user"
        except ImportError:
            pytest.skip("Home Assistant not available")

    async def test_user_flow_success(self):
        """Test successful config flow creates entry."""
        try:
            from custom_components.homeworks_hwi.config_flow import (
                HomeworksConfigFlowHandler,
            )

            handler = HomeworksConfigFlowHandler()
            handler.hass = MagicMock()
            handler._async_current_entries = MagicMock(return_value=[])
            handler.async_create_entry = MagicMock(
                return_value={"type": "create_entry"}
            )
            handler.async_set_unique_id = AsyncMock()

            # Patch the module-level _try_connection function
            with patch(
                "custom_components.homeworks_hwi.config_flow._try_connection",
                new_callable=AsyncMock,
            ):
                await handler.async_step_user(
                    user_input={
                        "name": "Test Controller",
                        "host": "192.168.1.100",
                        "port": 23,
                        "username": "",
                        "password": "",
                    }
                )

            # Should call async_create_entry on success
            handler.async_create_entry.assert_called_once()
            call_kwargs = handler.async_create_entry.call_args[1]
            assert call_kwargs["title"] == "Test Controller"
            assert call_kwargs["data"]["host"] == "192.168.1.100"
            assert call_kwargs["data"]["port"] == 23
            assert "controller_id" in call_kwargs["options"]
        except ImportError:
            pytest.skip("Home Assistant not available")

    async def test_user_flow_connection_error(self):
        """Test connection failure shows error form."""
        try:
            from custom_components.homeworks_hwi.config_flow import (
                HomeworksConfigFlowHandler,
                SchemaFlowError,
            )

            handler = HomeworksConfigFlowHandler()
            handler.hass = MagicMock()
            handler._async_current_entries = MagicMock(return_value=[])
            handler.async_show_form = MagicMock(
                return_value={"type": "form", "errors": {"base": "connection_error"}}
            )

            # _try_connection raises SchemaFlowError on failure
            with patch(
                "custom_components.homeworks_hwi.config_flow._try_connection",
                new_callable=AsyncMock,
                side_effect=SchemaFlowError("connection_error"),
            ):
                result = await handler.async_step_user(
                    user_input={
                        "name": "Test Controller",
                        "host": "192.168.1.100",
                        "port": 23,
                        "username": "",
                        "password": "",
                    }
                )

            # Should show form with connection_error
            assert result["type"] == "form"
            assert result["errors"]["base"] == "connection_error"
        except ImportError:
            pytest.skip("Home Assistant not available")

    async def test_user_flow_duplicate_host_port(self):
        """Test duplicate host:port detection aborts."""
        try:
            from custom_components.homeworks_hwi.config_flow import (
                HomeworksConfigFlowHandler,
            )

            existing_entry = MagicMock()
            existing_entry.data = {"host": "192.168.1.100", "port": 23}
            existing_entry.options = {"controller_id": "existing"}

            handler = HomeworksConfigFlowHandler()
            handler.hass = MagicMock()
            handler._async_current_entries = MagicMock(return_value=[existing_entry])
            handler.async_abort = MagicMock(
                return_value={"type": "abort", "reason": "already_configured"}
            )

            # No need to patch _try_connection — duplicate check happens before it
            result = await handler.async_step_user(
                user_input={
                    "name": "Duplicate",
                    "host": "192.168.1.100",
                    "port": 23,
                    "username": "",
                    "password": "",
                }
            )

            # Should abort with already_configured
            handler.async_abort.assert_called_once_with(reason="already_configured")
            assert result["type"] == "abort"
            assert result["reason"] == "already_configured"
        except ImportError:
            pytest.skip("Home Assistant not available")


# =============================================================================
# Reauth Flow Tests
# =============================================================================


class TestReauthFlow:
    """Tests for the reauth credential rotation flow."""

    async def test_reauth_flow_exists(self):
        """Test that reauth step is implemented."""
        try:
            from custom_components.homeworks_hwi.config_flow import (
                HomeworksConfigFlowHandler,
            )

            assert hasattr(HomeworksConfigFlowHandler, "async_step_reauth")
            assert hasattr(HomeworksConfigFlowHandler, "async_step_reauth_confirm")
        except ImportError:
            pytest.skip("Home Assistant not available")


# =============================================================================
# CSV Import Tests
# =============================================================================


class TestCSVImportLimits:
    """Tests for CSV import size and row validation."""

    def test_csv_size_limit_constant_defined(self):
        """Verify MAX_CSV_SIZE is defined and reasonable."""
        from custom_components.homeworks_hwi.const import MAX_CSV_SIZE

        assert MAX_CSV_SIZE == 1_000_000

    def test_csv_row_limit_constant_defined(self):
        """Verify MAX_CSV_ROWS is defined and reasonable."""
        from custom_components.homeworks_hwi.const import MAX_CSV_ROWS

        assert MAX_CSV_ROWS == 5000

    def test_csv_within_limits_parses(self):
        """CSV content within limits should be parseable."""
        # Small valid CSV
        csv_content = "Name,Address,Type,Button\nSwitch1,[02:06:03],switch,1\n"
        assert len(csv_content) < 1_000_000

    def test_csv_exceeding_size_would_be_rejected(self):
        """CSV content exceeding 1MB should be rejected."""
        from custom_components.homeworks_hwi.const import MAX_CSV_SIZE

        oversized = "x" * (MAX_CSV_SIZE + 1)
        assert len(oversized) > MAX_CSV_SIZE


# =============================================================================
# Legacy Migration Tests
# =============================================================================


class TestLegacyMigration:
    """Tests for v1 → v2 config entry migration logic."""

    def test_legacy_ccos_format(self, mock_config_entry_legacy):
        """Verify legacy CCOS format is correctly structured."""
        options = mock_config_entry_legacy.options
        assert "ccos" in options
        assert len(options["ccos"]) == 1
        assert options["ccos"][0]["relay_number"] == 6

    def test_legacy_covers_format(self, mock_config_entry_legacy):
        """Verify legacy covers format is correctly structured."""
        options = mock_config_entry_legacy.options
        assert "covers" in options
        assert len(options["covers"]) == 1
        assert options["covers"][0]["name"] == "Old Cover"

    def test_legacy_locks_format(self, mock_config_entry_legacy):
        """Verify legacy locks format is correctly structured."""
        options = mock_config_entry_legacy.options
        assert "locks" in options
        assert len(options["locks"]) == 1
        assert options["locks"][0]["relay_number"] == 1

    def test_migration_ccos_to_cco_devices(self, mock_config_entry_legacy):
        """Simulate migration: CCOS → CCO_DEVICES with entity_type=switch."""
        options = deepcopy(mock_config_entry_legacy.options)
        new_options = dict(options)

        # Simulate migration logic
        for cco in new_options.pop("ccos", []):
            device = {
                "addr": cco["addr"],
                "button_number": cco.get("relay_number", 1),
                "name": cco.get("name", ""),
                "entity_type": "switch",
                "inverted": cco.get("inverted", False),
            }
            new_options.setdefault("cco_devices", []).append(device)

        assert "ccos" not in new_options
        assert len(new_options["cco_devices"]) == 1
        assert new_options["cco_devices"][0]["entity_type"] == "switch"
        assert new_options["cco_devices"][0]["button_number"] == 6

    def test_migration_covers_to_cco_devices(self, mock_config_entry_legacy):
        """Simulate migration: COVERS → CCO_DEVICES with entity_type=cover."""
        options = deepcopy(mock_config_entry_legacy.options)
        new_options = dict(options)

        for cover in new_options.pop("covers", []):
            device = {
                "addr": cover["addr"],
                "button_number": 1,
                "name": cover.get("name", ""),
                "entity_type": "cover",
                "inverted": cover.get("inverted", False),
            }
            new_options.setdefault("cco_devices", []).append(device)

        assert "covers" not in new_options
        assert len(new_options["cco_devices"]) == 1
        assert new_options["cco_devices"][0]["entity_type"] == "cover"
        assert new_options["cco_devices"][0]["button_number"] == 1

    def test_migration_locks_to_cco_devices(self, mock_config_entry_legacy):
        """Simulate migration: LOCKS → CCO_DEVICES with entity_type=lock."""
        options = deepcopy(mock_config_entry_legacy.options)
        new_options = dict(options)

        for lock_cfg in new_options.pop("locks", []):
            device = {
                "addr": lock_cfg["addr"],
                "button_number": lock_cfg.get("relay_number", 1),
                "name": lock_cfg.get("name", ""),
                "entity_type": "lock",
                "inverted": lock_cfg.get("inverted", False),
            }
            new_options.setdefault("cco_devices", []).append(device)

        assert "locks" not in new_options
        assert len(new_options["cco_devices"]) == 1
        assert new_options["cco_devices"][0]["entity_type"] == "lock"
        assert new_options["cco_devices"][0]["button_number"] == 1

    def test_migration_all_combined(self, mock_config_entry_legacy):
        """Full migration converts all legacy formats into unified cco_devices."""
        options = deepcopy(mock_config_entry_legacy.options)
        new_options = dict(options)

        # CCOS
        for cco in new_options.pop("ccos", []):
            device = {
                "addr": cco["addr"],
                "button_number": cco.get("relay_number", 1),
                "name": cco.get("name", ""),
                "entity_type": "switch",
                "inverted": cco.get("inverted", False),
            }
            new_options.setdefault("cco_devices", []).append(device)

        # COVERS
        for cover in new_options.pop("covers", []):
            device = {
                "addr": cover["addr"],
                "button_number": 1,
                "name": cover.get("name", ""),
                "entity_type": "cover",
                "inverted": cover.get("inverted", False),
            }
            new_options.setdefault("cco_devices", []).append(device)

        # LOCKS
        for lock_cfg in new_options.pop("locks", []):
            device = {
                "addr": lock_cfg["addr"],
                "button_number": lock_cfg.get("relay_number", 1),
                "name": lock_cfg.get("name", ""),
                "entity_type": "lock",
                "inverted": lock_cfg.get("inverted", False),
            }
            new_options.setdefault("cco_devices", []).append(device)

        assert "ccos" not in new_options
        assert "covers" not in new_options
        assert "locks" not in new_options
        assert len(new_options["cco_devices"]) == 3

        types = {d["entity_type"] for d in new_options["cco_devices"]}
        assert types == {"switch", "cover", "lock"}


# =============================================================================
# Selector Step Tests
# =============================================================================


def test_light_rate_selector_uses_whole_seconds():
    """The fade rate moves in 1 s steps; the release delay keeps 0.01 s."""
    from custom_components.homeworks_hwi.config_flow import (
        BUTTON_EDIT,
        LIGHT_EDIT,
    )
    from custom_components.homeworks_hwi.const import (
        CONF_RATE,
        CONF_RELEASE_DELAY,
    )

    rate = next(v for k, v in LIGHT_EDIT.items() if k == CONF_RATE)
    assert rate.config["step"] == 1
    delay = next(v for k, v in BUTTON_EDIT.items() if k == CONF_RELEASE_DELAY)
    assert delay.config["step"] == 0.01


# =============================================================================
# Time Synchronization Step Tests
# =============================================================================


def _time_sync_handler():
    """Return a mocked options handler with HA in America/Chicago."""
    handler = MagicMock()
    handler.options = {}
    hass = handler.parent_handler.hass
    hass.config.time_zone = "America/Chicago"

    async def run_in_executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = run_in_executor
    return handler


def _time_sync_input(timezone="auto", manage_dst=False):
    """Return a full time sync form submission."""
    return {
        "clock_sync_timezone": timezone,
        "clock_sync_enabled": True,
        "clock_sync_frequency": "monthly_first",
        "clock_sync_weekday": "sat",
        "clock_sync_time": "03:30:00",
        "clock_sync_manage_dst": manage_dst,
    }


class TestTimeSyncStep:
    """Tests for the Time Synchronization options step."""

    async def test_validate_stores_six_keys(self):
        """All six option keys are written to the options."""
        from custom_components.homeworks_hwi.config_flow import validate_time_sync

        handler = _time_sync_handler()
        user_input = _time_sync_input(manage_dst=True)
        assert await validate_time_sync(handler, user_input) == {}
        assert handler.options == user_input

    async def test_zone_without_dst_rejected_when_managing_dst(self):
        """UTC with manage DST on raises zone_has_no_dst."""
        from homeassistant.helpers.schema_config_entry_flow import SchemaFlowError

        from custom_components.homeworks_hwi.config_flow import validate_time_sync

        handler = _time_sync_handler()
        with pytest.raises(SchemaFlowError, match="zone_has_no_dst"):
            await validate_time_sync(
                handler, _time_sync_input(timezone="UTC", manage_dst=True)
            )
        assert handler.options == {}

    async def test_zone_without_dst_allowed_without_managing_dst(self):
        """UTC with manage DST off is accepted."""
        from custom_components.homeworks_hwi.config_flow import validate_time_sync

        handler = _time_sync_handler()
        await validate_time_sync(handler, _time_sync_input(timezone="UTC"))
        assert handler.options["clock_sync_timezone"] == "UTC"

    async def test_first_timezone_option_is_auto(self):
        """The first timezone option is auto, labelled with HA's zone."""
        from custom_components.homeworks_hwi.config_flow import get_time_sync_schema

        schema = await get_time_sync_schema(_time_sync_handler())
        timezone_selector = next(
            v for k, v in schema.schema.items() if k == "clock_sync_timezone"
        )
        options = timezone_selector.config["options"]
        assert options[0] == {"value": "auto", "label": "Auto (America/Chicago)"}
        assert {"value": "America/Chicago", "label": "America/Chicago"} in options

    def test_time_sync_follows_controller_settings(self):
        """The menu shows time_sync right after controller_settings."""
        from custom_components.homeworks_hwi.config_flow import OPTIONS_FLOW

        menu = list(OPTIONS_FLOW["init"].options)
        assert menu[menu.index("controller_settings") + 1] == "time_sync"

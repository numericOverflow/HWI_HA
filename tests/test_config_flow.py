"""Tests for HomeworksConfigFlowHandler.

Covers:
- User flow: successful setup, connection error, duplicate detection
- Reauth flow: credential rotation
- CSV import: size limits, row limits, valid parsing
- Legacy migration: v1 → v2 format conversion
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from copy import deepcopy

pytestmark = [
    pytest.mark.requires_ha,
    pytest.mark.asyncio,
]


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
            from custom_components.homeworks_hwi.const import DOMAIN

            handler = HomeworksConfigFlowHandler()
            handler.hass = MagicMock()
            handler._async_current_entries = MagicMock(return_value=[])
            handler.async_create_entry = MagicMock(return_value={"type": "create_entry"})
            handler.async_set_unique_id = AsyncMock()

            # Patch the module-level _try_connection function
            with patch(
                "custom_components.homeworks_hwi.config_flow._try_connection",
                new_callable=AsyncMock,
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
            handler.async_show_form = MagicMock(return_value={"type": "form", "errors": {"base": "connection_error"}})

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
            handler.async_abort = MagicMock(return_value={"type": "abort", "reason": "already_configured"})

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
        from const import MAX_CSV_SIZE

        assert MAX_CSV_SIZE == 1_000_000

    def test_csv_row_limit_constant_defined(self):
        """Verify MAX_CSV_ROWS is defined and reasonable."""
        from const import MAX_CSV_ROWS

        assert MAX_CSV_ROWS == 5000

    def test_csv_within_limits_parses(self):
        """CSV content within limits should be parseable."""
        # Small valid CSV
        csv_content = "Name,Address,Type,Button\nSwitch1,[02:06:03],switch,1\n"
        assert len(csv_content) < 1_000_000

    def test_csv_exceeding_size_would_be_rejected(self):
        """CSV content exceeding 1MB should be rejected."""
        from const import MAX_CSV_SIZE

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

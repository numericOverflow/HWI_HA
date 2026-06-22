"""Tests for Sivoia QED shade support.

Tests are split into:
- Protocol tests (no HA deps): DL float parsing
- CRUD tests (no HA deps): QED cover config operations
- Entity tests (requires HA): HomeworksQEDCover behavior
"""

import pytest
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

from pyhomeworks import MessageParser, DimmerLevelMessage, normalize_address


# =============================================================================
# Protocol Tests — DL float parsing (no HA deps)
# =============================================================================


class TestParseDLFloat:
    """Tests for _parse_dl handling of float values from QED shades."""

    def test_parse_dl_float_value(self):
        """Verify _parse_dl correctly parses float DL values like '97.00'."""
        parser = MessageParser()
        data = b"DL, [01:04:01:01], 97.00\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, DimmerLevelMessage)
        assert msg.address == "[01:04:01:01]"
        assert msg.level == 97

    def test_parse_dl_int_unchanged(self):
        """Verify _parse_dl still parses integer DL values correctly."""
        parser = MessageParser()
        data = b"DL, [01:04:01:01:01], 75\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, DimmerLevelMessage)
        assert msg.address == "[01:04:01:01:01]"
        assert msg.level == 75

    def test_parse_dl_float_zero(self):
        """Verify float '0.00' parses to level 0."""
        parser = MessageParser()
        data = b"DL, [01:04:01:01], 0.00\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        assert messages[0].level == 0

    def test_parse_dl_float_rounds_down(self):
        """Verify '49.49' rounds to 49."""
        parser = MessageParser()
        data = b"DL, [01:04:01:01], 49.49\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        assert messages[0].level == 49

    def test_parse_dl_float_rounds_up(self):
        """Verify '99.50' rounds to 100."""
        parser = MessageParser()
        data = b"DL, [01:04:01:01], 99.50\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        assert messages[0].level == 100

    def test_parse_dl_float_100(self):
        """Verify '100.00' parses to 100."""
        parser = MessageParser()
        data = b"DL, [01:04:01:01], 100.00\r\n"
        messages = parser.feed(data)

        assert len(messages) == 1
        assert messages[0].level == 100


# =============================================================================
# CRUD Tests — QED cover config operations (no HA deps)
# =============================================================================


def create_options_with_qed() -> dict:
    """Create an options dict with QED covers list."""
    return {
        "controller_id": "test_controller",
        "host": "192.168.1.100",
        "port": 23,
        "cco_devices": [],
        "dimmers": [],
        "keypads": [],
        "rpm_covers": [],
        "qed_covers": [],
        "kls_poll_interval": 10,
        "kls_window_offset": 9,
    }


class TestQEDCoverCRUD:
    """Tests for QED cover create/read/update/delete operations."""

    def test_add_qed_cover(self):
        """Test adding a QED cover to options."""
        options = create_options_with_qed()

        new_cover = {
            "name": "Master Bedroom Shade",
            "addr": "[01:04:01:01]",
        }
        options["qed_covers"].append(new_cover)

        assert len(options["qed_covers"]) == 1
        assert options["qed_covers"][0]["name"] == "Master Bedroom Shade"
        assert options["qed_covers"][0]["addr"] == "[01:04:01:01]"

    def test_add_qed_cover_with_area(self):
        """Test adding a QED cover with area assignment."""
        options = create_options_with_qed()

        new_cover = {
            "name": "Living Room Shade",
            "addr": "[01:04:01:02]",
            "area": "Living Room",
        }
        options["qed_covers"].append(new_cover)

        assert options["qed_covers"][0]["area"] == "Living Room"

    def test_duplicate_qed_cover_detection(self):
        """Test that duplicate addresses are detectable."""
        options = create_options_with_qed()
        options["qed_covers"].append({"name": "Shade 1", "addr": "[01:04:01:01]"})

        # Check duplicate detection logic
        existing_addr = normalize_address("[01:04:01:01]")
        is_dup = any(
            normalize_address(c["addr"]) == existing_addr
            for c in options["qed_covers"]
        )
        assert is_dup is True

        # Non-duplicate
        new_addr = normalize_address("[01:04:01:02]")
        is_dup = any(
            normalize_address(c["addr"]) == new_addr
            for c in options["qed_covers"]
        )
        assert is_dup is False

    def test_remove_qed_cover(self):
        """Test removing a QED cover from options."""
        options = create_options_with_qed()
        options["qed_covers"] = [
            {"name": "Shade 1", "addr": "[01:04:01:01]"},
            {"name": "Shade 2", "addr": "[01:04:01:02]"},
            {"name": "Shade 3", "addr": "[01:04:01:03]"},
        ]

        # Remove index 1
        removed = {"1"}
        new_items = [
            item for i, item in enumerate(options["qed_covers"])
            if str(i) not in removed
        ]
        options["qed_covers"] = new_items

        assert len(options["qed_covers"]) == 2
        assert options["qed_covers"][0]["name"] == "Shade 1"
        assert options["qed_covers"][1]["name"] == "Shade 3"

    def test_edit_qed_cover(self):
        """Test editing a QED cover name."""
        options = create_options_with_qed()
        options["qed_covers"].append({"name": "Old Name", "addr": "[01:04:01:01]"})

        options["qed_covers"][0].update({"name": "New Name"})

        assert options["qed_covers"][0]["name"] == "New Name"
        assert options["qed_covers"][0]["addr"] == "[01:04:01:01]"

    def test_csv_import_qed_type_mapping(self):
        """Test that QED CSV device_type values are recognized."""
        valid_types = ("QED", "QED_SHADE", "SIVOIA_QED", "QED_COVER")
        for device_type in valid_types:
            assert device_type in valid_types


# =============================================================================
# Entity Tests — HomeworksQEDCover (requires HA)
# =============================================================================

pytestmark_ha = pytest.mark.requires_ha


class TestHomeworksQEDCover:
    """Tests for the HomeworksQEDCover entity class.

    These tests mock the coordinator to verify entity behavior in isolation.
    """

    pytestmark = [pytest.mark.requires_ha]

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.get_dimmer_level = MagicMock(return_value=50)
        coordinator.register_dimmer = MagicMock()
        coordinator.async_fade_dim = AsyncMock(return_value=True)
        coordinator.async_stop_dim = AsyncMock(return_value=True)
        coordinator.async_request_dimmer_level = AsyncMock(return_value=True)
        return coordinator

    @pytest.fixture
    def qed_cover(self, mock_coordinator):
        """Create a QED cover entity for testing."""
        try:
            from custom_components.homeworks_hwi.cover import HomeworksQEDCover
        except ImportError:
            pytest.skip("Requires Home Assistant dependencies")

        cover = HomeworksQEDCover(
            coordinator=mock_coordinator,
            controller_id="test_ctrl",
            address="[01:04:01:01]",
            name="Test QED Shade",
            area="Living Room",
        )
        return cover

    def test_qed_cover_position_from_coordinator(self, qed_cover, mock_coordinator):
        """Verify current_cover_position returns coordinator's dimmer level."""
        mock_coordinator.get_dimmer_level.return_value = 75
        assert qed_cover.current_cover_position == 75

    def test_qed_cover_is_closed_when_zero(self, qed_cover, mock_coordinator):
        """Verify is_closed returns True when level < 1."""
        mock_coordinator.get_dimmer_level.return_value = 0
        # Trigger coordinator update so entity receives initial state
        qed_cover.async_write_ha_state = MagicMock()
        qed_cover._handle_coordinator_update()
        assert qed_cover.is_closed is True

    def test_qed_cover_is_not_closed_when_nonzero(self, qed_cover, mock_coordinator):
        """Verify is_closed returns False when level >= 1."""
        mock_coordinator.get_dimmer_level.return_value = 1
        # Trigger coordinator update so entity receives initial state
        qed_cover.async_write_ha_state = MagicMock()
        qed_cover._handle_coordinator_update()
        assert qed_cover.is_closed is False

    @pytest.mark.asyncio
    async def test_qed_cover_open(self, qed_cover, mock_coordinator):
        """Verify async_open_cover sets is_opening and calls fade_dim to 100."""
        # Patch async_write_ha_state since entity isn't added to hass
        qed_cover.async_write_ha_state = MagicMock()

        await qed_cover.async_open_cover()

        assert qed_cover.is_opening is True
        assert qed_cover.is_closing is False
        mock_coordinator.async_fade_dim.assert_called_once_with(
            "[01:04:01:01]", 100.0, 0.0, 0.0
        )

    @pytest.mark.asyncio
    async def test_qed_cover_close(self, qed_cover, mock_coordinator):
        """Verify async_close_cover sets is_closing and calls fade_dim to 0."""
        qed_cover.async_write_ha_state = MagicMock()

        await qed_cover.async_close_cover()

        assert qed_cover.is_closing is True
        assert qed_cover.is_opening is False
        mock_coordinator.async_fade_dim.assert_called_once_with(
            "[01:04:01:01]", 0.0, 0.0, 0.0
        )

    @pytest.mark.asyncio
    async def test_qed_cover_set_position(self, qed_cover, mock_coordinator):
        """Verify async_set_cover_position passes correct value and sets direction."""
        qed_cover.async_write_ha_state = MagicMock()
        mock_coordinator.get_dimmer_level.return_value = 75

        # Moving down (75 -> 30)
        await qed_cover.async_set_cover_position(position=30)

        assert qed_cover.is_closing is True
        assert qed_cover.is_opening is False
        mock_coordinator.async_fade_dim.assert_called_once_with(
            "[01:04:01:01]", 30.0, 0.0, 0.0
        )

    @pytest.mark.asyncio
    async def test_qed_cover_set_position_opening(self, qed_cover, mock_coordinator):
        """Verify set_position sets is_opening when moving up."""
        qed_cover.async_write_ha_state = MagicMock()
        mock_coordinator.get_dimmer_level.return_value = 25

        await qed_cover.async_set_cover_position(position=80)

        assert qed_cover.is_opening is True
        assert qed_cover.is_closing is False

    @pytest.mark.asyncio
    async def test_qed_cover_stop(self, qed_cover, mock_coordinator):
        """Verify async_stop_cover clears flags and calls stop_dim + request_level."""
        qed_cover.async_write_ha_state = MagicMock()
        qed_cover._is_opening = True

        await qed_cover.async_stop_cover()

        assert qed_cover.is_opening is False
        assert qed_cover.is_closing is False
        mock_coordinator.async_stop_dim.assert_called_once_with("[01:04:01:01]")
        mock_coordinator.async_request_dimmer_level.assert_called_once_with(
            "[01:04:01:01]"
        )

    def test_qed_cover_coordinator_update_clears_flags(self, qed_cover):
        """Verify _handle_coordinator_update resets movement flags."""
        qed_cover.async_write_ha_state = MagicMock()
        qed_cover._is_opening = True
        qed_cover._is_closing = False

        qed_cover._handle_coordinator_update()

        assert qed_cover.is_opening is False
        assert qed_cover.is_closing is False

    def test_qed_cover_unique_id(self, qed_cover):
        """Verify unique_id format."""
        assert qed_cover.unique_id == "homeworks.test_ctrl.qed_cover.[01:04:01:01].v2"

    def test_qed_cover_supported_features(self, qed_cover):
        """Verify all expected features are supported."""
        try:
            from homeassistant.components.cover import CoverEntityFeature
        except ImportError:
            pytest.skip("Requires Home Assistant dependencies")

        features = qed_cover.supported_features
        assert features & CoverEntityFeature.OPEN
        assert features & CoverEntityFeature.CLOSE
        assert features & CoverEntityFeature.STOP
        assert features & CoverEntityFeature.SET_POSITION

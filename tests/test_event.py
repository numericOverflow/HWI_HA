"""Tests for the keypad button event platform.

The event platform is what makes physically-pressed keypad buttons visible in
Home Assistant: the processor reports KBP/KBR/KBH/KBDT while KBMON is enabled,
and each configured button gets an event entity whose state is the timestamp of
the last reported activation.

`button` entities cannot do this - ButtonEntity.state is @final and only records
presses issued through Home Assistant - which is why those stay "unknown".
"""

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.requires_ha


@pytest.fixture
def button_event(mock_coordinator):
    """Create a button event entity wired to the mock coordinator."""
    try:
        from custom_components.homeworks_hwi.event import HomeworksButtonEvent
    except ImportError:
        pytest.skip("Requires Home Assistant dependencies")

    entity = HomeworksButtonEvent(
        coordinator=mock_coordinator,
        controller_id="test_ctrl",
        keypad_addr="[02:08:02]",
        keypad_name="Back Hall",
        button_name="GOODNIGHT",
        button_number=3,
        area="Back Hall",
    )
    # Entity is not added to hass in these tests.
    entity.entity_id = "event.back_hall_goodnight"
    entity.async_write_ha_state = MagicMock()
    return entity


class TestButtonEventIdentity:
    """Entity metadata must be stable across restarts and unique per button."""

    def test_unique_id_format(self, button_event):
        """unique_id follows the versioned homeworks.<ctrl>.event.<addr>.<n>.v2 scheme."""
        assert button_event.unique_id == "homeworks.test_ctrl.event.[02:08:02].3.v2"

    def test_shares_keypad_device(self, button_event):
        """Event entity attaches to the same device as the button/LED entities."""
        from custom_components.homeworks_hwi.const import DOMAIN

        assert button_event.device_info["identifiers"] == {
            (DOMAIN, "test_ctrl.[02:08:02].v2")
        }
        assert button_event.device_info["suggested_area"] == "Back Hall"

    def test_device_class_and_event_types(self, button_event):
        """Device class is button and all four protocol activations are declared."""
        from homeassistant.components.event import EventDeviceClass

        from custom_components.homeworks_hwi.const import BUTTON_EVENT_TYPES

        assert button_event.device_class == EventDeviceClass.BUTTON
        assert button_event.event_types == list(BUTTON_EVENT_TYPES)

    def test_state_unknown_before_any_activation(self, button_event):
        """No activation reported yet reads as unknown, not a stale timestamp."""
        assert button_event.state is None


class TestButtonEventSubscription:
    """The coordinator's button dispatch must be subscribed to and released."""

    @pytest.mark.asyncio
    async def test_subscribes_on_add(self, button_event, mock_coordinator):
        """Adding the entity registers a button callback for its keypad address."""
        await button_event.async_added_to_hass()

        mock_coordinator.register_button_callback.assert_called_once()
        address, handler = mock_coordinator.register_button_callback.call_args[0]
        assert address == "[02:08:02]"
        assert handler == button_event._handle_button_event

    @pytest.mark.asyncio
    async def test_unsubscribes_on_remove(self, button_event, mock_coordinator):
        """Removing the entity calls the unregister callable exactly once."""
        unregister = MagicMock()
        mock_coordinator.register_button_callback.return_value = unregister

        await button_event.async_added_to_hass()
        await button_event.async_will_remove_from_hass()

        unregister.assert_called_once()
        assert button_event._unregister_callback is None

    @pytest.mark.asyncio
    async def test_remove_without_add_is_safe(self, button_event):
        """Removal before subscription does not raise."""
        await button_event.async_will_remove_from_hass()


class TestButtonEventDispatch:
    """Activation handling: filtering, state, and attributes."""

    @pytest.mark.parametrize(
        "event_type",
        ["pressed", "released", "hold", "double_tap"],
    )
    def test_activation_sets_state_and_event_type(self, button_event, event_type):
        """Each supported activation timestamps the entity and records its type."""
        button_event._handle_button_event("[02:08:02]", 3, event_type)

        assert button_event.state is not None
        assert button_event.state_attributes["event_type"] == event_type
        button_event.async_write_ha_state.assert_called_once()

    def test_activation_carries_address_and_button(self, button_event):
        """Attributes identify which physical button on which keypad fired."""
        button_event._handle_button_event("[02:08:02]", 3, "pressed")

        attributes = button_event.state_attributes
        assert attributes["homeworks_address"] == "[02:08:02]"
        assert attributes["button_number"] == 3

    def test_other_button_on_same_keypad_ignored(self, button_event):
        """Callbacks are per-keypad, so a different button number is filtered out."""
        button_event._handle_button_event("[02:08:02]", 4, "pressed")

        assert button_event.state is None
        button_event.async_write_ha_state.assert_not_called()

    def test_unsupported_event_type_ignored(self, button_event):
        """An event type outside event_types is dropped, not raised as ValueError."""
        button_event._handle_button_event("[02:08:02]", 3, "triple_tap")

        assert button_event.state is None
        button_event.async_write_ha_state.assert_not_called()

    def test_repeat_activation_updates_timestamp(self, button_event):
        """A second press onto an already-active scene still updates the state."""
        button_event._handle_button_event("[02:08:02]", 3, "pressed")
        first = button_event.state

        button_event._handle_button_event("[02:08:02]", 3, "pressed")

        assert button_event.state is not None
        assert button_event.state >= first
        assert button_event.async_write_ha_state.call_count == 2


class TestEventPlatformSetup:
    """One event entity is created per configured keypad button."""

    @pytest.mark.asyncio
    async def test_setup_creates_entity_per_button(self, mock_hass, mock_coordinator):
        """Buttons across multiple keypads each get an event entity."""
        try:
            from custom_components.homeworks_hwi.event import async_setup_entry
        except ImportError:
            pytest.skip("Requires Home Assistant dependencies")

        entry = MagicMock()
        entry.runtime_data.coordinator = mock_coordinator
        entry.options = {
            "controller_id": "test_ctrl",
            "keypads": [
                {
                    "name": "Back Hall",
                    "addr": "[02:08:02]",
                    "buttons": [
                        {"name": "GOODNIGHT", "number": 3},
                        {"name": "ALL ON", "number": 4},
                    ],
                },
                {
                    "name": "Kitchen",
                    "addr": "[2:8:3]",
                    "buttons": [{"name": "COOK", "number": 1}],
                },
            ],
        }

        added = []
        await async_setup_entry(mock_hass, entry, lambda entities: added.extend(entities))

        assert len(added) == 3
        assert {e.unique_id for e in added} == {
            "homeworks.test_ctrl.event.[02:08:02].3.v2",
            "homeworks.test_ctrl.event.[02:08:02].4.v2",
            "homeworks.test_ctrl.event.[02:08:03].1.v2",
        }

    @pytest.mark.asyncio
    async def test_setup_without_keypads_adds_nothing(self, mock_hass, mock_coordinator):
        """No configured keypads means no entities and no add_entities call."""
        try:
            from custom_components.homeworks_hwi.event import async_setup_entry
        except ImportError:
            pytest.skip("Requires Home Assistant dependencies")

        entry = MagicMock()
        entry.runtime_data.coordinator = mock_coordinator
        entry.options = {"controller_id": "test_ctrl", "keypads": []}

        async_add_entities = MagicMock()
        await async_setup_entry(mock_hass, entry, async_add_entities)

        async_add_entities.assert_not_called()

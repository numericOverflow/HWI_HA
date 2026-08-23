"""Support for Lutron Homeworks keypad button events.

The HomeWorks processor reports every button activation on the RS-232 link
once ``KBMON`` is enabled (see ``hwi_rs232_protocol/L232/kbmon.htm``):

- ``KBP, [pp:ll:aa], <button>``  button pressed
- ``KBR, [pp:ll:aa], <button>``  button released
- ``KBH, [pp:ll:aa], <button>``  button held
- ``KBDT, [pp:ll:aa], <button>`` button double tapped

These messages are emitted for *activations only*, whether the button was
pressed physically on the keypad or simulated with a ``KBP`` command. They are
therefore the only reliable signal for "a button was actually used".

This is deliberately separate from the keypad LED state (``KLS``): a processor
changes LEDs whenever the scene it tracks changes, so an LED transition does
NOT imply a button press. Conversely a press onto an already-active scene
produces a button event with no LED change.

``button`` entities cannot carry this information: Home Assistant's
``ButtonEntity.state`` is a ``@final`` timestamp of the last press made
*through Home Assistant* and cannot be set by an integration. Each configured
keypad button therefore also gets an ``event`` entity, whose state is the
timestamp of the last activation reported by the processor and whose
``event_type`` attribute says which kind it was.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksHWIConfigEntry, resolve_area_name
from .const import (
    ATTR_BUTTON_NUMBER,
    ATTR_HOMEWORKS_ADDRESS,
    BUTTON_EVENT_TYPES,
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTONS,
    CONF_CONTROLLER_ID,
    CONF_KEYPADS,
    CONF_NUMBER,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import normalize_address

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeworksHWIConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeworks keypad button event entities."""
    coordinator = entry.runtime_data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[HomeworksButtonEvent] = []

    for keypad in entry.options.get(CONF_KEYPADS, []):
        keypad_addr = normalize_address(keypad[CONF_ADDR])
        keypad_name = keypad.get(CONF_NAME, "Keypad")
        keypad_area = resolve_area_name(hass, keypad.get(CONF_AREA))

        for button in keypad.get(CONF_BUTTONS, []):
            entities.append(
                HomeworksButtonEvent(
                    coordinator=coordinator,
                    controller_id=controller_id,
                    keypad_addr=keypad_addr,
                    keypad_name=keypad_name,
                    button_name=button.get(CONF_NAME, "Button"),
                    button_number=button[CONF_NUMBER],
                    area=keypad_area,
                )
            )

    if entities:
        _LOGGER.debug("Adding %d button event entities", len(entities))
        async_add_entities(entities)


class HomeworksButtonEvent(CoordinatorEntity[HomeworksCoordinator], EventEntity):
    """Last activation reported by the processor for one keypad button."""

    _attr_has_entity_name = True
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(BUTTON_EVENT_TYPES)

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        keypad_addr: str,
        keypad_name: str,
        button_name: str,
        button_number: int,
        area: str | None = None,
    ) -> None:
        """Initialize the button event entity."""
        super().__init__(coordinator)
        self._controller_id = controller_id
        self._keypad_addr = keypad_addr
        self._button_number = button_number
        self._unregister_callback: Callable[[], None] | None = None

        self._attr_unique_id = (
            f"homeworks.{controller_id}.event.{keypad_addr}.{button_number}.v2"
        )
        self._attr_name = button_name
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.{keypad_addr}.v2")},
            name=keypad_name,
            manufacturer="Lutron",
            model="HomeWorks Keypad",
        )
        if area:
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to button events for this keypad."""
        await super().async_added_to_hass()
        self._unregister_callback = self.coordinator.register_button_callback(
            self._keypad_addr,
            self._handle_button_event,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from button events."""
        if self._unregister_callback:
            self._unregister_callback()
            self._unregister_callback = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_button_event(self, address: str, button: int, event_type: str) -> None:
        """Record an activation reported by the processor for this button."""
        if button != self._button_number:
            return
        if event_type not in self.event_types:
            _LOGGER.debug(
                "Ignoring unsupported event type %s for %s button %d",
                event_type,
                address,
                button,
            )
            return

        self._trigger_event(
            event_type,
            {
                ATTR_HOMEWORKS_ADDRESS: self._keypad_addr,
                ATTR_BUTTON_NUMBER: self._button_number,
            },
        )
        self.async_write_ha_state()

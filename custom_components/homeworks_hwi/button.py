"""Support for Lutron Homeworks buttons (keypad button simulation)."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeworksData, HomeworksHWIConfigEntry
from .const import (
    CONF_ADDR,
    CONF_BUTTONS,
    CONF_CONTROLLER_ID,
    CONF_KEYPADS,
    CONF_NUMBER,
    CONF_RELEASE_DELAY,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import normalize_address

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks buttons."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[HomeworksButton] = []

    for keypad in entry.options.get(CONF_KEYPADS, []):
        keypad_addr = normalize_address(keypad[CONF_ADDR])
        keypad_name = keypad.get(CONF_NAME, "Keypad")

        for button in keypad.get(CONF_BUTTONS, []):
            entity = HomeworksButton(
                coordinator=coordinator,
                controller_id=controller_id,
                keypad_addr=keypad_addr,
                keypad_name=keypad_name,
                button_name=button.get(CONF_NAME, "Button"),
                button_number=button[CONF_NUMBER],
                release_delay=button.get(CONF_RELEASE_DELAY, 0),
            )
            entities.append(entity)

    if entities:
        _LOGGER.debug("Adding %d button entities", len(entities))
        async_add_entities(entities)


class HomeworksButton(ButtonEntity):
    """Homeworks Button - simulates keypad button press."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        keypad_addr: str,
        keypad_name: str,
        button_name: str,
        button_number: int,
        release_delay: float,
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._controller_id = controller_id
        self._keypad_addr = keypad_addr
        self._button_number = button_number
        self._release_delay = release_delay

        self._attr_unique_id = (
            f"homeworks.{controller_id}.button.{keypad_addr}.{button_number}.v2"
        )
        self._attr_name = button_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.{keypad_addr}.v2")},
            name=keypad_name,
            manufacturer="Lutron",
            model="HomeWorks Keypad",
        )
        self._attr_extra_state_attributes = {
            "homeworks_address": keypad_addr,
            "button_number": button_number,
        }

    @property
    def available(self) -> bool:
        """Return True if the coordinator is connected."""
        return self._coordinator.connected

    async def async_press(self) -> None:
        """Press the button."""
        _LOGGER.debug(
            "Pressing button %d on keypad %s",
            self._button_number,
            self._keypad_addr,
        )

        await self._coordinator.async_keypad_button_press(
            self._keypad_addr, self._button_number
        )

        if self._release_delay > 0:
            self.hass.async_create_task(self._delayed_release())

    async def _delayed_release(self) -> None:
        """Release the button after delay."""
        await asyncio.sleep(self._release_delay)
        await self._coordinator.async_keypad_button_release(
            self._keypad_addr, self._button_number
        )

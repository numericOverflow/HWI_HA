"""Support for Lutron Homeworks CCO relays as fans (on/off only)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksHWIConfigEntry, create_cco_entities_for_type
from .const import (
    CONF_CONTROLLER_ID,
    CCO_TYPE_FAN,
    DEFAULT_FAN_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCODevice, CCOEntityType

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks CCO relays as fans."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]

    entities = create_cco_entities_for_type(
        hass, entry, coordinator, controller_id,
        CCO_TYPE_FAN, CCOEntityType.FAN, HomeworksCCOFan, DEFAULT_FAN_NAME,
    )

    if entities:
        _LOGGER.debug("Adding %d CCO fan entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No CCO fans to add")


class HomeworksCCOFan(CoordinatorEntity[HomeworksCoordinator], FanEntity):
    """Homeworks CCO Relay Fan.

    This is an on/off only fan device (no speed control).
    State is derived from the central KLS state engine in the coordinator.
    """

    _attr_supported_features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        device: CCODevice,
    ) -> None:
        """Initialize the CCO fan."""
        super().__init__(coordinator)
        self._device = device
        self._controller_id = controller_id

        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_unique_id = f"homeworks.{controller_id}.fan.{device.unique_id}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.fan.{device.address}.v2")},
            name=device.name,
            manufacturer="Lutron",
            model="HomeWorks CCO Fan",
        )
        if device.area:
            device_info["suggested_area"] = device.area
        self._attr_device_info = device_info
        self._attr_extra_state_attributes = {
            "homeworks_address": str(device.address),
            "button": device.address.button,
            "inverted": device.inverted,
        }

    @property
    def is_on(self) -> bool:
        """Return True if the fan is on."""
        return self.coordinator.get_cco_state(self._device.address)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan (close the CCO relay)."""
        _LOGGER.debug("Turning on CCO fan: %s", self._device.address)
        await self.coordinator.async_cco_turn_on(self._device)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan (open the CCO relay)."""
        _LOGGER.debug("Turning off CCO fan: %s", self._device.address)
        await self.coordinator.async_cco_turn_off(self._device)

    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates when added to hass."""
        await super().async_added_to_hass()

        # Ensure the CCO device is registered with the coordinator
        self.coordinator.register_cco_device(self._device)

        # Request initial state
        await self.coordinator.async_request_keypad_led_states(
            self._device.address.to_kls_address()
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister CCO device when removed from hass."""
        self.coordinator.unregister_cco_device(self._device.address)
        await super().async_will_remove_from_hass()

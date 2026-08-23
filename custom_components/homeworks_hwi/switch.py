"""Support for Lutron Homeworks CCO relays as switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksHWIConfigEntry, create_cco_entities_for_type
from .const import (
    CONF_CONTROLLER_ID,
    CCO_TYPE_SWITCH,
    DEFAULT_SWITCH_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCODevice, CCOEntityType

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks CCO relays as switches."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]

    entities = create_cco_entities_for_type(
        hass, entry, coordinator, controller_id,
        CCO_TYPE_SWITCH, CCOEntityType.SWITCH, HomeworksCCOSwitch, DEFAULT_SWITCH_NAME,
    )

    if entities:
        _LOGGER.debug("Adding %d CCO switch entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No CCO switches to add")


class HomeworksCCOSwitch(CoordinatorEntity[HomeworksCoordinator], SwitchEntity):
    """Homeworks CCO Relay Switch.

    State is derived from the central KLS state engine in the coordinator.
    """

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        device: CCODevice,
    ) -> None:
        """Initialize the CCO switch."""
        super().__init__(coordinator)
        self._device = device
        self._controller_id = controller_id

        # Modern HA entity naming: entity IS the device (1:1 mapping)
        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_unique_id = f"homeworks.{controller_id}.cco.{device.unique_id}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.cco.{device.address}.v2")},
            name=device.name,
            manufacturer="Lutron",
            model="HomeWorks CCO",
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
    def is_on(self) -> bool | None:
        """Return True if the switch is on, or None if not yet known.

        State is read from the coordinator's central CCO state cache, which
        is populated by the KLS state engine. None (shown as "unknown") means
        the processor has not yet reported this relay's position — a CCO relay
        latches, so there is no safe state to assume in the meantime.
        """
        return self.coordinator.get_cco_state(self._device.address)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return CCO address and relay feedback details."""
        return {
            **self._attr_extra_state_attributes,
            **self.coordinator.get_cco_diagnostics(self._device.address),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch (close the CCO relay)."""
        _LOGGER.debug("Turning on CCO switch: %s", self._device.address)
        await self.coordinator.async_cco_turn_on(self._device)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch (open the CCO relay)."""
        _LOGGER.debug("Turning off CCO switch: %s", self._device.address)
        await self.coordinator.async_cco_turn_off(self._device)

    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates when added to hass."""
        await super().async_added_to_hass()

        # Ensure the CCO device is registered with the coordinator.
        # No RKLS is issued here: the coordinator pre-registers module
        # addresses from config and sweeps them on the first refresh, so
        # asking per entity would send one duplicate request per relay on
        # the same board (L232/cco_kls_state.htm implementation note 3).
        self.coordinator.register_cco_device(self._device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister CCO device when removed from hass."""
        self.coordinator.unregister_cco_device(self._device.address)
        await super().async_will_remove_from_hass()

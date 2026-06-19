"""Support for Lutron Homeworks locks (CCO-based)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksHWIConfigEntry, create_cco_entities_for_type
from .const import (
    CONF_CONTROLLER_ID,
    CCO_TYPE_LOCK,
    DEFAULT_LOCK_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCODevice, CCOEntityType

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks locks."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]

    entities = create_cco_entities_for_type(
        hass, entry, coordinator, controller_id,
        CCO_TYPE_LOCK, CCOEntityType.LOCK, HomeworksCCOLock, DEFAULT_LOCK_NAME,
    )

    if entities:
        _LOGGER.debug("Adding %d lock entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No locks to add")


class HomeworksCCOLock(CoordinatorEntity[HomeworksCoordinator], LockEntity):
    """Homeworks CCO-based Lock.

    Lock state is derived from KLS feedback:
    - Locked = CCO relay closed (ON state)
    - Unlocked = CCO relay open (OFF state)
    """

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        device: CCODevice,
    ) -> None:
        """Initialize the lock."""
        super().__init__(coordinator)
        self._device = device
        self._controller_id = controller_id

        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_unique_id = f"homeworks.{controller_id}.lock.{device.unique_id}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.lock.{device.address}.v2")},
            name=device.name,
            manufacturer="Lutron",
            model="HomeWorks Lock",
        )
        if device.area:
            device_info["suggested_area"] = device.area
        self._attr_device_info = device_info
        self._attr_extra_state_attributes = {
            "homeworks_address": str(device.address),
            "inverted": device.inverted,
        }

    @property
    def is_locked(self) -> bool:
        """Return True if the lock is locked.

        Locked = CCO relay closed (ON state from KLS).
        Inversion is already handled by the coordinator's state engine.
        """
        return self.coordinator.get_cco_state(self._device.address)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock (close the CCO relay)."""
        _LOGGER.debug("Locking: %s", self._device.address)
        await self.coordinator.async_cco_turn_on(self._device)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock (open the CCO relay)."""
        _LOGGER.debug("Unlocking: %s", self._device.address)
        await self.coordinator.async_cco_turn_off(self._device)

    async def async_added_to_hass(self) -> None:
        """Register with coordinator when added to hass."""
        await super().async_added_to_hass()

        # Ensure device is registered
        self.coordinator.register_cco_device(self._device)

        # Request initial state
        await self.coordinator.async_request_keypad_led_states(
            self._device.address.to_kls_address()
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister CCO device when removed from hass."""
        self.coordinator.unregister_cco_device(self._device.address)
        await super().async_will_remove_from_hass()

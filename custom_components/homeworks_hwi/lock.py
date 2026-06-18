"""Support for Lutron Homeworks locks (CCO-based)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksData, HomeworksHWIConfigEntry, resolve_area_name
from .const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTON_NUMBER,
    CONF_CCO_DEVICES,
    CONF_CONTROLLER_ID,
    CONF_ENTITY_TYPE,
    CONF_INVERTED,
    CONF_LOCKS,
    CONF_RELAY_NUMBER,
    CCO_TYPE_LOCK,
    DEFAULT_LOCK_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCOAddress, CCODevice, CCOEntityType, normalize_address

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks locks."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[HomeworksCCOLock] = []

    # New-style CCO devices with type=lock
    for device_config in entry.options.get(CONF_CCO_DEVICES, []):
        if device_config.get(CONF_ENTITY_TYPE) != CCO_TYPE_LOCK:
            continue

        try:
            addr_str = device_config[CONF_ADDR]
            # Check CONF_BUTTON_NUMBER (new) then CONF_RELAY_NUMBER (legacy)
            button = device_config.get(
                CONF_BUTTON_NUMBER, device_config.get(CONF_RELAY_NUMBER, 1)
            )

            if "," not in addr_str:
                full_addr = f"{addr_str},{button}"
            else:
                full_addr = addr_str

            address = CCOAddress.from_string(full_addr)

            device = CCODevice(
                address=address,
                name=device_config.get(CONF_NAME, DEFAULT_LOCK_NAME),
                entity_type=CCOEntityType.LOCK,
                inverted=device_config.get(CONF_INVERTED, False),
                area=resolve_area_name(hass, device_config.get(CONF_AREA)),
            )

            entity = HomeworksCCOLock(
                coordinator=coordinator,
                controller_id=controller_id,
                device=device,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for lock device '%s': %s",
                device_config.get(CONF_NAME, "unknown"),
                err,
            )

    # Legacy locks format
    for lock_config in entry.options.get(CONF_LOCKS, []):
        try:
            addr = normalize_address(lock_config[CONF_ADDR])
            relay = lock_config.get(CONF_RELAY_NUMBER, 1)
            parts = addr.strip("[]").split(":")

            address = CCOAddress(
                processor=int(parts[0]),
                link=int(parts[1]),
                address=int(parts[2]),
                button=relay,
            )

            device = CCODevice(
                address=address,
                name=lock_config.get(CONF_NAME, DEFAULT_LOCK_NAME),
                entity_type=CCOEntityType.LOCK,
                inverted=lock_config.get(CONF_INVERTED, False),
                area=resolve_area_name(hass, lock_config.get(CONF_AREA)),
            )

            entity = HomeworksCCOLock(
                coordinator=coordinator,
                controller_id=controller_id,
                device=device,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for legacy lock device '%s': %s",
                lock_config.get(CONF_NAME, "unknown"),
                err,
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

        self._entity_name = device.name
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
    def name(self) -> str:
        """Return the name of the entity."""
        return self._entity_name

    @property
    def is_locked(self) -> bool:
        """Return True if the lock is locked.

        Locked = CCO relay closed (ON state from KLS).
        """
        is_on = self.coordinator.get_cco_state(self._device.address)

        if self._device.inverted:
            return not is_on
        return is_on

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock (close the CCO relay)."""
        _LOGGER.debug("Locking: %s", self._device.address)

        if self._device.inverted:
            await self.coordinator.async_cco_open(self._device.address)
        else:
            await self.coordinator.async_cco_close(self._device.address)
        # Optimistic state update is handled by coordinator

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock (open the CCO relay)."""
        _LOGGER.debug("Unlocking: %s", self._device.address)

        if self._device.inverted:
            await self.coordinator.async_cco_close(self._device.address)
        else:
            await self.coordinator.async_cco_open(self._device.address)
        # Optimistic state update is handled by coordinator

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

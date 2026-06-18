"""Support for Lutron Homeworks CCO relays as switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    CONF_CCOS,
    CONF_CONTROLLER_ID,
    CONF_ENTITY_TYPE,
    CONF_INVERTED,
    CONF_RELAY_NUMBER,
    CCO_TYPE_SWITCH,
    DEFAULT_SWITCH_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCOAddress, CCODevice, CCOEntityType, normalize_address

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks CCO relays as switches."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[HomeworksCCOSwitch] = []

    # New-style CCO devices with type=switch
    _LOGGER.debug(
        "Switch platform: reading %d CCO devices from config",
        len(entry.options.get(CONF_CCO_DEVICES, [])),
    )

    for device_config in entry.options.get(CONF_CCO_DEVICES, []):
        entity_type = device_config.get(CONF_ENTITY_TYPE, CCO_TYPE_SWITCH)
        _LOGGER.debug(
            "Switch platform checking device %s: entity_type=%s",
            device_config.get(CONF_NAME, "unknown"),
            entity_type,
        )
        if entity_type != CCO_TYPE_SWITCH:
            _LOGGER.debug("Skipping - not a switch (type=%s)", entity_type)
            continue

        try:
            addr_str = device_config[CONF_ADDR]
            # Check CONF_BUTTON_NUMBER (new) then CONF_RELAY_NUMBER (legacy)
            button = device_config.get(
                CONF_BUTTON_NUMBER, device_config.get(CONF_RELAY_NUMBER, 1)
            )

            # Handle address with or without button
            if "," not in addr_str:
                full_addr = f"{addr_str},{button}"
            else:
                full_addr = addr_str

            address = CCOAddress.from_string(full_addr)

            area = resolve_area_name(hass, device_config.get(CONF_AREA))
            _LOGGER.debug(
                "Creating switch %s with area=%s (config=%s)",
                device_config.get(CONF_NAME),
                area,
                device_config,
            )
            device = CCODevice(
                address=address,
                name=device_config.get(CONF_NAME, DEFAULT_SWITCH_NAME),
                entity_type=CCOEntityType.SWITCH,
                inverted=device_config.get(CONF_INVERTED, False),
                area=area,
            )

            entity = HomeworksCCOSwitch(
                coordinator=coordinator,
                controller_id=controller_id,
                device=device,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for switch device '%s': %s",
                device_config.get(CONF_NAME, "unknown"),
                err,
            )

    # Legacy CCOS format
    for cco_config in entry.options.get(CONF_CCOS, []):
        try:
            addr = normalize_address(cco_config[CONF_ADDR])
            relay = cco_config.get(CONF_RELAY_NUMBER, 1)
            parts = addr.strip("[]").split(":")

            address = CCOAddress(
                processor=int(parts[0]),
                link=int(parts[1]),
                address=int(parts[2]),
                button=relay,
            )

            device = CCODevice(
                address=address,
                name=cco_config.get(CONF_NAME, DEFAULT_SWITCH_NAME),
                entity_type=CCOEntityType.SWITCH,
                inverted=cco_config.get(CONF_INVERTED, False),
                area=resolve_area_name(hass, cco_config.get(CONF_AREA)),
            )

            entity = HomeworksCCOSwitch(
                coordinator=coordinator,
                controller_id=controller_id,
                device=device,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for legacy switch device '%s': %s",
                cco_config.get(CONF_NAME, "unknown"),
                err,
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

        # Set up entity attributes
        self._entity_name = device.name
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
    def name(self) -> str:
        """Return the name of the entity."""
        return self._entity_name

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on.

        State is read from the coordinator's central CCO state cache,
        which is populated by the KLS state engine.
        """
        return self.coordinator.get_cco_state(self._device.address)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch (close the CCO relay)."""
        _LOGGER.debug("Turning on CCO switch: %s", self._device.address)

        if self._device.inverted:
            await self.coordinator.async_cco_open(self._device.address)
        else:
            await self.coordinator.async_cco_close(self._device.address)
        # Optimistic state update is handled by coordinator

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch (open the CCO relay)."""
        _LOGGER.debug("Turning off CCO switch: %s", self._device.address)

        if self._device.inverted:
            await self.coordinator.async_cco_close(self._device.address)
        else:
            await self.coordinator.async_cco_open(self._device.address)
        # Optimistic state update is handled by coordinator

    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates when added to hass."""
        await super().async_added_to_hass()

        # Ensure the CCO device is registered with the coordinator
        self.coordinator.register_cco_device(self._device)

        # Request initial state
        await self.coordinator.async_request_keypad_led_states(
            self._device.address.to_kls_address()
        )

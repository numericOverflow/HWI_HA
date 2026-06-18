"""Support for Lutron Homeworks lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksData, resolve_area_name
from .const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTON_NUMBER,
    CONF_CCO_DEVICES,
    CONF_CONTROLLER_ID,
    CONF_DIMMERS,
    CONF_ENTITY_TYPE,
    CONF_INVERTED,
    CONF_RATE,
    CONF_RELAY_NUMBER,
    CCO_TYPE_LIGHT,
    DEFAULT_FADE_RATE,
    DEFAULT_LIGHT_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCOAddress, CCODevice, CCOEntityType, normalize_address

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks lights."""
    data: HomeworksData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[LightEntity] = []

    # Dimmable lights
    for dimmer in entry.options.get(CONF_DIMMERS, []):
        entity = HomeworksDimmableLight(
            coordinator=coordinator,
            controller_id=controller_id,
            addr=dimmer[CONF_ADDR],
            name=dimmer.get(CONF_NAME, DEFAULT_LIGHT_NAME),
            rate=dimmer.get(CONF_RATE, DEFAULT_FADE_RATE),
            area=resolve_area_name(hass, dimmer.get(CONF_AREA)),
        )
        entities.append(entity)

    # CCO-based on/off lights
    for device_config in entry.options.get(CONF_CCO_DEVICES, []):
        if device_config.get(CONF_ENTITY_TYPE) != CCO_TYPE_LIGHT:
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
                name=device_config.get(CONF_NAME, DEFAULT_LIGHT_NAME),
                entity_type=CCOEntityType.LIGHT,
                inverted=device_config.get(CONF_INVERTED, False),
                area=resolve_area_name(hass, device_config.get(CONF_AREA)),
            )

            entity = HomeworksCCOLight(
                coordinator=coordinator,
                controller_id=controller_id,
                device=device,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for CCO light device '%s': %s",
                device_config.get(CONF_NAME, "unknown"),
                err,
            )

    if entities:
        _LOGGER.debug("Adding %d light entities", len(entities))
        async_add_entities(entities)


class HomeworksDimmableLight(CoordinatorEntity[HomeworksCoordinator], LightEntity):
    """Homeworks Dimmable Light.

    Uses the DL (Dimmer Level) monitoring for state updates.
    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        addr: str,
        name: str,
        rate: float,
        area: str | None = None,
    ) -> None:
        """Create device with Addr, name, and rate."""
        super().__init__(coordinator)
        self._addr = normalize_address(addr)
        self._controller_id = controller_id
        self._rate = rate
        self._level = 0
        self._prev_level = 0

        self._entity_name = name
        self._attr_unique_id = f"homeworks.{controller_id}.light.{self._addr}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.{self._addr}.v2")},
            name=name,
            manufacturer="Lutron",
            model="HomeWorks Dimmer",
        )
        if area:
            device_info["suggested_area"] = area
        self._attr_device_info = device_info
        self._attr_extra_state_attributes = {"homeworks_address": self._addr}

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._entity_name

    @property
    def brightness(self) -> int:
        """Return the brightness (0-255)."""
        level = self.coordinator.get_dimmer_level(self._addr)
        return int((level * 255.0) / 100.0)

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        return self.coordinator.get_dimmer_level(self._addr) > 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        new_level = self.coordinator.get_dimmer_level(self._addr)
        if new_level != self._level:
            if new_level > 0:
                self._prev_level = new_level
            self._level = new_level
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        if ATTR_BRIGHTNESS in kwargs:
            new_level = int((kwargs[ATTR_BRIGHTNESS] * 100.0) / 255.0)
        elif self._prev_level == 0:
            new_level = 100
        else:
            new_level = self._prev_level

        await self.coordinator.async_fade_dim(
            self._addr, float(new_level), self._rate, 0
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self.coordinator.async_fade_dim(self._addr, 0.0, self._rate, 0)

    async def async_added_to_hass(self) -> None:
        """Register with coordinator when added to hass."""
        await super().async_added_to_hass()

        # Register dimmer for state tracking
        self.coordinator.register_dimmer(self._addr)

        # Request initial state
        await self.coordinator.async_request_dimmer_level(self._addr)


class HomeworksCCOLight(CoordinatorEntity[HomeworksCoordinator], LightEntity):
    """Homeworks CCO-based On/Off Light.

    Uses KLS state for feedback - no dimming capability.
    """

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        device: CCODevice,
    ) -> None:
        """Initialize the CCO light."""
        super().__init__(coordinator)
        self._device = device
        self._controller_id = controller_id

        self._entity_name = device.name
        self._attr_unique_id = f"homeworks.{controller_id}.ccolight.{device.unique_id}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.ccolight.{device.address}.v2")},
            name=device.name,
            manufacturer="Lutron",
            model="HomeWorks CCO Light",
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
    def is_on(self) -> bool:
        """Return True if the light is on."""
        return self.coordinator.get_cco_state(self._device.address)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light (close the CCO relay)."""
        _LOGGER.debug("Turning on CCO light: %s", self._device.address)

        if self._device.inverted:
            await self.coordinator.async_cco_open(self._device.address)
        else:
            await self.coordinator.async_cco_close(self._device.address)
        # Optimistic state update is handled by coordinator

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light (open the CCO relay)."""
        _LOGGER.debug("Turning off CCO light: %s", self._device.address)

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

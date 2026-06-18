"""Support for Lutron Homeworks CCO relays as climate devices (on/off only)."""

from __future__ import annotations

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import CONF_NAME, UnitOfTemperature
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
    CONF_RELAY_NUMBER,
    CCO_TYPE_CLIMATE,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import CCOAddress, CCODevice, CCOEntityType

_LOGGER = logging.getLogger(__name__)

DEFAULT_CLIMATE_NAME = "Homeworks Climate"


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks CCO relays as climate devices."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[HomeworksCCOClimate] = []

    # CCO devices with type=climate
    _LOGGER.debug(
        "Climate platform checking %d CCO devices",
        len(entry.options.get(CONF_CCO_DEVICES, [])),
    )
    for device_config in entry.options.get(CONF_CCO_DEVICES, []):
        entity_type = device_config.get(CONF_ENTITY_TYPE)
        _LOGGER.debug(
            "Climate platform checking device %s: entity_type=%s",
            device_config.get(CONF_NAME, "unknown"),
            entity_type,
        )
        if entity_type != CCO_TYPE_CLIMATE:
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

            device = CCODevice(
                address=address,
                name=device_config.get(CONF_NAME, DEFAULT_CLIMATE_NAME),
                entity_type=CCOEntityType.CLIMATE,
                inverted=device_config.get(CONF_INVERTED, False),
                area=resolve_area_name(hass, device_config.get(CONF_AREA)),
            )

            entity = HomeworksCCOClimate(
                coordinator=coordinator,
                controller_id=controller_id,
                device=device,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for climate device '%s': %s",
                device_config.get(CONF_NAME, "unknown"),
                err,
            )

    if entities:
        _LOGGER.debug("Adding %d CCO climate entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No CCO climate devices to add")


class HomeworksCCOClimate(CoordinatorEntity[HomeworksCoordinator], ClimateEntity):
    """Homeworks CCO Relay Climate.

    This is an on/off only climate device (no temperature control).
    State is derived from the central KLS state engine in the coordinator.
    """

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        device: CCODevice,
    ) -> None:
        """Initialize the CCO climate."""
        super().__init__(coordinator)
        self._device = device
        self._controller_id = controller_id

        # Set up entity attributes
        self._entity_name = device.name
        self._attr_unique_id = f"homeworks.{controller_id}.climate.{device.unique_id}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.climate.{device.address}.v2")},
            name=device.name,
            manufacturer="Lutron",
            model="HomeWorks CCO Climate",
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
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode (heat when on, off when off)."""
        is_on = self.coordinator.get_cco_state(self._device.address)
        return HVACMode.HEAT if is_on else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return None as this is an on/off only device with no temperature sensor."""
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode (heat = on, off = off)."""
        if hvac_mode == HVACMode.HEAT:
            await self.async_turn_on()
        else:
            await self.async_turn_off()

    async def async_turn_on(self) -> None:
        """Turn on the climate device (close the CCO relay)."""
        _LOGGER.debug("Turning on CCO climate: %s", self._device.address)

        if self._device.inverted:
            await self.coordinator.async_cco_open(self._device.address)
        else:
            await self.coordinator.async_cco_close(self._device.address)
        # Optimistic state update is handled by coordinator

    async def async_turn_off(self) -> None:
        """Turn off the climate device (open the CCO relay)."""
        _LOGGER.debug("Turning off CCO climate: %s", self._device.address)

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

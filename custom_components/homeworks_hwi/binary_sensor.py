"""Support for Lutron Homeworks binary sensors.

This module provides:
- Keypad LED binary sensors
- CCI (Contact Closure Input) binary sensors

CCI devices emulate keypads. When the physical key is:
- Turned to ON position: KBP then KBH (hold) = state is ON/closed
- Turned to OFF position: KBR (release) = state is OFF/open
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksData, HomeworksHWIConfigEntry, resolve_area_name
from .const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTONS,
    CONF_CCI_DEVICES,
    CONF_CONTROLLER_ID,
    CONF_DEVICE_CLASS,
    CONF_INPUT_NUMBER,
    CONF_KEYPADS,
    CONF_LED,
    CONF_NUMBER,
    DEFAULT_CCI_NAME,
    DOMAIN,
)
from .coordinator import HomeworksCoordinator
from .models import normalize_address

_LOGGER = logging.getLogger(__name__)

# Map string device classes to HA device classes for CCI
DEVICE_CLASS_MAP = {
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "garage_door": BinarySensorDeviceClass.GARAGE_DOOR,
    "opening": BinarySensorDeviceClass.OPENING,
    "lock": BinarySensorDeviceClass.LOCK,
    "motion": BinarySensorDeviceClass.MOTION,
    "occupancy": BinarySensorDeviceClass.OCCUPANCY,
    "presence": BinarySensorDeviceClass.PRESENCE,
    "safety": BinarySensorDeviceClass.SAFETY,
    "plug": BinarySensorDeviceClass.PLUG,
    "power": BinarySensorDeviceClass.POWER,
    "running": BinarySensorDeviceClass.RUNNING,
    "problem": BinarySensorDeviceClass.PROBLEM,
    "connectivity": BinarySensorDeviceClass.CONNECTIVITY,
    None: None,
    "": None,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks binary sensors."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[BinarySensorEntity] = []

    # Keypad LED binary sensors
    for keypad in entry.options.get(CONF_KEYPADS, []):
        keypad_addr = normalize_address(keypad[CONF_ADDR])
        keypad_name = keypad.get(CONF_NAME, "Keypad")

        # Register keypad address for KLS polling
        coordinator.register_kls_poll_address(keypad_addr)

        for button in keypad.get(CONF_BUTTONS, []):
            if not button.get(CONF_LED, False):
                continue

            entity = HomeworksLEDBinarySensor(
                coordinator=coordinator,
                controller_id=controller_id,
                keypad_addr=keypad_addr,
                keypad_name=keypad_name,
                button_name=button.get(CONF_NAME, "Button"),
                led_number=button[CONF_NUMBER],
            )
            entities.append(entity)

    # CCI (Contact Closure Input) binary sensors
    _LOGGER.debug(
        "Binary sensor platform checking %d CCI devices",
        len(entry.options.get(CONF_CCI_DEVICES, [])),
    )

    for device_config in entry.options.get(CONF_CCI_DEVICES, []):
        try:
            addr_str = device_config[CONF_ADDR]
            input_number = device_config.get(CONF_INPUT_NUMBER, 1)
            name = device_config.get(CONF_NAME, DEFAULT_CCI_NAME)
            device_class_str = device_config.get(CONF_DEVICE_CLASS, None)
            area = resolve_area_name(hass, device_config.get(CONF_AREA))

            # Map string device class to HA device class
            device_class = DEVICE_CLASS_MAP.get(device_class_str)

            entity = HomeworksCCIBinarySensor(
                coordinator=coordinator,
                controller_id=controller_id,
                address=addr_str,
                input_number=input_number,
                name=name,
                device_class=device_class,
                area=area,
            )
            entities.append(entity)

        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for CCI binary sensor '%s': %s",
                device_config.get(CONF_NAME, "unknown"),
                err,
            )

    if entities:
        _LOGGER.debug("Adding %d binary sensor entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No binary sensors to add")


class HomeworksLEDBinarySensor(
    CoordinatorEntity[HomeworksCoordinator], BinarySensorEntity
):
    """Homeworks Binary Sensor for keypad LED state."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        keypad_addr: str,
        keypad_name: str,
        button_name: str,
        led_number: int,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._controller_id = controller_id
        self._keypad_addr = keypad_addr
        self._led_number = led_number

        self._attr_unique_id = (
            f"homeworks.{controller_id}.led.{keypad_addr}.{led_number}.v2"
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
            "led_number": led_number,
        }

    @property
    def is_on(self) -> bool | None:
        """Return True if the LED is on.

        LED states: 0=Off, 1=On, 2=Flash1, 3=Flash2
        We treat Flash as On.
        """
        led_states = self.coordinator.get_keypad_led_states(self._keypad_addr)
        if not led_states or self._led_number > len(led_states):
            return None

        # LED number is 1-indexed
        led_value = led_states[self._led_number - 1]
        return led_value > 0  # 1, 2, or 3 are all "on"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register for updates when added to hass."""
        await super().async_added_to_hass()

        # Request initial state
        await self.coordinator.async_request_keypad_led_states(self._keypad_addr)


class HomeworksCCIBinarySensor(
    CoordinatorEntity[HomeworksCoordinator], BinarySensorEntity
):
    """Homeworks CCI Binary Sensor.

    Represents a physical input (key switch, contact closure) that reports
    its state when changed. Used to trigger Home Assistant automations.
    """

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        address: str,
        input_number: int,
        name: str,
        device_class: BinarySensorDeviceClass | None,
        area: str | None = None,
    ) -> None:
        """Initialize the CCI binary sensor."""
        super().__init__(coordinator)
        self._address = normalize_address(address)
        self._input_number = input_number
        self._controller_id = controller_id
        self._sensor_name = name
        self._unregister_callback: callable[[], None] | None = None

        # Set up entity attributes
        self._entity_name = name
        addr_clean = self._address.replace(":", "_").strip("[]")
        self._attr_unique_id = f"homeworks.{controller_id}.cci.{addr_clean}_{input_number}.v2"
        self._attr_device_class = device_class
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.cci.{self._address}_{input_number}.v2")},
            name=name,
            manufacturer="Lutron",
            model="HomeWorks CCI Input",
        )
        if area:
            device_info["suggested_area"] = area
        self._attr_device_info = device_info
        self._attr_extra_state_attributes = {
            "homeworks_address": self._address,
            "input_number": input_number,
        }

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._entity_name

    @property
    def is_on(self) -> bool:
        """Return True if the input is closed/on."""
        return self.coordinator.get_cci_state(self._address, self._input_number)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @callback
    def _handle_cci_state_change(self, state: bool) -> None:
        """Handle direct CCI state change callback."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates when added to hass."""
        await super().async_added_to_hass()

        # Register the CCI device with the coordinator
        self.coordinator.register_cci_device(
            self._address,
            self._input_number,
            self,
        )

        # Register for direct state change callbacks
        self._unregister_callback = self.coordinator.register_cci_callback(
            self._address,
            self._input_number,
            self._handle_cci_state_change,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister when removed from hass."""
        await super().async_will_remove_from_hass()

        if self._unregister_callback:
            self._unregister_callback()

        self.coordinator.unregister_cci_device(self._address, self._input_number)


# Keep old class name for backwards compatibility
HomeworksBinarySensor = HomeworksLEDBinarySensor

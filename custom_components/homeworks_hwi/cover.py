"""Support for Lutron Homeworks covers (CCO-based or RPM motor-based)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksHWIConfigEntry, create_cco_entities_for_type, resolve_area_name
from .const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_CONTROLLER_ID,
    CONF_QED_COVERS,
    CONF_RPM_COVERS,
    CCO_TYPE_COVER,
    DEFAULT_COVER_NAME,
    DEFAULT_QED_COVER_NAME,
    DEFAULT_RPM_COVER_NAME,
    DOMAIN,
    RPM_MOTOR_DOWN,
    RPM_MOTOR_STOP,
    RPM_MOTOR_UP,
)
from .coordinator import HomeworksCoordinator
from .models import CCODevice, CCOEntityType, normalize_address

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks covers."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]
    entities: list[HomeworksCCOCover | HomeworksRPMCover | HomeworksQEDCover] = []

    # New-style CCO devices with type=cover
    cco_covers = create_cco_entities_for_type(
        hass, entry, coordinator, controller_id,
        CCO_TYPE_COVER, CCOEntityType.COVER, HomeworksCCOCover, DEFAULT_COVER_NAME,
    )
    entities.extend(cco_covers)

    # RPM motor covers
    for rpm_cover_config in entry.options.get(CONF_RPM_COVERS, []):
        try:
            addr = normalize_address(rpm_cover_config[CONF_ADDR])
            entity = HomeworksRPMCover(
                coordinator=coordinator,
                controller_id=controller_id,
                address=addr,
                name=rpm_cover_config.get(CONF_NAME, DEFAULT_RPM_COVER_NAME),
                area=resolve_area_name(hass, rpm_cover_config.get(CONF_AREA)),
            )
            entities.append(entity)
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for RPM cover '%s': %s",
                rpm_cover_config.get(CONF_NAME, "unknown"),
                err,
            )

    # QED Sivoia shades (position-trackable)
    for qed_cover_config in entry.options.get(CONF_QED_COVERS, []):
        try:
            addr = normalize_address(qed_cover_config[CONF_ADDR])
            entity = HomeworksQEDCover(
                coordinator=coordinator,
                controller_id=controller_id,
                address=addr,
                name=qed_cover_config.get(CONF_NAME, DEFAULT_QED_COVER_NAME),
                area=resolve_area_name(hass, qed_cover_config.get(CONF_AREA)),
            )
            entities.append(entity)
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for QED cover '%s': %s",
                qed_cover_config.get(CONF_NAME, "unknown"),
                err,
            )

    if entities:
        _LOGGER.debug("Adding %d cover entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No covers to add")


class HomeworksCCOCover(CoordinatorEntity[HomeworksCoordinator], CoverEntity):
    """Homeworks CCO-based Cover.

    For CCO-based covers, we can only determine open/close state from KLS.
    Position tracking is not available without additional hardware feedback.
    """

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        device: CCODevice,
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._device = device
        self._controller_id = controller_id
        self._is_opening = False
        self._is_closing = False

        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_unique_id = f"homeworks.{controller_id}.cover.{device.unique_id}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.cover.{device.address}.v2")},
            name=device.name,
            manufacturer="Lutron",
            model="HomeWorks Cover",
        )
        if device.area:
            device_info["suggested_area"] = device.area
        self._attr_device_info = device_info
        self._attr_extra_state_attributes = {
            "homeworks_address": str(device.address),
        }

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed.

        For CCO-based covers, we derive this from the KLS state.
        When the CCO state is ON (relay closed), the cover is closed.
        Inversion is already handled by the coordinator's state engine.
        """
        return self.coordinator.get_cco_state(self._device.address)

    @property
    def is_opening(self) -> bool:
        """Return True if the cover is opening."""
        return self._is_opening

    @property
    def is_closing(self) -> bool:
        """Return True if the cover is closing."""
        return self._is_closing

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Clear movement flags when state updates
        self._is_opening = False
        self._is_closing = False
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug("Opening cover: %s", self._device.address)
        self._is_opening = True
        self._is_closing = False
        self.async_write_ha_state()
        # Open = logical OFF state
        await self.coordinator.async_cco_turn_off(self._device)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug("Closing cover: %s", self._device.address)
        self._is_closing = True
        self._is_opening = False
        self.async_write_ha_state()
        # Close = logical ON state
        await self.coordinator.async_cco_turn_on(self._device)

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


# Attribute key for storing last known position
ATTR_LAST_KNOWN_POSITION = "last_known_position"


class HomeworksRPMCover(CoordinatorEntity[HomeworksCoordinator], CoverEntity, RestoreEntity):
    """Homeworks RPM motor-based Cover.

    For HW-RPM-4M-230 and similar motor modules.
    Uses FADEDIM commands with specific values:
    - Up: 16
    - Stop: 0
    - Down: 35

    State tracking uses RDL (Request Dimmer Level) to get the last commanded value:
    - Level 16 = last command was "up" → cover is open/opening
    - Level 35 = last command was "down" → cover is closed/closing
    - Level 0 = last command was "stop" → use last known position

    The last known position is persisted across HA restarts using RestoreEntity.
    """

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        address: str,
        name: str,
        area: str | None = None,
    ) -> None:
        """Initialize the RPM cover."""
        super().__init__(coordinator)
        self._address = address
        self._controller_id = controller_id
        # Last known position: True=closed, False=open, None=unknown
        self._last_known_closed: bool | None = None

        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_unique_id = f"homeworks.{controller_id}.rpm_cover.{address}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.rpm_cover.{address}.v2")},
            name=name,
            manufacturer="Lutron",
            model="HomeWorks RPM Motor Cover",
        )
        if area:
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        level = self.coordinator.get_dimmer_level(self._address)
        level_name = {
            RPM_MOTOR_UP: "up",
            RPM_MOTOR_DOWN: "down",
            RPM_MOTOR_STOP: "stopped",
        }.get(level, f"unknown ({level})")
        return {
            "homeworks_address": self._address,
            "motor_level": level,
            "motor_state": level_name,
            ATTR_LAST_KNOWN_POSITION: (
                "closed" if self._last_known_closed is True
                else "open" if self._last_known_closed is False
                else "unknown"
            ),
        }

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed.

        Uses RDL feedback to determine state:
        - Level 35 (down command) = closed
        - Level 16 (up command) = open
        - Level 0 (stop command) = use last known position
        """
        level = self.coordinator.get_dimmer_level(self._address)
        if level == RPM_MOTOR_DOWN:
            # Update last known position
            self._last_known_closed = True
            return True
        elif level == RPM_MOTOR_UP:
            # Update last known position
            self._last_known_closed = False
            return False
        else:
            # Stopped or unknown - use last known position
            return self._last_known_closed

    @property
    def is_opening(self) -> bool:
        """Return True if the cover is opening."""
        level = self.coordinator.get_dimmer_level(self._address)
        return level == RPM_MOTOR_UP

    @property
    def is_closing(self) -> bool:
        """Return True if the cover is closing."""
        level = self.coordinator.get_dimmer_level(self._address)
        return level == RPM_MOTOR_DOWN

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update last known position based on current level
        level = self.coordinator.get_dimmer_level(self._address)
        if level == RPM_MOTOR_DOWN:
            self._last_known_closed = True
        elif level == RPM_MOTOR_UP:
            self._last_known_closed = False
        # If stopped (0), keep the previous last_known_closed value
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (raise)."""
        _LOGGER.debug("Opening RPM cover: %s", self._address)
        self._last_known_closed = False  # Optimistically update
        await self.coordinator.async_motor_cover_up(self._address)
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (lower)."""
        _LOGGER.debug("Closing RPM cover: %s", self._address)
        self._last_known_closed = True  # Optimistically update
        await self.coordinator.async_motor_cover_down(self._address)
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("Stopping RPM cover: %s", self._address)
        # Don't change last_known_closed - keep the last known position
        await self.coordinator.async_motor_cover_stop(self._address)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register with coordinator when added to hass."""
        await super().async_added_to_hass()

        # Restore last known position from previous state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.attributes.get(ATTR_LAST_KNOWN_POSITION) == "closed":
                self._last_known_closed = True
                _LOGGER.debug("Restored %s last position: closed", self._address)
            elif last_state.attributes.get(ATTR_LAST_KNOWN_POSITION) == "open":
                self._last_known_closed = False
                _LOGGER.debug("Restored %s last position: open", self._address)

        # Register as a dimmer to receive DL (dimmer level) updates
        self.coordinator.register_dimmer(self._address)

        # Request initial state from controller
        await self.coordinator.async_request_dimmer_level(self._address)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister dimmer address when removed from hass."""
        self.coordinator.unregister_dimmer(self._address)
        await super().async_will_remove_from_hass()


class HomeworksQEDCover(CoordinatorEntity[HomeworksCoordinator], CoverEntity):
    """Homeworks Sivoia QED shade with continuous position feedback.

    QED shades behave like dimmers: FADEDIM sets position (0-100),
    RDL requests position, and DL reports current position.
    Unlike RPM motor covers, QED shades provide exact position tracking.
    """

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        address: str,
        name: str,
        area: str | None = None,
    ) -> None:
        """Initialize the QED cover."""
        super().__init__(coordinator)
        self._address = address
        self._controller_id = controller_id
        self._is_opening = False
        self._is_closing = False
        self._received_initial_state = False

        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_unique_id = f"homeworks.{controller_id}.qed_cover.{address}.v2"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.qed_cover.{address}.v2")},
            name=name,
            manufacturer="Lutron",
            model="Sivoia QED Shade",
        )
        if area:
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "homeworks_address": self._address,
        }

    @property
    def current_cover_position(self) -> int:
        """Return current position of cover (0=closed, 100=open)."""
        return self.coordinator.get_dimmer_level(self._address)

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed."""
        if not self._received_initial_state:
            return None
        return self.coordinator.get_dimmer_level(self._address) < 1

    @property
    def is_opening(self) -> bool:
        """Return True if the cover is opening."""
        return self._is_opening

    @property
    def is_closing(self) -> bool:
        """Return True if the cover is closing."""
        return self._is_closing

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        Clears optimistic movement flags when a real DL update arrives.
        """
        self._received_initial_state = True
        self._is_opening = False
        self._is_closing = False
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self._is_opening = True
        self._is_closing = False
        self.async_write_ha_state()
        await self.coordinator.async_fade_dim(self._address, 100.0, 0.0, 0.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._is_closing = True
        self._is_opening = False
        self.async_write_ha_state()
        await self.coordinator.async_fade_dim(self._address, 0.0, 0.0, 0.0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        position = kwargs[ATTR_POSITION]
        current = self.coordinator.get_dimmer_level(self._address)
        if position > current:
            self._is_opening = True
            self._is_closing = False
        elif position < current:
            self._is_closing = True
            self._is_opening = False
        self.async_write_ha_state()
        await self.coordinator.async_fade_dim(self._address, float(position), 0.0, 0.0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover mid-travel."""
        self._is_opening = False
        self._is_closing = False
        await self.coordinator.async_stop_dim(self._address)
        # Request updated position after stop
        await self.coordinator.async_request_dimmer_level(self._address)

    async def async_added_to_hass(self) -> None:
        """Register with coordinator when added to hass."""
        await super().async_added_to_hass()

        # Register as a dimmer to receive DL updates
        self.coordinator.register_dimmer(self._address)

        # Request initial state from controller
        await self.coordinator.async_request_dimmer_level(self._address)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister dimmer address when removed from hass."""
        self.coordinator.unregister_dimmer(self._address)
        await super().async_will_remove_from_hass()

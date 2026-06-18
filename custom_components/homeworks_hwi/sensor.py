"""Support for Lutron Homeworks health and diagnostic sensors."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeworksData, HomeworksHWIConfigEntry
from .const import CONF_CONTROLLER_ID, DOMAIN
from .coordinator import HomeworksCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homeworks health sensors."""
    data = entry.runtime_data
    coordinator = data.coordinator
    controller_id = entry.options[CONF_CONTROLLER_ID]

    entities = [
        HomeworksConnectionSensor(coordinator, controller_id),
        HomeworksLastKLSTimeSensor(coordinator, controller_id),
        HomeworksReconnectCountSensor(coordinator, controller_id),
        HomeworksPollFailureCountSensor(coordinator, controller_id),
        HomeworksParseErrorCountSensor(coordinator, controller_id),
    ]

    async_add_entities(entities)


class HomeworksHealthSensor(CoordinatorEntity[HomeworksCoordinator], SensorEntity):
    """Base class for Homeworks health sensors."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False  # Disabled by default
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        sensor_type: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._controller_id = controller_id
        self._attr_unique_id = f"homeworks.{controller_id}.health.{sensor_type}.v2"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}.controller.v2")},
            name=f"Homeworks Controller ({controller_id})",
            manufacturer="Lutron",
            model="HomeWorks Interactive",
        )


class HomeworksConnectionSensor(HomeworksHealthSensor):
    """Sensor showing connection status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["connected", "disconnected"]
    _attr_entity_registry_enabled_default = True  # This one is enabled by default
    _attr_translation_key = "connection"

    def __init__(self, coordinator: HomeworksCoordinator, controller_id: str) -> None:
        """Initialize the connection sensor."""
        super().__init__(coordinator, controller_id, "connection", "Connection Status")

    @property
    def native_value(self) -> str:
        """Return the connection status."""
        return "connected" if self.coordinator.connected else "disconnected"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class HomeworksLastKLSTimeSensor(HomeworksHealthSensor):
    """Sensor showing last KLS message timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_kls_time"

    def __init__(self, coordinator: HomeworksCoordinator, controller_id: str) -> None:
        """Initialize the last KLS time sensor."""
        super().__init__(coordinator, controller_id, "last_kls_time", "Last KLS Update")

    @property
    def native_value(self) -> datetime | None:
        """Return the last KLS timestamp."""
        return self.coordinator.health.last_kls_time

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class HomeworksReconnectCountSensor(HomeworksHealthSensor):
    """Sensor showing reconnection count."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "reconnect_count"

    def __init__(self, coordinator: HomeworksCoordinator, controller_id: str) -> None:
        """Initialize the reconnect count sensor."""
        super().__init__(
            coordinator, controller_id, "reconnect_count", "Reconnect Count"
        )

    @property
    def native_value(self) -> int:
        """Return the reconnect count."""
        return self.coordinator.health.reconnect_count

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class HomeworksPollFailureCountSensor(HomeworksHealthSensor):
    """Sensor showing poll failure count."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "poll_failure_count"

    def __init__(self, coordinator: HomeworksCoordinator, controller_id: str) -> None:
        """Initialize the poll failure count sensor."""
        super().__init__(
            coordinator, controller_id, "poll_failure_count", "Poll Failures"
        )

    @property
    def native_value(self) -> int:
        """Return the poll failure count."""
        return self.coordinator.health.poll_failure_count

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class HomeworksParseErrorCountSensor(HomeworksHealthSensor):
    """Sensor showing parse error count."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "parse_error_count"

    def __init__(self, coordinator: HomeworksCoordinator, controller_id: str) -> None:
        """Initialize the parse error count sensor."""
        super().__init__(
            coordinator, controller_id, "parse_error_count", "Parse Errors"
        )

    @property
    def native_value(self) -> int:
        """Return the parse error count."""
        return self.coordinator.health.parse_error_count

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

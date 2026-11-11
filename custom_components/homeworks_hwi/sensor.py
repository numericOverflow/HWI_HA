"""Support for Lutron Homeworks health and diagnostic sensors."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import (
    HomeworksHWIConfigEntry,
    controller_device_info,
)
from .clock_sync import ClockSyncManager
from .const import (
    CLOCK_SYNC_STATUSES,
    CONF_CONTROLLER_ID,
)
from .coordinator import HomeworksCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeworksHWIConfigEntry,
    async_add_entities: AddEntitiesCallback,
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
        HomeworksClockSyncStatusSensor(data.clock_sync, controller_id),
        HomeworksClockOffsetSensor(data.clock_sync, controller_id),
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
        self._attr_device_info = controller_device_info(controller_id)


class HomeworksClockSensor(RestoreSensor):
    """Base class for the controller clock sensors.

    Values come from the ClockSyncManager and survive a restart.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_should_poll = False

    def __init__(
        self, manager: ClockSyncManager, controller_id: str, sensor_type: str
    ) -> None:
        """Initialize the sensor."""
        self._manager = manager
        self._attr_unique_id = f"homeworks.{controller_id}.clock.{sensor_type}"
        self._attr_device_info = controller_device_info(controller_id)

    async def async_added_to_hass(self) -> None:
        """Restore the last value and follow the manager."""
        await super().async_added_to_hass()
        await self._async_restore()
        self.async_on_remove(
            self._manager.async_add_listener(self.async_write_ha_state)
        )

    async def _async_restore(self) -> None:
        """Pass the restored value to the manager."""
        raise NotImplementedError


class HomeworksClockSyncStatusSensor(HomeworksClockSensor):
    """Sensor showing the result of the last controller clock sync attempt."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CLOCK_SYNC_STATUSES)  # noqa: RUF012 - HA _attr_ pattern
    _attr_translation_key = "last_clock_sync"

    def __init__(self, manager: ClockSyncManager, controller_id: str) -> None:
        """Initialize the clock sync status sensor."""
        super().__init__(manager, controller_id, "last_sync")

    @property
    def native_value(self) -> str:
        """Return the status of the last sync attempt."""
        return self._manager.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the details of the last sync attempt."""
        return self._manager.status_attributes

    async def _async_restore(self) -> None:
        """Pass the restored status and attributes to the manager."""
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._manager.restore_status(last_state.state, last_state.attributes)


class HomeworksClockOffsetSensor(HomeworksClockSensor):
    """Sensor showing the processor clock offset from HA (positive is ahead)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0
    _attr_translation_key = "processor_clock_offset"

    def __init__(self, manager: ClockSyncManager, controller_id: str) -> None:
        """Initialize the clock offset sensor."""
        super().__init__(manager, controller_id, "offset")

    @property
    def native_value(self) -> float | None:
        """Return the pre-sync drift on sync, or the measured offset on query."""
        return self._manager.last_offset

    async def _async_restore(self) -> None:
        """Pass the restored offset to the manager."""
        last_data = await self.async_get_last_sensor_data()
        if last_data is not None and isinstance(last_data.native_value, (int, float)):
            self._manager.restore_offset(float(last_data.native_value))


class HomeworksConnectionSensor(HomeworksHealthSensor):
    """Sensor showing connection status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["connected", "disconnected"]  # noqa: RUF012 - HA _attr_ pattern
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

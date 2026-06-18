"""Support for Lutron Homeworks Series 4 and 8 systems.

HA 2026.1 compliant:
- Credentials (host, port, username, password) in entry.data
- Non-secrets (devices, settings) in entry.options
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from .client import HomeworksClientConfig
from .const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTON_NUMBER,
    CONF_CCI_DEVICES,
    CONF_CCO_DEVICES,
    CONF_CCOS,
    CONF_CONTROLLER_ID,
    CONF_COVERS,
    CONF_DIMMERS,
    CONF_ENTITY_TYPE,
    CONF_INPUT_NUMBER,
    CONF_INVERTED,
    CONF_KLS_POLL_INTERVAL,
    CONF_KLS_WINDOW_OFFSET,
    CONF_LOCKS,
    CONF_RELAY_NUMBER,
    CONF_RPM_COVERS,
    CCO_TYPE_CLIMATE,
    CCO_TYPE_COVER,
    CCO_TYPE_FAN,
    CCO_TYPE_LIGHT,
    CCO_TYPE_LOCK,
    CCO_TYPE_SWITCH,
    DEFAULT_KLS_POLL_INTERVAL,
    DEFAULT_KLS_WINDOW_OFFSET,
    DOMAIN,
    MAX_COMMAND_DELAY_MS,
)
from .coordinator import HomeworksCoordinator
from .models import CCOAddress, CCODevice, CCOEntityType, normalize_address

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.FAN,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONF_COMMAND = "command"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONTROLLER_ID): str,
        vol.Required(CONF_COMMAND): vol.All(cv.ensure_list, [str]),
    }
)


@dataclass
class HomeworksData:
    """Container for config entry data."""

    coordinator: HomeworksCoordinator
    controller_id: str


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in a string.

    - Strips leading/trailing whitespace
    - Replaces multiple consecutive spaces with single space
    - Replaces various unicode whitespace characters with regular space
    """
    import re
    import unicodedata

    # Normalize unicode (e.g., convert non-breaking spaces to regular spaces)
    text = unicodedata.normalize("NFKC", text)
    # Replace any whitespace character (including \xa0 non-breaking space) with space
    text = re.sub(r"[\s\xa0]+", " ", text)
    # Strip leading/trailing
    return text.strip()


def resolve_area_name(hass: HomeAssistant, area_name: str | None) -> str | None:
    """Resolve an area name to its ID, matching flexibly.

    Tries multiple matching strategies:
    1. Exact name match (case-insensitive, whitespace-normalized)
    2. Area ID match (case-insensitive)
    3. Underscore-to-space conversion (e.g., "living_room" matches "Living Room")
    4. Space-to-underscore conversion (e.g., "Living Room" matches area ID "living_room")

    Args:
        hass: Home Assistant instance
        area_name: The area name from CSV (e.g., "Living Room" or "living_room")

    Returns:
        The area ID if found, or the original name if not found.
        If area doesn't exist, suggested_area will create it with the given name.
    """
    if not area_name:
        return None

    area_registry = ar.async_get(hass)

    # Normalize the input area name
    area_name_clean = _normalize_whitespace(area_name)
    if not area_name_clean:
        return None

    area_name_lower = area_name_clean.lower()

    # Also try with underscores replaced by spaces and vice versa
    area_name_spaces = area_name_lower.replace("_", " ")
    area_name_underscores = area_name_lower.replace(" ", "_")

    # Log the available areas for debugging
    available_areas = [(a.id, a.name) for a in area_registry.areas.values()]
    _LOGGER.debug(
        "resolve_area_name: input='%s' (clean='%s'), available areas: %s",
        area_name,
        area_name_clean,
        available_areas,
    )

    for area in area_registry.areas.values():
        # Normalize area name from registry too
        area_name_normalized = _normalize_whitespace(area.name).lower()
        area_id_check = area.id.lower()

        # Match against area name (case-insensitive, whitespace-normalized)
        if area_name_normalized == area_name_lower:
            _LOGGER.debug(
                "Resolved area '%s' to ID '%s' (exact name match)",
                area_name,
                area.id,
            )
            return area.id

        # Match against area ID (case-insensitive)
        if area_id_check == area_name_lower:
            _LOGGER.debug(
                "Resolved area '%s' to ID '%s' (ID match)",
                area_name,
                area.id,
            )
            return area.id

        # Match with underscores converted to spaces (e.g., "living_room" -> "living room")
        if area_name_normalized == area_name_spaces:
            _LOGGER.debug(
                "Resolved area '%s' to ID '%s' (underscore-to-space match)",
                area_name,
                area.id,
            )
            return area.id

        # Match with spaces converted to underscores (e.g., "Living Room" -> "living_room")
        if area_id_check == area_name_underscores:
            _LOGGER.debug(
                "Resolved area '%s' to ID '%s' (space-to-underscore match)",
                area_name,
                area.id,
            )
            return area.id

    # No match found - log warning since user expects all areas to exist
    _LOGGER.warning(
        "Area '%s' (normalized: '%s') NOT FOUND in registry. "
        "Available areas: %s. HA will create a new area.",
        area_name,
        area_name_clean,
        [(a.id, a.name) for a in area_registry.areas.values()],
    )

    # If it looks like a slug (has underscores, no spaces), convert to Title Case
    if "_" in area_name_clean and " " not in area_name_clean:
        friendly_name = area_name_clean.replace("_", " ").title()
        return friendly_name

    return area_name_clean


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Lutron Homeworks."""

    async def async_call_service(service_call: ServiceCall) -> None:
        """Call the service."""
        await async_send_command(hass, service_call.data)

    hass.services.async_register(
        DOMAIN,
        "send_command",
        async_call_service,
        schema=SERVICE_SEND_COMMAND_SCHEMA,
    )


async def async_send_command(hass: HomeAssistant, data: Mapping[str, Any]) -> None:
    """Send command to a controller."""

    def get_controller_ids() -> list[str]:
        """Get controller IDs."""
        return [hw_data.controller_id for hw_data in hass.data[DOMAIN].values()]

    def get_homeworks_data(controller_id: str) -> HomeworksData | None:
        """Get homeworks data for controller ID."""
        for hw_data in hass.data[DOMAIN].values():
            if hw_data.controller_id == controller_id:
                return hw_data
        return None

    homeworks_data = get_homeworks_data(data[CONF_CONTROLLER_ID])
    if not homeworks_data:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_controller_id",
            translation_placeholders={
                "controller_id": data[CONF_CONTROLLER_ID],
                "controller_ids": ",".join(get_controller_ids()),
            },
        )

    commands = data[CONF_COMMAND]
    _LOGGER.debug("Send commands: %s", commands)

    client = homeworks_data.coordinator.client
    if not client:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_connected",
        )

    for command in commands:
        if command.lower().startswith("delay"):
            try:
                delay = min(int(command.partition(" ")[2]), MAX_COMMAND_DELAY_MS)
            except (ValueError, IndexError):
                _LOGGER.warning("Invalid delay command ignored: %s", command)
                continue
            _LOGGER.debug("Sleeping for %s ms", delay)
            await asyncio.sleep(delay / 1000)
        else:
            _LOGGER.debug("Sending command '%s'", command)
            await client.send_command(command)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Start Homeworks controller."""
    async_setup_services(hass)
    return True


def _cleanup_old_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove old entities with legacy unique_id format.

    This cleans up entities that were created with the old unique_id format
    before the v2 suffix was added. Those entities may have cached doubled
    names in the entity registry.
    """
    entity_registry = async_get_entity_registry(hass)
    entities_to_remove = []

    for entity_entry in list(entity_registry.entities.values()):
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        if entity_entry.platform != DOMAIN:
            continue

        # Remove ALL entities that don't end with .v2
        # This ensures we catch everything regardless of unique_id pattern
        unique_id = entity_entry.unique_id
        if unique_id and not unique_id.endswith(".v2"):
            entities_to_remove.append(entity_entry.entity_id)
            _LOGGER.debug("Marking for removal: %s (unique_id: %s)",
                         entity_entry.entity_id, unique_id)

    for entity_id in entities_to_remove:
        _LOGGER.info("Removing old entity with legacy unique_id: %s", entity_id)
        entity_registry.async_remove(entity_id)

    if entities_to_remove:
        _LOGGER.info("Cleaned up %d old entities", len(entities_to_remove))


def _cleanup_devices_without_areas(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove devices that don't have areas assigned.

    This ensures that devices will be recreated fresh with the correct
    suggested_area from the config. This is necessary because HA only
    applies suggested_area when a device is first created.
    """
    device_registry = dr.async_get(hass)
    devices_to_remove = []

    for device_entry in list(device_registry.devices.values()):
        # Only process devices for this config entry
        if entry.entry_id not in device_entry.config_entries:
            continue

        # Check if it's one of our domain's devices
        is_our_device = any(
            identifier[0] == DOMAIN for identifier in device_entry.identifiers
        )
        if not is_our_device:
            continue

        # Remove devices without area assignment
        if device_entry.area_id is None:
            devices_to_remove.append(device_entry.id)
            _LOGGER.debug(
                "Marking device for removal (no area): %s (identifiers: %s)",
                device_entry.name,
                device_entry.identifiers,
            )

    for device_id in devices_to_remove:
        _LOGGER.info("Removing device without area: %s", device_id)
        device_registry.async_remove_device(device_id)

    if devices_to_remove:
        _LOGGER.info(
            "Cleaned up %d devices without areas (will be recreated with areas)",
            len(devices_to_remove),
        )


def _cleanup_orphaned_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove devices that have no entities after platform setup.

    After a config entry reload (e.g., after removing a device via options flow),
    devices whose entities were not recreated become orphaned. This removes them.
    """
    device_registry = dr.async_get(hass)
    entity_registry = async_get_entity_registry(hass)

    for device_entry in list(device_registry.devices.values()):
        if entry.entry_id not in device_entry.config_entries:
            continue

        is_our_device = any(
            identifier[0] == DOMAIN for identifier in device_entry.identifiers
        )
        if not is_our_device:
            continue

        # Check if any entities reference this device
        has_entities = any(
            entity.device_id == device_entry.id
            for entity in entity_registry.entities.values()
        )
        if not has_entities:
            _LOGGER.info(
                "Removing orphaned device: %s (%s)",
                device_entry.name,
                device_entry.identifiers,
            )
            device_registry.async_remove_device(device_entry.id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homeworks from a config entry.

    Credentials are read from entry.data (secrets).
    Devices and settings are read from entry.options (non-secrets).
    """
    # Clean up old entities with legacy unique_id format
    _cleanup_old_entities(hass, entry)

    # Clean up devices without areas so they get recreated with correct areas
    _cleanup_devices_without_areas(hass, entry)

    hass.data.setdefault(DOMAIN, {})

    # Read credentials from entry.data
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)

    # Read non-secrets from entry.options
    options = entry.options
    controller_id = options.get(CONF_CONTROLLER_ID, slugify(entry.title))

    # Build client config
    client_config = HomeworksClientConfig(
        host=host,
        port=port,
        username=username,
        password=password,
    )

    # Get poll interval and window offset from options
    kls_poll_interval = options.get(CONF_KLS_POLL_INTERVAL, DEFAULT_KLS_POLL_INTERVAL)
    kls_window_offset = options.get(CONF_KLS_WINDOW_OFFSET, DEFAULT_KLS_WINDOW_OFFSET)

    # Create coordinator
    coordinator = HomeworksCoordinator(
        hass=hass,
        config=client_config,
        controller_id=controller_id,
        kls_poll_interval=timedelta(seconds=kls_poll_interval),
        kls_window_offset=kls_window_offset,
    )

    # Register CCO devices from options
    _register_cco_devices_from_options(coordinator, options)

    # Register dimmers
    for dimmer in options.get(CONF_DIMMERS, []):
        coordinator.register_dimmer(dimmer[CONF_ADDR])

    # Connect and start coordinator
    try:
        if not await coordinator.async_setup():
            raise ConfigEntryNotReady("Failed to connect to Homeworks controller")
    except Exception as err:
        _LOGGER.error("Failed to setup Homeworks: %s", err)
        # Check if this is an auth failure
        if "auth" in str(err).lower() or "credential" in str(err).lower():
            raise ConfigEntryAuthFailed("Authentication failed") from err
        raise ConfigEntryNotReady(f"Connection failed: {err}") from err

    # Store data
    hass.data[DOMAIN][entry.entry_id] = HomeworksData(
        coordinator=coordinator,
        controller_id=controller_id,
    )

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Remove orphaned devices (devices with no entities after reload)
    _cleanup_orphaned_devices(hass, entry)

    # Force-assign areas to devices after platforms are set up
    # This is more reliable than suggested_area which only works on first creation
    await _assign_areas_to_devices(hass, entry, controller_id)

    # Handle HA stop
    async def cleanup(event: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cleanup))
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Start the coordinator's regular updates
    await coordinator.async_config_entry_first_refresh()

    return True


async def _assign_areas_to_devices(
    hass: HomeAssistant, entry: ConfigEntry, controller_id: str
) -> None:
    """Directly assign areas to devices using device registry.

    This is called after all platforms are set up to ensure devices exist.
    It's more reliable than suggested_area which only works on first creation.
    """
    device_registry = dr.async_get(hass)
    options = entry.options

    # Build a mapping from device identifier to expected area
    identifier_to_area: dict[str, str] = {}

    # CCO devices (switches, lights, covers, locks, climate, fans)
    for device_config in options.get(CONF_CCO_DEVICES, []):
        try:
            addr_str = device_config[CONF_ADDR]
            button = device_config.get(
                CONF_BUTTON_NUMBER, device_config.get(CONF_RELAY_NUMBER, 1)
            )
            entity_type = device_config.get(CONF_ENTITY_TYPE, CCO_TYPE_SWITCH)

            if "," not in addr_str:
                full_addr = f"{addr_str},{button}"
            else:
                full_addr = addr_str

            address = CCOAddress.from_string(full_addr)

            # Map entity type to device identifier prefix
            type_prefix_map = {
                CCO_TYPE_SWITCH: "cco",
                CCO_TYPE_LIGHT: "ccolight",
                CCO_TYPE_COVER: "cover",
                CCO_TYPE_LOCK: "lock",
                CCO_TYPE_CLIMATE: "climate",
                "fan": "fan",
            }
            prefix = type_prefix_map.get(entity_type, "cco")

            # Build the identifier that matches what's used in entity files
            identifier = f"{controller_id}.{prefix}.{address}.v2"

            area_name = device_config.get(CONF_AREA)
            if area_name:
                area_id = resolve_area_name(hass, area_name)
                if area_id:
                    identifier_to_area[identifier] = area_id

        except Exception as err:
            _LOGGER.debug("Error building area mapping for CCO: %s", err)

    # Dimmers
    for dimmer_config in options.get(CONF_DIMMERS, []):
        try:
            addr = normalize_address(dimmer_config[CONF_ADDR])
            identifier = f"{controller_id}.{addr}.v2"

            area_name = dimmer_config.get(CONF_AREA)
            if area_name:
                area_id = resolve_area_name(hass, area_name)
                if area_id:
                    identifier_to_area[identifier] = area_id

        except Exception as err:
            _LOGGER.debug("Error building area mapping for dimmer: %s", err)

    # CCI devices
    for cci_config in options.get(CONF_CCI_DEVICES, []):
        try:
            addr = normalize_address(cci_config[CONF_ADDR])
            input_num = cci_config.get(CONF_INPUT_NUMBER, 1)
            identifier = f"{controller_id}.cci.{addr}_{input_num}.v2"

            area_name = cci_config.get(CONF_AREA)
            if area_name:
                area_id = resolve_area_name(hass, area_name)
                if area_id:
                    identifier_to_area[identifier] = area_id

        except Exception as err:
            _LOGGER.debug("Error building area mapping for CCI: %s", err)

    # RPM motor covers
    for rpm_config in options.get(CONF_RPM_COVERS, []):
        try:
            addr = normalize_address(rpm_config[CONF_ADDR])
            identifier = f"{controller_id}.rpm_cover.{addr}.v2"

            area_name = rpm_config.get(CONF_AREA)
            if area_name:
                area_id = resolve_area_name(hass, area_name)
                if area_id:
                    identifier_to_area[identifier] = area_id

        except Exception as err:
            _LOGGER.debug("Error building area mapping for RPM cover: %s", err)

    _LOGGER.debug(
        "Area assignment mapping built: %d devices with areas",
        len(identifier_to_area),
    )

    # Now iterate through all devices and assign areas
    updated_count = 0
    for device_entry in device_registry.devices.values():
        # Only process devices for this config entry
        if entry.entry_id not in device_entry.config_entries:
            continue

        # Check each identifier
        for identifier in device_entry.identifiers:
            if identifier[0] != DOMAIN:
                continue

            device_id_str = identifier[1]
            expected_area = identifier_to_area.get(device_id_str)

            if expected_area and device_entry.area_id != expected_area:
                _LOGGER.info(
                    "Assigning area '%s' to device '%s' (identifier: %s)",
                    expected_area,
                    device_entry.name,
                    device_id_str,
                )
                device_registry.async_update_device(
                    device_entry.id, area_id=expected_area
                )
                updated_count += 1
                break

    if updated_count:
        _LOGGER.info("Assigned areas to %d devices", updated_count)


def _register_cco_devices_from_options(
    coordinator: HomeworksCoordinator, options: dict[str, Any]
) -> None:
    """Register CCO devices from the config entry options.

    Handles both new-style CCO_DEVICES and legacy CCOS/COVERS/LOCKS format.
    """
    # New-style unified CCO devices
    for device_config in options.get(CONF_CCO_DEVICES, []):
        try:
            entity_type_str = device_config.get(CONF_ENTITY_TYPE, CCO_TYPE_SWITCH)
            entity_type = _parse_entity_type(entity_type_str)

            addr_str = device_config[CONF_ADDR]
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
                name=device_config.get(CONF_NAME, ""),
                entity_type=entity_type,
                inverted=device_config.get(CONF_INVERTED, False),
            )
            coordinator.register_cco_device(device)
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error("Failed to register CCO device: %s - %s", device_config, err)

    # Legacy CCO format (switches)
    for cco_config in options.get(CONF_CCOS, []):
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
                name=cco_config.get(CONF_NAME, ""),
                entity_type=CCOEntityType.SWITCH,
                inverted=cco_config.get(CONF_INVERTED, False),
            )
            coordinator.register_cco_device(device)
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error("Failed to register legacy CCO: %s - %s", cco_config, err)

    # Legacy covers
    for cover_config in options.get(CONF_COVERS, []):
        try:
            addr = normalize_address(cover_config[CONF_ADDR])
            parts = addr.strip("[]").split(":")

            address = CCOAddress(
                processor=int(parts[0]),
                link=int(parts[1]),
                address=int(parts[2]),
                button=1,
            )

            device = CCODevice(
                address=address,
                name=cover_config.get(CONF_NAME, ""),
                entity_type=CCOEntityType.COVER,
                inverted=cover_config.get(CONF_INVERTED, False),
            )
            coordinator.register_cco_device(device)
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error("Failed to register legacy cover: %s - %s", cover_config, err)

    # Legacy locks
    for lock_config in options.get(CONF_LOCKS, []):
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
                name=lock_config.get(CONF_NAME, ""),
                entity_type=CCOEntityType.LOCK,
                inverted=lock_config.get(CONF_INVERTED, False),
            )
            coordinator.register_cco_device(device)
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error("Failed to register legacy lock: %s - %s", lock_config, err)


def _parse_entity_type(type_str: str) -> CCOEntityType:
    """Parse entity type string to enum."""
    type_map = {
        CCO_TYPE_SWITCH: CCOEntityType.SWITCH,
        CCO_TYPE_LIGHT: CCOEntityType.LIGHT,
        CCO_TYPE_COVER: CCOEntityType.COVER,
        CCO_TYPE_LOCK: CCOEntityType.LOCK,
        CCO_TYPE_CLIMATE: CCOEntityType.CLIMATE,
        CCO_TYPE_FAN: CCOEntityType.FAN,
    }
    return type_map.get(type_str.lower(), CCOEntityType.SWITCH)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    data: HomeworksData = hass.data[DOMAIN].pop(entry.entry_id)
    await data.coordinator.async_shutdown()

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removal of a device only if it has no active entities.

    HA calls this to confirm whether a device can be removed.
    We allow removal only if the device has no active entities (orphaned after
    a cover/dimmer/etc was deleted from the options flow).
    """
    entity_registry = async_get_entity_registry(hass)

    has_entities = any(
        entity.device_id == device_entry.id
        for entity in entity_registry.entities.values()
        if entity.config_entry_id == entry.entry_id
    )

    if has_entities:
        _LOGGER.debug(
            "Refusing device removal — device '%s' still has active entities",
            device_entry.name,
        )
        return False

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def calculate_unique_id(controller_id: str, addr: str, idx: int) -> str:
    """Calculate entity unique id."""
    return f"homeworks.{controller_id}.{addr}.{idx}.v2"


class HomeworksEntity(Entity):
    """Base class of a Homeworks device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HomeworksCoordinator,
        controller_id: str,
        addr: str,
        idx: int,
        name: str | None,
    ) -> None:
        """Initialize Homeworks device."""
        self._addr = addr
        self._idx = idx
        self._controller_id = controller_id
        self._coordinator = coordinator
        self._attr_name = name
        self._attr_unique_id = calculate_unique_id(
            self._controller_id, self._addr, self._idx
        )
        self._attr_extra_state_attributes = {"homeworks_address": self._addr}

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._coordinator.connected

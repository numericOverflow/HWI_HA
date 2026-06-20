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
import re
from typing import Any
import unicodedata

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
from homeassistant.exceptions import ServiceValidationError
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
    SERVICE_SEND_COMMAND,
)
from .coordinator import HomeworksCoordinator
from .models import CCOAddress, CCODevice, CCOEntityType

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


type HomeworksHWIConfigEntry = ConfigEntry[HomeworksData]


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in a string.

    - Strips leading/trailing whitespace
    - Replaces multiple consecutive spaces with single space
    - Replaces various unicode whitespace characters with regular space
    """
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
        "Area '%s' not found in registry. HA will create a new area.",
        area_name,
    )
    _LOGGER.debug(
        "Available areas for resolution of '%s': %s",
        area_name,
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
        SERVICE_SEND_COMMAND,
        async_call_service,
        schema=SERVICE_SEND_COMMAND_SCHEMA,
    )


async def async_send_command(hass: HomeAssistant, data: Mapping[str, Any]) -> None:
    """Send command to a controller."""

    def get_controller_ids() -> list[str]:
        """Get controller IDs."""
        return [
            entry.runtime_data.controller_id
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        ]

    def get_homeworks_data(controller_id: str) -> HomeworksData | None:
        """Get homeworks data for controller ID."""
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            hw_data: HomeworksData = entry.runtime_data
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
                delay = max(0, min(int(command.partition(" ")[2]), MAX_COMMAND_DELAY_MS))
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

        # Only remove entities matching our legacy pattern
        unique_id = entity_entry.unique_id
        if (
            unique_id
            and unique_id.startswith("homeworks.")
            and not unique_id.endswith(".v2")
        ):
            entities_to_remove.append(entity_entry.entity_id)
            _LOGGER.debug("Marking for removal: %s (unique_id: %s)",
                         entity_entry.entity_id, unique_id)

    for entity_id in entities_to_remove:
        _LOGGER.info("Removing old entity with legacy unique_id: %s", entity_id)
        entity_registry.async_remove(entity_id)

    if entities_to_remove:
        _LOGGER.info("Cleaned up %d old entities", len(entities_to_remove))


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


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrate config entry to current version."""
    if config_entry.version == 1:
        _LOGGER.info(
            "Migrating config entry %s from v1 to v2", config_entry.entry_id
        )
        new_options = dict(config_entry.options)

        # Convert legacy CCOS → CCO_DEVICES (switches)
        for cco in new_options.pop(CONF_CCOS, []):
            device = {
                CONF_ADDR: cco[CONF_ADDR],
                CONF_BUTTON_NUMBER: cco.get(CONF_RELAY_NUMBER, 1),
                CONF_NAME: cco.get(CONF_NAME, ""),
                CONF_ENTITY_TYPE: CCO_TYPE_SWITCH,
                CONF_INVERTED: cco.get(CONF_INVERTED, False),
            }
            if CONF_AREA in cco:
                device[CONF_AREA] = cco[CONF_AREA]
            new_options.setdefault(CONF_CCO_DEVICES, []).append(device)

        # Convert legacy COVERS → CCO_DEVICES
        for cover in new_options.pop(CONF_COVERS, []):
            device = {
                CONF_ADDR: cover[CONF_ADDR],
                CONF_BUTTON_NUMBER: 1,
                CONF_NAME: cover.get(CONF_NAME, ""),
                CONF_ENTITY_TYPE: CCO_TYPE_COVER,
                CONF_INVERTED: cover.get(CONF_INVERTED, False),
            }
            if CONF_AREA in cover:
                device[CONF_AREA] = cover[CONF_AREA]
            new_options.setdefault(CONF_CCO_DEVICES, []).append(device)

        # Convert legacy LOCKS → CCO_DEVICES
        for lock_cfg in new_options.pop(CONF_LOCKS, []):
            device = {
                CONF_ADDR: lock_cfg[CONF_ADDR],
                CONF_BUTTON_NUMBER: lock_cfg.get(CONF_RELAY_NUMBER, 1),
                CONF_NAME: lock_cfg.get(CONF_NAME, ""),
                CONF_ENTITY_TYPE: CCO_TYPE_LOCK,
                CONF_INVERTED: lock_cfg.get(CONF_INVERTED, False),
            }
            if CONF_AREA in lock_cfg:
                device[CONF_AREA] = lock_cfg[CONF_AREA]
            new_options.setdefault(CONF_CCO_DEVICES, []).append(device)

        hass.config_entries.async_update_entry(
            config_entry, options=new_options, version=2
        )
        _LOGGER.info(
            "Migration complete: %d CCO devices total",
            len(new_options.get(CONF_CCO_DEVICES, [])),
        )

    if config_entry.version == 2:
        _LOGGER.warning(
            "Migrating config entry %s from v2 to v3: "
            "CCO state polarity corrected. Flipping all 'inverted' flags "
            "to preserve existing behavior.",
            config_entry.entry_id,
        )
        new_options = dict(config_entry.options)
        for device in new_options.get(CONF_CCO_DEVICES, []):
            device[CONF_INVERTED] = not device.get(CONF_INVERTED, False)
        hass.config_entries.async_update_entry(
            config_entry, options=new_options, version=3
        )

    # Clean up old entities with legacy unique_id format (pre-v2 suffix)
    _cleanup_old_entities(hass, config_entry)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomeworksHWIConfigEntry) -> bool:
    """Set up Homeworks from a config entry.

    Credentials are read from entry.data (secrets).
    Devices and settings are read from entry.options (non-secrets).
    """
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

    # Create coordinator (client created but not connected — lazy connect on first poll)
    coordinator = HomeworksCoordinator(
        hass=hass,
        config=client_config,
        controller_id=controller_id,
        config_entry=entry,
        kls_poll_interval=timedelta(seconds=kls_poll_interval),
        kls_window_offset=kls_window_offset,
    )

    # Store data in entry.runtime_data (auto-cleaned by HA on unload)
    entry.runtime_data = HomeworksData(
        coordinator=coordinator,
        controller_id=controller_id,
    )

    # First refresh connects, subscribes, and polls initial state.
    # On any failure, shut down to avoid leaked connections/tasks.
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_shutdown()
        raise

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Remove orphaned devices (devices with no entities after reload)
    _cleanup_orphaned_devices(hass, entry)

    # Handle HA stop
    async def cleanup(event: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cleanup))

    return True


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


def parse_cco_device_config(
    hass: HomeAssistant,
    device_config: dict[str, Any],
    entity_type: CCOEntityType,
    default_name: str,
) -> CCODevice:
    """Parse a CCO device config dict into a CCODevice."""
    addr_str = device_config[CONF_ADDR]
    button = device_config.get(
        CONF_BUTTON_NUMBER, device_config.get(CONF_RELAY_NUMBER, 1)
    )
    if "," not in addr_str:
        full_addr = f"{addr_str},{button}"
    else:
        full_addr = addr_str

    address = CCOAddress.from_string(full_addr)

    return CCODevice(
        address=address,
        name=device_config.get(CONF_NAME, default_name),
        entity_type=entity_type,
        inverted=device_config.get(CONF_INVERTED, False),
        area=resolve_area_name(hass, device_config.get(CONF_AREA)),
    )


def create_cco_entities_for_type(
    hass: HomeAssistant,
    entry: HomeworksHWIConfigEntry,
    coordinator: HomeworksCoordinator,
    controller_id: str,
    target_type: str,
    entity_type: CCOEntityType,
    entity_cls: type,
    default_name: str,
) -> list[Entity]:
    """Create CCO entities of a given type from config options.

    Constructor contract: entity_cls MUST accept keyword arguments
    (coordinator, controller_id, device). All CCO entity classes follow this.
    """
    entities: list[Entity] = []
    for device_config in entry.options.get(CONF_CCO_DEVICES, []):
        if device_config.get(CONF_ENTITY_TYPE) != target_type:
            continue
        try:
            device = parse_cco_device_config(
                hass, device_config, entity_type, default_name
            )
            entities.append(
                entity_cls(
                    coordinator=coordinator,
                    controller_id=controller_id,
                    device=device,
                )
            )
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for %s device '%s': %s",
                target_type,
                device_config.get(CONF_NAME, "unknown"),
                err,
            )
    return entities


async def async_unload_entry(hass: HomeAssistant, entry: HomeworksHWIConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    await entry.runtime_data.coordinator.async_shutdown()

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

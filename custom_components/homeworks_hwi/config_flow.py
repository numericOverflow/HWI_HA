"""Lutron Homeworks Series 4 and 8 config flow.

HA 2026.1 compliant:
- Credentials (host, port, username, password) stored in entry.data
- Non-secrets (devices, settings) stored in entry.options
"""

from __future__ import annotations

import csv
from collections import Counter
from io import StringIO
import logging
from typing import Any, NamedTuple

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    selector,
)
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
    SchemaOptionsFlowHandler,
    SchemaOptionsFlowHandlerWithReload,
)
from homeassistant.helpers.typing import VolDictType
from homeassistant.util import slugify

from .const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTON_NUMBER,
    CONF_BUTTONS,
    CONF_CCI_DEVICES,
    CONF_CCO_DEVICES,
    CONF_CCOS,
    CONF_CONTROLLER_ID,
    CONF_COVERS,
    CONF_DEVICE_CLASS,
    CONF_DIMMERS,
    CONF_ENTITY_TYPE,
    CONF_INDEX,
    CONF_INPUT_NUMBER,
    CONF_INVERTED,
    CONF_KEYPADS,
    CONF_KLS_POLL_INTERVAL,
    CONF_KLS_WINDOW_OFFSET,
    CONF_LED,
    CONF_LOCKS,
    CONF_NUMBER,
    CONF_QED_COVERS,
    CONF_RATE,
    CONF_RELAY_NUMBER,
    CONF_RELEASE_DELAY,
    CONF_RPM_COVERS,
    CCO_TYPE_CLIMATE,
    CCO_TYPE_COVER,
    CCO_TYPE_FAN,
    CCO_TYPE_LIGHT,
    CCO_TYPE_LOCK,
    CCO_TYPE_SWITCH,
    DEFAULT_BUTTON_NAME,
    DEFAULT_CCI_NAME,
    DEFAULT_CCO_NAME,
    DEFAULT_FADE_RATE,
    DEFAULT_KEYPAD_NAME,
    DEFAULT_KLS_POLL_INTERVAL,
    DEFAULT_KLS_WINDOW_OFFSET,
    DEFAULT_LIGHT_NAME,
    DEFAULT_QED_COVER_NAME,
    DEFAULT_RPM_COVER_NAME,
    DOMAIN,
    MAX_CSV_ROWS,
    MAX_CSV_SIZE,
)
from .models import CCOAddress, normalize_address
from .xml_import import (
    MAX_XML_SIZE,
    ParsedProject,
    XMLImportError,
    get_cco_address_parts,
    parse_homeworks_xml,
)

_LOGGER = logging.getLogger(__name__)

# CCO device types for selector
CCO_ENTITY_TYPES = [
    selector.SelectOptionDict(value=CCO_TYPE_SWITCH, label="switch"),
    selector.SelectOptionDict(value=CCO_TYPE_LIGHT, label="light"),
    selector.SelectOptionDict(value=CCO_TYPE_COVER, label="cover"),
    selector.SelectOptionDict(value=CCO_TYPE_LOCK, label="lock"),
    selector.SelectOptionDict(value=CCO_TYPE_CLIMATE, label="climate"),
    selector.SelectOptionDict(value=CCO_TYPE_FAN, label="fan"),
]


# === Connection Testing ===


async def _try_connection(
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Try connecting to the controller."""
    from .client import HomeworksClient, HomeworksClientConfig

    config = HomeworksClientConfig(
        host=host,
        port=port,
        username=username,
        password=password,
    )

    client = HomeworksClient(config)

    try:
        connected = await client.connect()
        if not connected:
            raise SchemaFlowError("connection_error")
        await client.stop()
    except SchemaFlowError:
        raise
    except Exception as err:
        _LOGGER.debug("Connection failed: %s", err)
        raise SchemaFlowError("connection_error") from err


# === Validation Functions ===


def _validate_address(addr: str) -> str:
    """Validate and normalize address format."""
    try:
        normalized = normalize_address(addr)
        parts = normalized.strip("[]").split(":")
        if len(parts) not in (3, 4, 5) or not all(len(p) == 2 for p in parts):
            raise SchemaFlowError("invalid_addr")
        return normalized
    except ValueError as err:
        raise SchemaFlowError("invalid_addr") from err


def _validate_cco_address(addr_str: str, button: int) -> CCOAddress:
    """Validate and parse a CCO address."""
    try:
        if "," not in addr_str:
            full_addr = f"{addr_str},{button}"
        else:
            full_addr = addr_str
        return CCOAddress.from_string(full_addr)
    except ValueError as err:
        raise SchemaFlowError("invalid_addr") from err


# === CCO Device CRUD ===


async def validate_add_cco_device(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate CCO device input."""
    addr = user_input[CONF_ADDR]
    button = int(
        user_input.get(CONF_BUTTON_NUMBER, user_input.get(CONF_RELAY_NUMBER, 1))
    )
    cco_addr = _validate_cco_address(addr, button)

    # Check for duplicates
    for device in handler.options.get(CONF_CCO_DEVICES, []):
        existing_addr = _validate_cco_address(
            device[CONF_ADDR],
            device.get(CONF_BUTTON_NUMBER, device.get(CONF_RELAY_NUMBER, 1)),
        )
        if existing_addr.unique_key == cco_addr.unique_key:
            raise SchemaFlowError("duplicate_cco")

    user_input[CONF_ADDR] = cco_addr.to_kls_address()
    user_input[CONF_BUTTON_NUMBER] = button

    items = handler.options.setdefault(CONF_CCO_DEVICES, [])
    items.append(user_input)
    return {}


async def get_select_cco_device_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting a CCO device."""
    devices = handler.options.get(CONF_CCO_DEVICES, [])
    if not devices:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(
                        i
                    ): f"{d.get(CONF_NAME, 'CCO')} ({d[CONF_ADDR]}:{d.get(CONF_BUTTON_NUMBER, d.get(CONF_RELAY_NUMBER, 1))}) [{d.get(CONF_ENTITY_TYPE, 'switch')}]"
                    for i, d in enumerate(devices)
                }
            )
        }
    )


async def validate_select_cco_device(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store CCO device index."""
    handler.flow_state["_cco_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_edit_cco_device_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return suggested values for CCO device editing."""
    idx = handler.flow_state["_cco_idx"]
    device = handler.options[CONF_CCO_DEVICES][idx]
    values = {
        CONF_NAME: device.get(CONF_NAME, ""),
        CONF_ADDR: device.get(CONF_ADDR, ""),
        CONF_BUTTON_NUMBER: device.get(
            CONF_BUTTON_NUMBER, device.get(CONF_RELAY_NUMBER, 1)
        ),
        CONF_ENTITY_TYPE: device.get(CONF_ENTITY_TYPE, CCO_TYPE_SWITCH),
        CONF_INVERTED: device.get(CONF_INVERTED, False),
    }
    if device.get(CONF_AREA):
        values[CONF_AREA] = device.get(CONF_AREA)
    return values


async def validate_cco_device_edit(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update edited CCO device."""
    idx = handler.flow_state["_cco_idx"]

    if CONF_ADDR in user_input:
        addr = user_input[CONF_ADDR]
        button = int(user_input.get(CONF_BUTTON_NUMBER, 1))
        cco_addr = _validate_cco_address(addr, button)

        # Check for duplicates (excluding current)
        for i, device in enumerate(handler.options.get(CONF_CCO_DEVICES, [])):
            if i == idx:
                continue
            existing_addr = _validate_cco_address(
                device[CONF_ADDR],
                device.get(CONF_BUTTON_NUMBER, device.get(CONF_RELAY_NUMBER, 1)),
            )
            if existing_addr.unique_key == cco_addr.unique_key:
                raise SchemaFlowError("duplicate_cco")

        user_input[CONF_ADDR] = cco_addr.to_kls_address()
        user_input[CONF_BUTTON_NUMBER] = button

    handler.options[CONF_CCO_DEVICES][idx].update(user_input)
    return {}


async def get_remove_cco_device_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for CCO device removal."""
    devices = handler.options.get(CONF_CCO_DEVICES, [])
    if not devices:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(
                        i
                    ): f"{d.get(CONF_NAME, 'CCO')} ({d[CONF_ADDR]}:{d.get(CONF_BUTTON_NUMBER, d.get(CONF_RELAY_NUMBER, 1))})"
                    for i, d in enumerate(devices)
                }
            )
        }
    )


# Map CCO entity_type to (HA domain, unique_id type prefix)
_CCO_TYPE_MAP: dict[str, tuple[str, str]] = {
    CCO_TYPE_SWITCH: ("switch", "cco"),
    CCO_TYPE_LIGHT: ("light", "ccolight"),
    CCO_TYPE_COVER: ("cover", "cover"),
    CCO_TYPE_LOCK: ("lock", "lock"),
    CCO_TYPE_CLIMATE: ("climate", "climate"),
    CCO_TYPE_FAN: ("fan", "fan"),
}


def _remove_cco_entity(
    registry: er.EntityRegistry,
    controller_id: str,
    device: dict[str, Any],
) -> None:
    """Remove entity for a CCO device using exact unique_id matching."""
    addr_parts = device[CONF_ADDR].strip("[]").split(":")
    btn = device.get(CONF_BUTTON_NUMBER, device.get(CONF_RELAY_NUMBER, 1))
    device_uid = (
        f"cco_{int(addr_parts[0])}_{int(addr_parts[1])}_{int(addr_parts[2])}_{btn}"
    )
    entity_type = device.get(CONF_ENTITY_TYPE, CCO_TYPE_SWITCH)
    ha_domain, uid_prefix = _CCO_TYPE_MAP.get(entity_type, ("switch", "cco"))
    uid = f"homeworks.{controller_id}.{uid_prefix}.{device_uid}.v2"
    entity_id = registry.async_get_entity_id(ha_domain, DOMAIN, uid)
    if entity_id:
        registry.async_remove(entity_id)


async def validate_remove_cco_device(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected CCO devices."""
    removed = set(user_input[CONF_INDEX])
    registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_devices = []
    for i, device in enumerate(handler.options.get(CONF_CCO_DEVICES, [])):
        if str(i) not in removed:
            new_devices.append(device)
        else:
            _remove_cco_entity(registry, controller_id, device)

    handler.options[CONF_CCO_DEVICES] = new_devices
    return {}


# === Dimmable Light CRUD ===


async def validate_add_light(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate light input."""
    user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])

    for item in handler.options.get(CONF_DIMMERS, []):
        if normalize_address(item[CONF_ADDR]) == user_input[CONF_ADDR]:
            raise SchemaFlowError("duplicated_addr")

    items = handler.options.setdefault(CONF_DIMMERS, [])
    items.append(user_input)
    return {}


async def get_select_light_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting a light."""
    lights = handler.options.get(CONF_DIMMERS, [])
    if not lights:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(i): f"{d.get(CONF_NAME, 'Light')} ({d[CONF_ADDR]})"
                    for i, d in enumerate(lights)
                }
            )
        }
    )


async def validate_select_light(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store light index."""
    handler.flow_state["_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_edit_light_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return suggested values for light editing."""
    idx = handler.flow_state["_idx"]
    return dict(handler.options[CONF_DIMMERS][idx])


async def validate_light_edit(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update edited light."""
    idx = handler.flow_state["_idx"]

    if CONF_ADDR in user_input:
        user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])
        for i, item in enumerate(handler.options.get(CONF_DIMMERS, [])):
            if i == idx:
                continue
            if normalize_address(item[CONF_ADDR]) == user_input[CONF_ADDR]:
                raise SchemaFlowError("duplicated_addr")

    handler.options[CONF_DIMMERS][idx].update(user_input)
    return {}


async def get_remove_light_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for light removal."""
    lights = handler.options.get(CONF_DIMMERS, [])
    if not lights:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(i): f"{d.get(CONF_NAME, 'Light')} ({d[CONF_ADDR]})"
                    for i, d in enumerate(lights)
                }
            )
        }
    )


async def validate_remove_light(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected lights."""
    removed = set(user_input[CONF_INDEX])
    registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_items = []
    for i, item in enumerate(handler.options.get(CONF_DIMMERS, [])):
        if str(i) not in removed:
            new_items.append(item)
        else:
            uid = f"homeworks.{controller_id}.light.{item[CONF_ADDR]}.v2"
            entity_id = registry.async_get_entity_id("light", DOMAIN, uid)
            if entity_id:
                registry.async_remove(entity_id)

    handler.options[CONF_DIMMERS] = new_items
    return {}


# === RPM Motor Cover CRUD ===


async def validate_add_rpm_cover(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate RPM cover input."""
    user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])

    for item in handler.options.get(CONF_RPM_COVERS, []):
        if normalize_address(item[CONF_ADDR]) == user_input[CONF_ADDR]:
            raise SchemaFlowError("duplicated_addr")

    items = handler.options.setdefault(CONF_RPM_COVERS, [])
    items.append(user_input)
    return {}


async def get_select_rpm_cover_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting an RPM cover."""
    covers = handler.options.get(CONF_RPM_COVERS, [])
    if not covers:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(i): f"{d.get(CONF_NAME, 'RPM Cover')} ({d[CONF_ADDR]})"
                    for i, d in enumerate(covers)
                }
            )
        }
    )


async def validate_select_rpm_cover(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store RPM cover index."""
    handler.flow_state["_rpm_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_edit_rpm_cover_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return suggested values for RPM cover editing."""
    idx = handler.flow_state["_rpm_idx"]
    return dict(handler.options[CONF_RPM_COVERS][idx])


async def validate_rpm_cover_edit(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update edited RPM cover."""
    idx = handler.flow_state["_rpm_idx"]

    if CONF_ADDR in user_input:
        user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])
        for i, item in enumerate(handler.options.get(CONF_RPM_COVERS, [])):
            if i == idx:
                continue
            if normalize_address(item[CONF_ADDR]) == user_input[CONF_ADDR]:
                raise SchemaFlowError("duplicated_addr")

    handler.options[CONF_RPM_COVERS][idx].update(user_input)
    return {}


async def get_remove_rpm_cover_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for RPM cover removal."""
    covers = handler.options.get(CONF_RPM_COVERS, [])
    if not covers:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(i): f"{d.get(CONF_NAME, 'RPM Cover')} ({d[CONF_ADDR]})"
                    for i, d in enumerate(covers)
                }
            )
        }
    )


async def validate_remove_rpm_cover(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected RPM covers."""
    removed = set(user_input[CONF_INDEX])
    registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_items = []
    for i, item in enumerate(handler.options.get(CONF_RPM_COVERS, [])):
        if str(i) not in removed:
            new_items.append(item)
        else:
            uid = f"homeworks.{controller_id}.rpm_cover.{item[CONF_ADDR]}.v2"
            entity_id = registry.async_get_entity_id("cover", DOMAIN, uid)
            if entity_id:
                registry.async_remove(entity_id)

    handler.options[CONF_RPM_COVERS] = new_items
    return {}


# === QED Shade CRUD ===


async def validate_add_qed_cover(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate QED cover input."""
    addr = _validate_address(user_input[CONF_ADDR])
    user_input[CONF_ADDR] = addr
    for item in handler.options.get(CONF_QED_COVERS, []):
        if normalize_address(item[CONF_ADDR]) == addr:
            raise SchemaFlowError("duplicated_addr")
    items = handler.options.setdefault(CONF_QED_COVERS, [])
    items.append(user_input)
    return {}


async def get_select_qed_cover_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting a QED cover."""
    covers = handler.options.get(CONF_QED_COVERS, [])
    if not covers:
        raise SchemaFlowError("no_devices")
    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(i): f"{c.get(CONF_NAME, 'QED')} ({c[CONF_ADDR]})"
                    for i, c in enumerate(covers)
                }
            )
        }
    )


async def validate_select_qed_cover(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store QED cover index."""
    handler.flow_state["_qed_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_edit_qed_cover_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return suggested values for QED cover editing."""
    idx = handler.flow_state["_qed_idx"]
    return dict(handler.options[CONF_QED_COVERS][idx])


async def validate_qed_cover_edit(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update edited QED cover."""
    idx = handler.flow_state["_qed_idx"]

    if CONF_ADDR in user_input:
        user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])
        for i, item in enumerate(handler.options.get(CONF_QED_COVERS, [])):
            if i == idx:
                continue
            if normalize_address(item[CONF_ADDR]) == user_input[CONF_ADDR]:
                raise SchemaFlowError("duplicated_addr")

    handler.options[CONF_QED_COVERS][idx].update(user_input)
    return {}


async def get_remove_qed_cover_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for QED cover removal."""
    covers = handler.options.get(CONF_QED_COVERS, [])
    if not covers:
        raise SchemaFlowError("no_devices")
    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(i): f"{c.get(CONF_NAME, 'QED')} ({c[CONF_ADDR]})"
                    for i, c in enumerate(covers)
                }
            )
        }
    )


async def validate_remove_qed_cover(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected QED covers."""
    removed = set(user_input[CONF_INDEX])
    ent_registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_items = []
    for i, item in enumerate(handler.options.get(CONF_QED_COVERS, [])):
        if str(i) not in removed:
            new_items.append(item)
        else:
            uid = f"homeworks.{controller_id}.qed_cover.{item[CONF_ADDR]}.v2"
            entity_id = ent_registry.async_get_entity_id("cover", DOMAIN, uid)
            if entity_id:
                ent_registry.async_remove(entity_id)

    handler.options[CONF_QED_COVERS] = new_items
    return {}


# === CCI Device CRUD ===


async def validate_add_cci_device(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate CCI device input."""
    user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])
    input_number = int(user_input.get(CONF_INPUT_NUMBER, 1))

    # Check for duplicates (same address + input number)
    for device in handler.options.get(CONF_CCI_DEVICES, []):
        if (
            normalize_address(device[CONF_ADDR]) == user_input[CONF_ADDR]
            and device.get(CONF_INPUT_NUMBER, 1) == input_number
        ):
            raise SchemaFlowError("duplicate_cci")

    user_input[CONF_INPUT_NUMBER] = input_number
    items = handler.options.setdefault(CONF_CCI_DEVICES, [])
    items.append(user_input)
    return {}


async def get_select_cci_device_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting a CCI device."""
    devices = handler.options.get(CONF_CCI_DEVICES, [])
    if not devices:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(i): f"{d.get(CONF_NAME, 'Input')} ({d[CONF_ADDR]}:{d.get(CONF_INPUT_NUMBER, 1)})"
                    for i, d in enumerate(devices)
                }
            )
        }
    )


async def validate_select_cci_device(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store CCI device index."""
    handler.flow_state["_cci_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_edit_cci_device_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return suggested values for CCI device editing."""
    idx = handler.flow_state["_cci_idx"]
    device = handler.options[CONF_CCI_DEVICES][idx]
    values = {
        CONF_NAME: device.get(CONF_NAME, ""),
        CONF_ADDR: device.get(CONF_ADDR, ""),
        CONF_INPUT_NUMBER: device.get(CONF_INPUT_NUMBER, 1),
    }
    if device.get(CONF_DEVICE_CLASS):
        values[CONF_DEVICE_CLASS] = device[CONF_DEVICE_CLASS]
    if device.get(CONF_AREA):
        values[CONF_AREA] = device[CONF_AREA]
    return values


async def validate_cci_device_edit(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update edited CCI device."""
    idx = handler.flow_state["_cci_idx"]
    current = handler.options[CONF_CCI_DEVICES][idx]

    addr = user_input.get(CONF_ADDR, current[CONF_ADDR])
    if CONF_ADDR in user_input:
        addr = _validate_address(addr)
        user_input[CONF_ADDR] = addr

    input_number = int(
        user_input.get(CONF_INPUT_NUMBER, current.get(CONF_INPUT_NUMBER, 1))
    )

    # Always check for duplicates regardless of which fields changed
    for i, device in enumerate(handler.options.get(CONF_CCI_DEVICES, [])):
        if i == idx:
            continue
        if (
            normalize_address(device[CONF_ADDR]) == normalize_address(addr)
            and device.get(CONF_INPUT_NUMBER, 1) == input_number
        ):
            raise SchemaFlowError("duplicate_cci")

    handler.options[CONF_CCI_DEVICES][idx].update(user_input)
    return {}


async def get_remove_cci_device_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for CCI device removal."""
    devices = handler.options.get(CONF_CCI_DEVICES, [])
    if not devices:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(i): f"{d.get(CONF_NAME, 'Input')} ({d[CONF_ADDR]}:{d.get(CONF_INPUT_NUMBER, 1)})"
                    for i, d in enumerate(devices)
                }
            )
        }
    )


async def validate_remove_cci_device(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected CCI devices."""
    removed = set(user_input[CONF_INDEX])
    registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_devices = []
    for i, device in enumerate(handler.options.get(CONF_CCI_DEVICES, [])):
        if str(i) not in removed:
            new_devices.append(device)
        else:
            addr_clean = device[CONF_ADDR].replace(":", "_").strip("[]")
            input_num = device.get(CONF_INPUT_NUMBER, 1)
            uid = f"homeworks.{controller_id}.cci.{addr_clean}_{input_num}.v2"
            entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, uid)
            if entity_id:
                registry.async_remove(entity_id)

    handler.options[CONF_CCI_DEVICES] = new_devices
    return {}


# === Keypad CRUD ===


async def validate_add_keypad(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate keypad input."""
    user_input[CONF_ADDR] = _validate_address(user_input[CONF_ADDR])

    for item in handler.options.get(CONF_KEYPADS, []):
        if normalize_address(item[CONF_ADDR]) == user_input[CONF_ADDR]:
            raise SchemaFlowError("duplicated_addr")

    items = handler.options.setdefault(CONF_KEYPADS, [])
    items.append(user_input | {CONF_BUTTONS: []})
    return {}


async def get_select_keypad_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting a keypad."""
    keypads = handler.options.get(CONF_KEYPADS, [])
    if not keypads:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(i): f"{d.get(CONF_NAME, 'Keypad')} ({d[CONF_ADDR]})"
                    for i, d in enumerate(keypads)
                }
            )
        }
    )


async def validate_select_keypad(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store keypad index."""
    handler.flow_state["_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_remove_keypad_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for keypad removal."""
    keypads = handler.options.get(CONF_KEYPADS, [])
    if not keypads:
        raise SchemaFlowError("no_devices")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(i): f"{d.get(CONF_NAME, 'Keypad')} ({d[CONF_ADDR]})"
                    for i, d in enumerate(keypads)
                }
            )
        }
    )


async def validate_remove_keypad(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected keypads."""
    removed = set(user_input[CONF_INDEX])
    registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_items = []
    for i, item in enumerate(handler.options.get(CONF_KEYPADS, [])):
        if str(i) not in removed:
            new_items.append(item)
        else:
            addr = item[CONF_ADDR]
            # Remove all button and LED entities for this keypad
            for button in item.get(CONF_BUTTONS, []):
                btn_num = button[CONF_NUMBER]
                btn_uid = f"homeworks.{controller_id}.button.{addr}.{btn_num}.v2"
                eid = registry.async_get_entity_id("button", DOMAIN, btn_uid)
                if eid:
                    registry.async_remove(eid)
                if button.get(CONF_LED, False):
                    led_uid = f"homeworks.{controller_id}.led.{addr}.{btn_num}.v2"
                    eid = registry.async_get_entity_id(
                        "binary_sensor", DOMAIN, led_uid
                    )
                    if eid:
                        registry.async_remove(eid)

    handler.options[CONF_KEYPADS] = new_items
    return {}


# === Keypad Button CRUD ===


async def validate_add_button(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate button input."""
    user_input[CONF_NUMBER] = int(user_input[CONF_NUMBER])
    keypad_idx = handler.flow_state["_idx"]
    buttons = handler.options[CONF_KEYPADS][keypad_idx][CONF_BUTTONS]

    for button in buttons:
        if button[CONF_NUMBER] == user_input[CONF_NUMBER]:
            raise SchemaFlowError("duplicated_number")

    buttons.append(user_input)
    return {}


async def get_select_button_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for selecting a button."""
    keypad_idx = handler.flow_state["_idx"]
    buttons = handler.options[CONF_KEYPADS][keypad_idx][CONF_BUTTONS]

    if not buttons:
        raise SchemaFlowError("no_buttons")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): vol.In(
                {
                    str(i): f"{b.get(CONF_NAME, 'Button')} (#{b[CONF_NUMBER]})"
                    for i, b in enumerate(buttons)
                }
            )
        }
    )


async def validate_select_button(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store button index."""
    handler.flow_state["_button_idx"] = int(user_input[CONF_INDEX])
    return {}


async def get_edit_button_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return suggested values for button editing."""
    keypad_idx = handler.flow_state["_idx"]
    button_idx = handler.flow_state["_button_idx"]
    return dict(handler.options[CONF_KEYPADS][keypad_idx][CONF_BUTTONS][button_idx])


async def validate_button_edit(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update edited button."""
    keypad_idx = handler.flow_state["_idx"]
    button_idx = handler.flow_state["_button_idx"]
    handler.options[CONF_KEYPADS][keypad_idx][CONF_BUTTONS][button_idx].update(
        user_input
    )
    return {}


async def get_remove_button_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for button removal."""
    keypad_idx = handler.flow_state["_idx"]
    buttons = handler.options[CONF_KEYPADS][keypad_idx][CONF_BUTTONS]

    if not buttons:
        raise SchemaFlowError("no_buttons")

    return vol.Schema(
        {
            vol.Required(CONF_INDEX): cv.multi_select(
                {
                    str(i): f"{b.get(CONF_NAME, 'Button')} (#{b[CONF_NUMBER]})"
                    for i, b in enumerate(buttons)
                }
            )
        }
    )


async def validate_remove_button(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Remove selected buttons."""
    removed = set(user_input[CONF_INDEX])
    keypad_idx = handler.flow_state["_idx"]
    keypad = handler.options[CONF_KEYPADS][keypad_idx]
    addr = keypad[CONF_ADDR]
    registry = er.async_get(handler.parent_handler.hass)
    controller_id = handler.options[CONF_CONTROLLER_ID]

    new_buttons = []
    for i, button in enumerate(keypad[CONF_BUTTONS]):
        if str(i) not in removed:
            new_buttons.append(button)
        else:
            btn_num = button[CONF_NUMBER]
            btn_uid = f"homeworks.{controller_id}.button.{addr}.{btn_num}.v2"
            eid = registry.async_get_entity_id("button", DOMAIN, btn_uid)
            if eid:
                registry.async_remove(eid)
            if button.get(CONF_LED, False):
                led_uid = f"homeworks.{controller_id}.led.{addr}.{btn_num}.v2"
                eid = registry.async_get_entity_id(
                    "binary_sensor", DOMAIN, led_uid
                )
                if eid:
                    registry.async_remove(eid)

    keypad[CONF_BUTTONS] = new_buttons
    return {}


# === Controller Settings ===


async def get_controller_settings_suggested_values(
    handler: SchemaCommonFlowHandler,
) -> dict[str, Any]:
    """Return current controller settings."""
    return {
        CONF_KLS_POLL_INTERVAL: handler.options.get(
            CONF_KLS_POLL_INTERVAL, DEFAULT_KLS_POLL_INTERVAL
        ),
        CONF_KLS_WINDOW_OFFSET: handler.options.get(
            CONF_KLS_WINDOW_OFFSET, DEFAULT_KLS_WINDOW_OFFSET
        ),
    }


async def validate_controller_settings(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Update controller settings."""
    handler.options[CONF_KLS_POLL_INTERVAL] = int(user_input[CONF_KLS_POLL_INTERVAL])
    handler.options[CONF_KLS_WINDOW_OFFSET] = int(user_input[CONF_KLS_WINDOW_OFFSET])
    return {}


# === CSV Import ===


class DeviceImport(NamedTuple):
    """Device import from CSV."""

    device_type: str  # CCO, DIMMER, CCI, or MOTOR_COVER
    address: str
    button: int | None  # For CCO/CCI: button/input number
    name: str
    entity_type: str | None = None  # For CCO: switch/light/cover/lock/climate/fan
    area: str | None = None  # Home Assistant area ID
    device_class: str | None = None  # For CCI: door/window/motion/etc.


async def async_parse_csv(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Parse CSV content."""
    content = user_input["csv_file"]

    if len(content) > MAX_CSV_SIZE:
        raise SchemaFlowError("csv_too_large")

    # Remove BOM (Byte Order Mark) if present - Excel often adds this
    if content.startswith('\ufeff'):
        content = content[1:]
        _LOGGER.debug("Removed BOM from CSV content")
    f = StringIO(content)
    reader = csv.DictReader(f)

    # Log the field names to help debug column issues
    _LOGGER.debug("CSV field names: %s", reader.fieldnames)

    devices = []
    row_count = 0
    skipped_rows: list[str] = []
    try:
        for row in reader:
            row_count += 1
            if row_count > MAX_CSV_ROWS:
                raise SchemaFlowError("csv_too_many_rows")
            device_type = row.get("device_type", "").strip().upper()
            # Get optional entity type for CCO devices (switch/light/cover/lock/climate)
            cco_type = row.get("type", "").strip().lower() or None
            # Get optional area - check multiple possible column names
            area = (
                row.get("area", "").strip()
                or row.get("Area", "").strip()
                or row.get("AREA", "").strip()
                or row.get("zone", "").strip()
                or row.get("Zone", "").strip()
            ) or None

            _LOGGER.debug(
                "CSV row: device_type=%s, name=%s, area=%s, raw_row=%s",
                device_type,
                row.get("name", ""),
                area,
                dict(row),
            )

            # Validate address format before processing
            raw_addr = row.get("address", "").strip()
            if not raw_addr:
                _LOGGER.warning("Skipping CSV row %d: missing address", row_count)
                continue
            try:
                validated_addr = _validate_address(raw_addr)
            except SchemaFlowError:
                _LOGGER.warning(
                    "Skipping CSV row %d: invalid address '%s'",
                    row_count,
                    raw_addr,
                )
                continue

            if device_type in ("CCO", "SWITCH"):
                try:
                    button = int(row.get("relay", row.get("button", 1)))
                except (ValueError, TypeError):
                    skipped_rows.append(f"row {row_count}: non-numeric relay/button value")
                    continue
                # Map type column to entity type, default to switch
                entity_type = cco_type if cco_type in (
                    CCO_TYPE_SWITCH, CCO_TYPE_LIGHT, CCO_TYPE_COVER,
                    CCO_TYPE_LOCK, CCO_TYPE_CLIMATE, CCO_TYPE_FAN
                ) else CCO_TYPE_SWITCH
                devices.append(
                    DeviceImport(
                        "CCO",
                        validated_addr,
                        button,
                        row.get("name", "").strip(),
                        entity_type,
                        area,
                    )
                )
            elif device_type in ("LIGHT", "DIMMER"):
                devices.append(
                    DeviceImport(
                        "DIMMER",
                        validated_addr,
                        None,
                        row.get("name", "").strip(),
                        None,
                        area,
                    )
                )
            elif device_type == "COVER":
                try:
                    button = int(row.get("relay", row.get("button", 1)))
                except (ValueError, TypeError):
                    skipped_rows.append(f"row {row_count}: non-numeric relay/button value")
                    continue
                devices.append(
                    DeviceImport(
                        "CCO",
                        validated_addr,
                        button,
                        row.get("name", "").strip(),
                        CCO_TYPE_COVER,
                        area,
                    )
                )
            elif device_type == "LOCK":
                try:
                    button = int(row.get("relay", row.get("button", 1)))
                except (ValueError, TypeError):
                    skipped_rows.append(f"row {row_count}: non-numeric relay/button value")
                    continue
                devices.append(
                    DeviceImport(
                        "CCO",
                        validated_addr,
                        button,
                        row.get("name", "").strip(),
                        CCO_TYPE_LOCK,
                        area,
                    )
                )
            elif device_type == "CLIMATE":
                try:
                    button = int(row.get("relay", row.get("button", 1)))
                except (ValueError, TypeError):
                    skipped_rows.append(f"row {row_count}: non-numeric relay/button value")
                    continue
                devices.append(
                    DeviceImport(
                        "CCO",
                        validated_addr,
                        button,
                        row.get("name", "").strip(),
                        CCO_TYPE_CLIMATE,
                        area,
                    )
                )
            elif device_type == "FAN":
                try:
                    button = int(row.get("relay", row.get("button", 1)))
                except (ValueError, TypeError):
                    skipped_rows.append(f"row {row_count}: non-numeric relay/button value")
                    continue
                devices.append(
                    DeviceImport(
                        "CCO",
                        validated_addr,
                        button,
                        row.get("name", "").strip(),
                        CCO_TYPE_FAN,
                        area,
                    )
                )
            elif device_type == "CCI":
                # CCI (Contact Closure Input) - binary sensors
                try:
                    input_num = int(row.get("input", row.get("relay", row.get("button", 1))))
                except (ValueError, TypeError):
                    skipped_rows.append(f"row {row_count}: non-numeric input/relay/button value")
                    continue
                device_class = row.get("device_class", row.get("class", "")).strip().lower() or None
                devices.append(
                    DeviceImport(
                        "CCI",
                        validated_addr,
                        input_num,
                        row.get("name", "").strip(),
                        None,  # entity_type not used for CCI
                        area,
                        device_class,
                    )
                )
            elif device_type in ("MOTOR_COVER", "RPM_COVER", "RPM"):
                # RPM motor covers (HW-RPM-4M-230 module)
                devices.append(
                    DeviceImport(
                        "MOTOR_COVER",
                        validated_addr,
                        None,  # No button for motor covers
                        row.get("name", "").strip(),
                        None,  # entity_type not used for motor covers
                        area,
                    )
                )
            elif device_type in ("QED", "QED_SHADE", "SIVOIA_QED", "QED_COVER"):
                # QED Sivoia shades (position-trackable)
                devices.append(
                    DeviceImport(
                        "QED_COVER",
                        validated_addr,
                        None,  # No button for QED shades
                        row.get("name", "").strip(),
                        None,  # entity_type not used for QED covers
                        area,
                    )
                )
    except SchemaFlowError:
        raise
    except Exception as err:
        _LOGGER.exception("Error processing CSV at row %d", row_count)
        raise SchemaFlowError("invalid_csv") from err

    if skipped_rows:
        _LOGGER.warning("CSV import skipped %d rows: %s", len(skipped_rows), "; ".join(skipped_rows))

    if not devices:
        raise SchemaFlowError("no_devices_in_csv")

    handler.flow_state["import_devices"] = devices
    return {}


def _is_duplicate_cco(handler: SchemaCommonFlowHandler, address: str, button: int) -> bool:
    """Check if a CCO device already exists."""
    return _find_existing_cco(handler, address, button) is not None


def _find_existing_cco(handler: SchemaCommonFlowHandler, address: str, button: int) -> int | None:
    """Find existing CCO device index, or None if not found."""
    try:
        new_addr = _validate_cco_address(address, button)
        for i, device in enumerate(handler.options.get(CONF_CCO_DEVICES, [])):
            existing_addr = _validate_cco_address(
                device[CONF_ADDR],
                device.get(CONF_BUTTON_NUMBER, device.get(CONF_RELAY_NUMBER, 1)),
            )
            if existing_addr.unique_key == new_addr.unique_key:
                return i
    except Exception:
        pass
    return None


def _find_existing_by_address(
    handler: SchemaCommonFlowHandler, config_key: str, address: str
) -> int | None:
    """Find existing device index by normalized address, or None if not found."""
    normalized = normalize_address(address)
    for i, item in enumerate(handler.options.get(config_key, [])):
        if normalize_address(item[CONF_ADDR]) == normalized:
            return i
    return None


def _is_duplicate_by_address(
    handler: SchemaCommonFlowHandler, config_key: str, address: str
) -> bool:
    """Check if a device with this address already exists."""
    return _find_existing_by_address(handler, config_key, address) is not None


def _is_duplicate_dimmer(handler: SchemaCommonFlowHandler, address: str) -> bool:
    """Check if a dimmer already exists."""
    return _is_duplicate_by_address(handler, CONF_DIMMERS, address)


def _find_existing_dimmer(handler: SchemaCommonFlowHandler, address: str) -> int | None:
    """Find existing dimmer index, or None if not found."""
    return _find_existing_by_address(handler, CONF_DIMMERS, address)


def _is_duplicate_cci(handler: SchemaCommonFlowHandler, address: str, input_number: int) -> bool:
    """Check if a CCI device already exists."""
    return _find_existing_cci(handler, address, input_number) is not None


def _find_existing_cci(handler: SchemaCommonFlowHandler, address: str, input_number: int) -> int | None:
    """Find existing CCI device index, or None if not found."""
    normalized = normalize_address(address)
    for i, device in enumerate(handler.options.get(CONF_CCI_DEVICES, [])):
        if (
            normalize_address(device[CONF_ADDR]) == normalized
            and device.get(CONF_INPUT_NUMBER, 1) == input_number
        ):
            return i
    return None


def _is_duplicate_rpm_cover(handler: SchemaCommonFlowHandler, address: str) -> bool:
    """Check if an RPM cover already exists."""
    return _is_duplicate_by_address(handler, CONF_RPM_COVERS, address)


def _find_existing_rpm_cover(handler: SchemaCommonFlowHandler, address: str) -> int | None:
    """Find existing RPM cover index, or None if not found."""
    return _find_existing_by_address(handler, CONF_RPM_COVERS, address)


def _is_duplicate_qed_cover(handler: SchemaCommonFlowHandler, address: str) -> bool:
    """Check if a QED cover already exists."""
    return _is_duplicate_by_address(handler, CONF_QED_COVERS, address)


def _find_existing_qed_cover(handler: SchemaCommonFlowHandler, address: str) -> int | None:
    """Find existing QED cover index, or None if not found."""
    return _find_existing_by_address(handler, CONF_QED_COVERS, address)


async def get_confirm_import_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for confirming imports."""
    devices = handler.flow_state.get("import_devices", [])
    selections = {}
    default_selected = []

    for idx, dev in enumerate(devices):
        if dev.device_type == "DIMMER":
            is_dup = _is_duplicate_dimmer(handler, dev.address)
            label = f"Dimmer: {dev.name} ({dev.address})"
            if is_dup:
                label += " [ALREADY EXISTS]"
            else:
                default_selected.append(str(idx))
            selections[str(idx)] = label
        elif dev.device_type == "CCI":
            is_dup = _is_duplicate_cci(handler, dev.address, dev.button or 1)
            device_class = dev.device_class or "input"
            label = f"CCI ({device_class}): {dev.name} ({dev.address}:{dev.button})"
            if is_dup:
                label += " [ALREADY EXISTS]"
            else:
                default_selected.append(str(idx))
            selections[str(idx)] = label
        elif dev.device_type == "MOTOR_COVER":
            is_dup = _is_duplicate_rpm_cover(handler, dev.address)
            label = f"Motor Cover: {dev.name} ({dev.address})"
            if is_dup:
                label += " [ALREADY EXISTS]"
            else:
                default_selected.append(str(idx))
            selections[str(idx)] = label
        elif dev.device_type == "QED_COVER":
            is_dup = _is_duplicate_qed_cover(handler, dev.address)
            label = f"QED Shade: {dev.name} ({dev.address})"
            if is_dup:
                label += " [ALREADY EXISTS]"
            else:
                default_selected.append(str(idx))
            selections[str(idx)] = label
        else:
            # CCO device
            entity_type = dev.entity_type or "switch"
            is_dup = _is_duplicate_cco(handler, dev.address, dev.button or 1)
            label = f"CCO ({entity_type}): {dev.name} ({dev.address}:{dev.button})"
            if is_dup:
                label += " [ALREADY EXISTS]"
            else:
                default_selected.append(str(idx))
            selections[str(idx)] = label

    return vol.Schema(
        {
            vol.Optional("devices", default=default_selected): cv.multi_select(
                selections
            )
        }
    )


async def validate_confirm_import(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Process selected devices, skipping duplicates."""
    devices = handler.flow_state.get("import_devices", [])

    _LOGGER.debug("Processing %d parsed devices from CSV", len(devices))
    selected = user_input.get("devices", [])
    skipped = 0

    for idx in selected:
        device = devices[int(idx)]
        if device.device_type == "DIMMER":
            # Check if duplicate - if so, update the area instead of skipping
            existing_idx = _find_existing_dimmer(handler, device.address)
            if existing_idx is not None:
                # Update existing dimmer with new area if provided
                if device.area:
                    handler.options[CONF_DIMMERS][existing_idx][CONF_AREA] = device.area
                    _LOGGER.debug(
                        "Updated existing dimmer %s with area=%s",
                        device.name,
                        device.area,
                    )
                skipped += 1
                continue
            items = handler.options.setdefault(CONF_DIMMERS, [])
            dimmer_config = {
                CONF_ADDR: device.address,
                CONF_NAME: device.name or DEFAULT_LIGHT_NAME,
                CONF_RATE: DEFAULT_FADE_RATE,
            }
            if device.area:
                dimmer_config[CONF_AREA] = device.area
            items.append(dimmer_config)
        elif device.device_type == "CCI":
            # Check if duplicate - if so, update the area instead of skipping
            existing_idx = _find_existing_cci(handler, device.address, device.button or 1)
            if existing_idx is not None:
                # Update existing CCI with new area if provided
                if device.area:
                    handler.options[CONF_CCI_DEVICES][existing_idx][CONF_AREA] = device.area
                    _LOGGER.debug(
                        "Updated existing CCI device %s with area=%s",
                        device.name,
                        device.area,
                    )
                skipped += 1
                continue
            _LOGGER.debug(
                "Importing CCI device %s with device_class=%s",
                device.name,
                device.device_class,
            )
            items = handler.options.setdefault(CONF_CCI_DEVICES, [])
            cci_config = {
                CONF_ADDR: device.address,
                CONF_INPUT_NUMBER: device.button or 1,
                CONF_NAME: device.name or DEFAULT_CCI_NAME,
            }
            if device.device_class:
                cci_config[CONF_DEVICE_CLASS] = device.device_class
            if device.area:
                cci_config[CONF_AREA] = device.area
            items.append(cci_config)
        elif device.device_type == "MOTOR_COVER":
            # Check if duplicate - if so, update the area instead of skipping
            existing_idx = _find_existing_rpm_cover(handler, device.address)
            if existing_idx is not None:
                # Update existing motor cover with new area if provided
                if device.area:
                    handler.options[CONF_RPM_COVERS][existing_idx][CONF_AREA] = device.area
                    _LOGGER.debug(
                        "Updated existing motor cover %s with area=%s",
                        device.name,
                        device.area,
                    )
                skipped += 1
                continue
            _LOGGER.debug(
                "Importing motor cover %s",
                device.name,
            )
            items = handler.options.setdefault(CONF_RPM_COVERS, [])
            rpm_config = {
                CONF_ADDR: device.address,
                CONF_NAME: device.name or DEFAULT_RPM_COVER_NAME,
            }
            if device.area:
                rpm_config[CONF_AREA] = device.area
            items.append(rpm_config)
        elif device.device_type == "QED_COVER":
            # Check if duplicate - if so, update the area instead of skipping
            existing_idx = _find_existing_qed_cover(handler, device.address)
            if existing_idx is not None:
                if device.area:
                    handler.options[CONF_QED_COVERS][existing_idx][CONF_AREA] = device.area
                    _LOGGER.debug(
                        "Updated existing QED cover %s with area=%s",
                        device.name,
                        device.area,
                    )
                skipped += 1
                continue
            _LOGGER.debug(
                "Importing QED cover %s",
                device.name,
            )
            items = handler.options.setdefault(CONF_QED_COVERS, [])
            qed_config = {
                CONF_ADDR: device.address,
                CONF_NAME: device.name or DEFAULT_QED_COVER_NAME,
            }
            if device.area:
                qed_config[CONF_AREA] = device.area
            items.append(qed_config)
        else:
            # CCO device
            # Check if duplicate - if so, update the area instead of skipping
            existing_idx = _find_existing_cco(handler, device.address, device.button or 1)
            if existing_idx is not None:
                # Update existing device with new area if provided
                if device.area:
                    handler.options[CONF_CCO_DEVICES][existing_idx][CONF_AREA] = device.area
                    _LOGGER.debug(
                        "Updated existing CCO device %s with area=%s",
                        device.name,
                        device.area,
                    )
                skipped += 1
                continue
            # Use entity_type from CSV if provided, otherwise default to switch
            entity_type = device.entity_type or CCO_TYPE_SWITCH
            _LOGGER.debug(
                "Importing CCO device %s with entity_type=%s, area=%s (from CSV: entity_type=%s, area=%s)",
                device.name,
                entity_type,
                device.area,
                device.entity_type,
                device.area,
            )
            items = handler.options.setdefault(CONF_CCO_DEVICES, [])
            cco_config = {
                CONF_ADDR: device.address,
                CONF_BUTTON_NUMBER: device.button or 1,
                CONF_NAME: device.name or DEFAULT_CCO_NAME,
                CONF_ENTITY_TYPE: entity_type,
                CONF_INVERTED: False,
            }
            if device.area:
                cco_config[CONF_AREA] = device.area
                _LOGGER.debug("Added area '%s' to CCO device %s", device.area, device.name)
            else:
                _LOGGER.warning("No area found for CCO device %s", device.name)
            items.append(cco_config)

    _LOGGER.debug(
        "CSV import complete: %d CCO devices total",
        len(handler.options.get(CONF_CCO_DEVICES, [])),
    )

    return {}


# === Review Configuration ===


async def get_review_config_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return empty schema for review."""
    return vol.Schema({})


async def validate_review_config(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """No-op for review."""
    return {}


# === XML Import ===


def _is_duplicate_keypad(handler: SchemaCommonFlowHandler, address: str) -> bool:
    """Check if a keypad already exists."""
    return _is_duplicate_by_address(handler, CONF_KEYPADS, address)


async def async_parse_xml(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Parse XML content and store parsed project in flow_state."""
    content = user_input["xml_file"]

    try:
        parsed = parse_homeworks_xml(content)
    except XMLImportError as err:
        raise SchemaFlowError(err.error_key) from err

    handler.flow_state["xml_parsed"] = parsed
    return {}


async def get_xml_area_mapping_schema(
    handler: SchemaCommonFlowHandler,
) -> vol.Schema:
    """Build dynamic schema for mapping XML rooms to HA areas.

    Each room with importable devices gets a SelectSelector dropdown.
    The schema key IS the room name (shown as the field label by HA).
    Options: existing HA areas + "Create: {RoomName}" + custom text input.
    """
    hass = handler.parent_handler.hass
    from homeassistant.helpers import area_registry as ar

    area_registry = ar.async_get(hass)
    existing_areas = sorted(
        [
            selector.SelectOptionDict(value=a.name, label=a.name)
            for a in area_registry.areas.values()
        ],
        key=lambda x: x["label"],
    )

    parsed: ParsedProject = handler.flow_state["xml_parsed"]
    schema_dict: VolDictType = {}
    # Map pretty key → internal key for downstream lookups
    key_map: dict[str, str] = {}
    used_keys: set[str] = set()

    for lutron_area in parsed.areas:
        for room in lutron_area.rooms:
            if room.importable_device_count == 0:
                continue
            internal_key = f"room_{lutron_area.area_id}_{room.room_id}"
            room_title = room.name.title()

            # Build unique display key (used as field label by HA frontend)
            display_key = room_title
            if display_key in used_keys:
                display_key = f"{lutron_area.name.title()} / {room_title}"
            used_keys.add(display_key)
            key_map[display_key] = internal_key

            create_option = selector.SelectOptionDict(
                value=f"__create__{room_title}",
                label=f"\u2795 Create new: {room_title}",
            )
            options = [create_option] + existing_areas

            # Auto-match: check if an existing HA area matches room name
            default = create_option["value"]
            room_name_lower = room_title.lower().replace("_", " ")
            for area_opt in existing_areas:
                if area_opt["label"].lower().replace("_", " ") == room_name_lower:
                    default = area_opt["value"]
                    break

            schema_dict[vol.Required(display_key, default=default)] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                )
            )

    if not schema_dict:
        raise SchemaFlowError("no_devices_in_xml")

    handler.flow_state["_xml_key_map"] = key_map
    return vol.Schema(schema_dict)


async def validate_xml_area_mapping(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store room-to-area mapping in flow_state.

    Converts display keys back to internal keys for downstream use.
    """
    key_map = handler.flow_state.get("_xml_key_map", {})
    internal_mapping: dict[str, str] = {}
    for display_key, value in user_input.items():
        internal_key = key_map.get(display_key, display_key)
        internal_mapping[internal_key] = value
    handler.flow_state["xml_area_mapping"] = internal_mapping
    return {}


async def get_xml_device_selection_schema(
    handler: SchemaCommonFlowHandler,
) -> vol.Schema:
    """Build device selection schema from parsed XML + area mappings.

    Shows all discovered devices grouped by type with multi-select checkboxes.
    Marks duplicates as [ALREADY EXISTS].
    """
    parsed: ParsedProject = handler.flow_state["xml_parsed"]
    area_mapping: dict[str, str] = handler.flow_state["xml_area_mapping"]

    selections: dict[str, str] = {}
    default_selected: list[str] = []
    device_list: list[dict[str, Any]] = []

    for lutron_area in parsed.areas:
        for room in lutron_area.rooms:
            room_key = f"room_{lutron_area.area_id}_{room.room_id}"
            area_value = area_mapping.get(room_key, "")
            # Resolve area name for display
            if area_value.startswith("__create__"):
                area_display = area_value.replace("__create__", "")
            elif area_value:
                area_display = area_value
            else:
                area_display = room.name.title()

            for output in room.outputs:
                idx = str(len(device_list))
                if output.output_type == "DIMMER":
                    addr = normalize_address(output.address)
                    is_dup = _is_duplicate_dimmer(handler, addr)
                    label = f"Light: {output.name} ({area_display}) [{addr}]"
                    if is_dup:
                        label += " [ALREADY EXISTS]"
                    else:
                        default_selected.append(idx)
                elif output.output_type == "QED SHADE":
                    addr = normalize_address(output.address)
                    is_dup = _is_duplicate_qed_cover(handler, addr)
                    label = f"QED Shade: {output.name} ({area_display}) [{addr}]"
                    if is_dup:
                        label += " [ALREADY EXISTS]"
                    else:
                        default_selected.append(idx)
                elif output.output_type == "MOTOR":
                    addr = normalize_address(output.address)
                    is_dup = _is_duplicate_rpm_cover(handler, addr)
                    label = f"Motor Cover: {output.name} ({area_display}) [{addr}]"
                    if is_dup:
                        label += " [ALREADY EXISTS]"
                    else:
                        default_selected.append(idx)
                elif output.output_type == "MAINTAINED OUTPUT":
                    try:
                        cco_addr, relay = get_cco_address_parts(output.address)
                        addr = normalize_address(cco_addr)
                        is_dup = _is_duplicate_cco(handler, addr, relay)
                    except ValueError:
                        addr = normalize_address(output.address)
                        relay = 1
                        is_dup = False
                    label = f"CCO: {output.name} ({area_display}) [{addr}]:{relay}"
                    if is_dup:
                        label += " [ALREADY EXISTS]"
                    else:
                        default_selected.append(idx)
                else:
                    continue

                device_list.append(
                    {
                        "type": output.output_type,
                        "address": output.address,
                        "name": output.name,
                        "room_key": room_key,
                        "area_display": area_display,
                    }
                )
                selections[idx] = label

            for keypad in room.keypads:
                idx = str(len(device_list))
                addr = normalize_address(keypad.address)
                is_dup = _is_duplicate_keypad(handler, addr)
                btn_count = len(keypad.buttons)
                label = f"Keypad: {keypad.name} ({area_display}) [{addr}] ({btn_count} buttons)"
                if is_dup:
                    label += " [ALREADY EXISTS]"
                else:
                    default_selected.append(idx)

                device_list.append(
                    {
                        "type": "KEYPAD",
                        "address": keypad.address,
                        "name": keypad.name,
                        "room_key": room_key,
                        "area_display": area_display,
                        "buttons": [
                            {
                                "number": b.number,
                                "name": b.name,
                                "has_led": b.has_led,
                                "release_delay": b.release_delay,
                            }
                            for b in keypad.buttons
                        ],
                    }
                )
                selections[idx] = label

            for cci in room.cci_inputs:
                idx = str(len(device_list))
                addr = normalize_address(cci.address)
                is_dup = _is_duplicate_cci(handler, addr, cci.input_number)
                label = f"CCI Input {cci.input_number} ({area_display}) [{addr}]"
                if is_dup:
                    label += " [ALREADY EXISTS]"
                else:
                    default_selected.append(idx)

                device_list.append(
                    {
                        "type": "CCI",
                        "address": cci.address,
                        "name": cci.name,
                        "room_key": room_key,
                        "area_display": area_display,
                        "input_number": cci.input_number,
                    }
                )
                selections[idx] = label

    handler.flow_state["xml_device_list"] = device_list

    if not selections:
        raise SchemaFlowError("no_devices_in_xml")

    return vol.Schema(
        {
            vol.Optional(
                "devices", default=default_selected
            ): cv.multi_select(selections)
        }
    )


async def validate_xml_device_selection(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store selected device indices and determine next step."""
    selected = user_input.get("devices", [])
    handler.flow_state["xml_selected_devices"] = selected

    # Determine which CCO devices were selected (need classification)
    device_list = handler.flow_state["xml_device_list"]
    cco_devices = []
    cci_devices = []
    for idx_str in selected:
        idx = int(idx_str)
        device = device_list[idx]
        if device["type"] == "MAINTAINED OUTPUT":
            cco_devices.append({"idx": idx, **device})
        elif device["type"] == "CCI":
            cci_devices.append({"idx": idx, **device})

    handler.flow_state["xml_cco_to_classify"] = cco_devices
    handler.flow_state["xml_cci_to_classify"] = cci_devices
    return {}


async def get_xml_cco_classify_schema(
    handler: SchemaCommonFlowHandler,
) -> vol.Schema | None:
    """Build schema for classifying CCO devices.

    Returns None if no CCO devices need classification (auto-skips step).
    Each selected CCO/MAINTAINED OUTPUT device gets a SelectSelector
    for choosing entity type (switch/light/lock/cover/climate/fan).
    """
    cco_devices = handler.flow_state.get("xml_cco_to_classify", [])
    if not cco_devices:
        return None

    schema_dict: VolDictType = {}

    for i, dev in enumerate(cco_devices):
        key = f"cco_{i}"
        schema_dict[
            vol.Required(key, default=CCO_TYPE_SWITCH)
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=CCO_ENTITY_TYPES,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    return vol.Schema(schema_dict)


async def validate_xml_cco_classify(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store CCO classifications."""
    cco_devices = handler.flow_state.get("xml_cco_to_classify", [])
    for i, dev in enumerate(cco_devices):
        key = f"cco_{i}"
        dev["entity_type"] = user_input.get(key, CCO_TYPE_SWITCH)
    return {}


async def get_xml_cci_classify_schema(
    handler: SchemaCommonFlowHandler,
) -> vol.Schema | None:
    """Build schema for classifying CCI devices.

    Returns None if no CCI devices need classification (auto-skips step).
    Each selected CCI input gets a TextSelector for name and a SelectSelector
    for device_class.
    """
    cci_devices = handler.flow_state.get("xml_cci_to_classify", [])
    if not cci_devices:
        return None

    schema_dict: VolDictType = {}

    for i, dev in enumerate(cci_devices):
        name_key = f"cci_name_{i}"
        class_key = f"cci_class_{i}"
        default_name = dev.get("name", f"CCI Input {dev.get('input_number', i + 1)}")
        schema_dict[vol.Required(name_key, default=default_name)] = (
            selector.TextSelector()
        )
        schema_dict[vol.Optional(class_key)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value="door", label="Door"),
                    selector.SelectOptionDict(value="window", label="Window"),
                    selector.SelectOptionDict(value="motion", label="Motion"),
                    selector.SelectOptionDict(value="opening", label="Opening"),
                    selector.SelectOptionDict(value="occupancy", label="Occupancy"),
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    return vol.Schema(schema_dict)


async def validate_xml_cci_classify(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store CCI classifications (name + device_class)."""
    cci_devices = handler.flow_state.get("xml_cci_to_classify", [])
    for i, dev in enumerate(cci_devices):
        name_key = f"cci_name_{i}"
        class_key = f"cci_class_{i}"
        dev["name"] = user_input.get(name_key, dev.get("name", ""))
        dev["device_class"] = user_input.get(class_key)
    return {}


async def get_xml_confirm_schema(
    handler: SchemaCommonFlowHandler,
) -> vol.Schema:
    """Build confirmation summary schema (empty — just displays description)."""
    return vol.Schema({})


async def get_xml_confirm_description_placeholders(
    handler: SchemaCommonFlowHandler,
) -> dict[str, str]:
    """Compute summary counts for the confirm step description."""
    device_list = handler.flow_state.get("xml_device_list", [])
    selected = handler.flow_state.get("xml_selected_devices", [])
    counts: Counter[str] = Counter()
    total_buttons = 0
    for idx_str in selected:
        idx = int(idx_str)
        device = device_list[idx]
        counts[device["type"]] += 1
        if device["type"] == "KEYPAD":
            total_buttons += len(device.get("buttons", []))

    return {
        "lights": str(counts.get("DIMMER", 0)),
        "qed_shades": str(counts.get("QED SHADE", 0)),
        "motor_covers": str(counts.get("MOTOR", 0)),
        "cco_devices": str(counts.get("MAINTAINED OUTPUT", 0)),
        "keypads": str(counts.get("KEYPAD", 0)),
        "total_buttons": str(total_buttons),
        "cci_inputs": str(counts.get("CCI", 0)),
    }


async def validate_xml_confirm_import(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Commit all selected XML devices to config entry options."""
    device_list = handler.flow_state["xml_device_list"]
    selected = handler.flow_state.get("xml_selected_devices", [])
    area_mapping: dict[str, str] = handler.flow_state["xml_area_mapping"]
    cco_devices = handler.flow_state.get("xml_cco_to_classify", [])
    cci_devices = handler.flow_state.get("xml_cci_to_classify", [])

    # Build CCO entity_type lookup by device_list index
    cco_type_map: dict[int, str] = {}
    for dev in cco_devices:
        cco_type_map[dev["idx"]] = dev.get("entity_type", CCO_TYPE_SWITCH)

    # Build CCI data lookup by device_list index (name + device_class from
    # classification step are on the copies, not the originals in device_list)
    cci_data_map: dict[int, dict[str, Any]] = {}
    for dev in cci_devices:
        cci_data_map[dev["idx"]] = dev

    for idx_str in selected:
        idx = int(idx_str)
        device = device_list[idx]
        device_type = device["type"]
        room_key = device["room_key"]

        # Resolve area — value is always a human-readable name
        # (either "__create__Name", existing area name, or custom typed name).
        area_value = area_mapping.get(room_key, "")
        area: str | None = None
        if area_value.startswith("__create__"):
            area = area_value.replace("__create__", "")
        elif area_value:
            area = area_value

        if device_type == "DIMMER":
            addr = normalize_address(device["address"])
            if _is_duplicate_dimmer(handler, addr):
                continue
            items = handler.options.setdefault(CONF_DIMMERS, [])
            dimmer_config: dict[str, Any] = {
                CONF_ADDR: addr,
                CONF_NAME: device["name"] or DEFAULT_LIGHT_NAME,
                CONF_RATE: DEFAULT_FADE_RATE,
            }
            if area:
                dimmer_config[CONF_AREA] = area
            items.append(dimmer_config)

        elif device_type == "QED SHADE":
            addr = normalize_address(device["address"])
            if _is_duplicate_qed_cover(handler, addr):
                continue
            items = handler.options.setdefault(CONF_QED_COVERS, [])
            qed_config: dict[str, Any] = {
                CONF_ADDR: addr,
                CONF_NAME: device["name"] or DEFAULT_QED_COVER_NAME,
            }
            if area:
                qed_config[CONF_AREA] = area
            items.append(qed_config)

        elif device_type == "MOTOR":
            addr = normalize_address(device["address"])
            if _is_duplicate_rpm_cover(handler, addr):
                continue
            items = handler.options.setdefault(CONF_RPM_COVERS, [])
            rpm_config: dict[str, Any] = {
                CONF_ADDR: addr,
                CONF_NAME: device["name"] or DEFAULT_RPM_COVER_NAME,
            }
            if area:
                rpm_config[CONF_AREA] = area
            items.append(rpm_config)

        elif device_type == "MAINTAINED OUTPUT":
            try:
                cco_addr, relay = get_cco_address_parts(device["address"])
                addr = normalize_address(cco_addr)
            except ValueError:
                continue
            if _is_duplicate_cco(handler, addr, relay):
                continue
            entity_type = cco_type_map.get(idx, CCO_TYPE_SWITCH)
            items = handler.options.setdefault(CONF_CCO_DEVICES, [])
            cco_config: dict[str, Any] = {
                CONF_ADDR: addr,
                CONF_BUTTON_NUMBER: relay,
                CONF_NAME: device["name"] or DEFAULT_CCO_NAME,
                CONF_ENTITY_TYPE: entity_type,
                CONF_INVERTED: False,
            }
            if area:
                cco_config[CONF_AREA] = area
            items.append(cco_config)

        elif device_type == "KEYPAD":
            addr = normalize_address(device["address"])
            if _is_duplicate_keypad(handler, addr):
                continue
            items = handler.options.setdefault(CONF_KEYPADS, [])
            buttons_config = []
            for btn in device.get("buttons", []):
                buttons_config.append(
                    {
                        CONF_NUMBER: btn["number"],
                        CONF_NAME: btn["name"],
                        CONF_LED: btn["has_led"],
                        CONF_RELEASE_DELAY: btn["release_delay"],
                    }
                )
            keypad_config: dict[str, Any] = {
                CONF_ADDR: addr,
                CONF_NAME: device["name"] or DEFAULT_KEYPAD_NAME,
                CONF_BUTTONS: buttons_config,
            }
            if area:
                keypad_config[CONF_AREA] = area
            items.append(keypad_config)

        elif device_type == "CCI":
            addr = normalize_address(device["address"])
            input_number = device.get("input_number", 1)
            if _is_duplicate_cci(handler, addr, input_number):
                continue
            # Use classified data (name + device_class) from the CCI
            # classification step if available, otherwise fall back to
            # the original device_list entry.
            cci_data = cci_data_map.get(idx, device)
            items = handler.options.setdefault(CONF_CCI_DEVICES, [])
            cci_config: dict[str, Any] = {
                CONF_ADDR: addr,
                CONF_INPUT_NUMBER: input_number,
                CONF_NAME: cci_data.get("name") or DEFAULT_CCI_NAME,
            }
            if cci_data.get("device_class"):
                cci_config[CONF_DEVICE_CLASS] = cci_data["device_class"]
            if area:
                cci_config[CONF_AREA] = area
            items.append(cci_config)

    return {}


# === Schema Definitions ===

DATA_SCHEMA_ADD_CONTROLLER = vol.Schema(
    {
        vol.Required(
            CONF_NAME, description={"suggested_value": "Lutron Homeworks"}
        ): selector.TextSelector(),
        vol.Required(CONF_HOST): selector.TextSelector(),
        vol.Required(CONF_PORT, default=23): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=65535, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_USERNAME): selector.TextSelector(),
        vol.Optional(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)

DATA_SCHEMA_REAUTH = vol.Schema(
    {
        vol.Optional(CONF_USERNAME): selector.TextSelector(),
        vol.Optional(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)

DATA_SCHEMA_RECONFIGURE = vol.Schema(
    {
        vol.Required(CONF_HOST): selector.TextSelector(),
        vol.Required(CONF_PORT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=65535, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_USERNAME): selector.TextSelector(),
        vol.Optional(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)

LIGHT_EDIT: VolDictType = {
    vol.Optional(CONF_RATE, default=DEFAULT_FADE_RATE): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=20,
            mode=selector.NumberSelectorMode.BOX,
            step=0.01,
            unit_of_measurement="s",
        )
    ),
}

DATA_SCHEMA_ADD_LIGHT = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_LIGHT_NAME): selector.TextSelector(),
        vol.Required(CONF_ADDR): selector.TextSelector(),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
        **LIGHT_EDIT,
    }
)

DATA_SCHEMA_EDIT_LIGHT = vol.Schema(
    {vol.Optional(CONF_NAME): selector.TextSelector(), **LIGHT_EDIT}
)

BUTTON_EDIT: VolDictType = {
    vol.Optional(CONF_LED, default=False): selector.BooleanSelector(),
    vol.Optional(CONF_RELEASE_DELAY, default=0): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=5,
            step=0.01,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    ),
}

DATA_SCHEMA_ADD_BUTTON = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_BUTTON_NAME): selector.TextSelector(),
        vol.Required(CONF_NUMBER): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        **BUTTON_EDIT,
    }
)

DATA_SCHEMA_EDIT_BUTTON = vol.Schema(
    {vol.Optional(CONF_NAME): selector.TextSelector(), **BUTTON_EDIT}
)

DATA_SCHEMA_ADD_KEYPAD = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_KEYPAD_NAME): selector.TextSelector(),
        vol.Required(CONF_ADDR): selector.TextSelector(),
    }
)

DATA_SCHEMA_ADD_CCO_DEVICE = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_CCO_NAME): selector.TextSelector(),
        vol.Required(CONF_ADDR): selector.TextSelector(),
        vol.Required(CONF_BUTTON_NUMBER, default=1): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_ENTITY_TYPE, default=CCO_TYPE_SWITCH
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=CCO_ENTITY_TYPES,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="cco_entity_type",
            )
        ),
        vol.Optional(CONF_INVERTED, default=False): selector.BooleanSelector(),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
    }
)

DATA_SCHEMA_EDIT_CCO_DEVICE = vol.Schema(
    {
        vol.Optional(CONF_NAME): selector.TextSelector(),
        vol.Optional(CONF_ADDR): selector.TextSelector(),
        vol.Optional(CONF_BUTTON_NUMBER): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_ENTITY_TYPE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=CCO_ENTITY_TYPES,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="cco_entity_type",
            )
        ),
        vol.Optional(CONF_INVERTED): selector.BooleanSelector(),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
    }
)

DATA_SCHEMA_CONTROLLER_SETTINGS = vol.Schema(
    {
        vol.Required(
            CONF_KLS_POLL_INTERVAL, default=DEFAULT_KLS_POLL_INTERVAL
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5,
                max=300,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_KLS_WINDOW_OFFSET, default=DEFAULT_KLS_WINDOW_OFFSET
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=16, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }
)

DATA_SCHEMA_ADD_RPM_COVER = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_RPM_COVER_NAME): selector.TextSelector(),
        vol.Required(CONF_ADDR): selector.TextSelector(),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
    }
)

DATA_SCHEMA_EDIT_RPM_COVER = vol.Schema(
    {
        vol.Optional(CONF_NAME): selector.TextSelector(),
    }
)

DATA_SCHEMA_ADD_QED_COVER = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_QED_COVER_NAME): selector.TextSelector(),
        vol.Required(CONF_ADDR): selector.TextSelector(),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
    }
)

DATA_SCHEMA_EDIT_QED_COVER = vol.Schema(
    {
        vol.Optional(CONF_NAME): selector.TextSelector(),
    }
)

DATA_SCHEMA_ADD_CCI_DEVICE = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_CCI_NAME): selector.TextSelector(),
        vol.Required(CONF_ADDR): selector.TextSelector(),
        vol.Required(CONF_INPUT_NUMBER, default=1): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_DEVICE_CLASS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value="door", label="Door"),
                    selector.SelectOptionDict(value="window", label="Window"),
                    selector.SelectOptionDict(value="motion", label="Motion"),
                    selector.SelectOptionDict(value="opening", label="Opening"),
                    selector.SelectOptionDict(value="occupancy", label="Occupancy"),
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
    }
)

DATA_SCHEMA_EDIT_CCI_DEVICE = vol.Schema(
    {
        vol.Optional(CONF_NAME): selector.TextSelector(),
        vol.Optional(CONF_DEVICE_CLASS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value="door", label="Door"),
                    selector.SelectOptionDict(value="window", label="Window"),
                    selector.SelectOptionDict(value="motion", label="Motion"),
                    selector.SelectOptionDict(value="opening", label="Opening"),
                    selector.SelectOptionDict(value="occupancy", label="Occupancy"),
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_AREA): selector.AreaSelector(),
    }
)

# === Options Flow Definition ===

OPTIONS_FLOW = {
    "init": SchemaFlowMenuStep(
        [
            "manage_cco_devices",
            "manage_dimmers",
            "manage_rpm_covers",
            "manage_qed_covers",
            "manage_cci_devices",
            "manage_keypads",
            "controller_settings",
            "import_csv",
            "import_xml",
            "review_config",
        ]
    ),
    "manage_cco_devices": SchemaFlowMenuStep(
        ["add_cco_device", "select_edit_cco_device", "remove_cco_device"]
    ),
    "add_cco_device": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_CCO_DEVICE, validate_user_input=validate_add_cco_device
    ),
    "select_edit_cco_device": SchemaFlowFormStep(
        get_select_cco_device_schema,
        validate_user_input=validate_select_cco_device,
        next_step="edit_cco_device",
    ),
    "edit_cco_device": SchemaFlowFormStep(
        DATA_SCHEMA_EDIT_CCO_DEVICE,
        suggested_values=get_edit_cco_device_suggested_values,
        validate_user_input=validate_cco_device_edit,
    ),
    "remove_cco_device": SchemaFlowFormStep(
        get_remove_cco_device_schema, validate_user_input=validate_remove_cco_device
    ),
    "manage_dimmers": SchemaFlowMenuStep(
        ["add_light", "select_edit_light", "remove_light"]
    ),
    "add_light": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_LIGHT, validate_user_input=validate_add_light
    ),
    "select_edit_light": SchemaFlowFormStep(
        get_select_light_schema,
        validate_user_input=validate_select_light,
        next_step="edit_light",
    ),
    "edit_light": SchemaFlowFormStep(
        DATA_SCHEMA_EDIT_LIGHT,
        suggested_values=get_edit_light_suggested_values,
        validate_user_input=validate_light_edit,
    ),
    "remove_light": SchemaFlowFormStep(
        get_remove_light_schema, validate_user_input=validate_remove_light
    ),
    "manage_rpm_covers": SchemaFlowMenuStep(
        ["add_rpm_cover", "select_edit_rpm_cover", "remove_rpm_cover"]
    ),
    "add_rpm_cover": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_RPM_COVER, validate_user_input=validate_add_rpm_cover
    ),
    "select_edit_rpm_cover": SchemaFlowFormStep(
        get_select_rpm_cover_schema,
        validate_user_input=validate_select_rpm_cover,
        next_step="edit_rpm_cover",
    ),
    "edit_rpm_cover": SchemaFlowFormStep(
        DATA_SCHEMA_EDIT_RPM_COVER,
        suggested_values=get_edit_rpm_cover_suggested_values,
        validate_user_input=validate_rpm_cover_edit,
    ),
    "remove_rpm_cover": SchemaFlowFormStep(
        get_remove_rpm_cover_schema, validate_user_input=validate_remove_rpm_cover
    ),
    "manage_qed_covers": SchemaFlowMenuStep(
        ["add_qed_cover", "select_edit_qed_cover", "remove_qed_cover"]
    ),
    "add_qed_cover": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_QED_COVER, validate_user_input=validate_add_qed_cover
    ),
    "select_edit_qed_cover": SchemaFlowFormStep(
        get_select_qed_cover_schema,
        validate_user_input=validate_select_qed_cover,
        next_step="edit_qed_cover",
    ),
    "edit_qed_cover": SchemaFlowFormStep(
        DATA_SCHEMA_EDIT_QED_COVER,
        suggested_values=get_edit_qed_cover_suggested_values,
        validate_user_input=validate_qed_cover_edit,
    ),
    "remove_qed_cover": SchemaFlowFormStep(
        get_remove_qed_cover_schema, validate_user_input=validate_remove_qed_cover
    ),
    "manage_cci_devices": SchemaFlowMenuStep(
        ["add_cci_device", "select_edit_cci_device", "remove_cci_device"]
    ),
    "add_cci_device": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_CCI_DEVICE, validate_user_input=validate_add_cci_device
    ),
    "select_edit_cci_device": SchemaFlowFormStep(
        get_select_cci_device_schema,
        validate_user_input=validate_select_cci_device,
        next_step="edit_cci_device",
    ),
    "edit_cci_device": SchemaFlowFormStep(
        DATA_SCHEMA_EDIT_CCI_DEVICE,
        suggested_values=get_edit_cci_device_suggested_values,
        validate_user_input=validate_cci_device_edit,
    ),
    "remove_cci_device": SchemaFlowFormStep(
        get_remove_cci_device_schema, validate_user_input=validate_remove_cci_device
    ),
    "manage_keypads": SchemaFlowMenuStep(
        ["add_keypad", "select_edit_keypad", "remove_keypad"]
    ),
    "add_keypad": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_KEYPAD, validate_user_input=validate_add_keypad
    ),
    "select_edit_keypad": SchemaFlowFormStep(
        get_select_keypad_schema,
        validate_user_input=validate_select_keypad,
        next_step="edit_keypad",
    ),
    "edit_keypad": SchemaFlowMenuStep(
        ["add_button", "select_edit_button", "remove_button"]
    ),
    "remove_keypad": SchemaFlowFormStep(
        get_remove_keypad_schema, validate_user_input=validate_remove_keypad
    ),
    "add_button": SchemaFlowFormStep(
        DATA_SCHEMA_ADD_BUTTON, validate_user_input=validate_add_button
    ),
    "select_edit_button": SchemaFlowFormStep(
        get_select_button_schema,
        validate_user_input=validate_select_button,
        next_step="edit_button",
    ),
    "edit_button": SchemaFlowFormStep(
        DATA_SCHEMA_EDIT_BUTTON,
        suggested_values=get_edit_button_suggested_values,
        validate_user_input=validate_button_edit,
    ),
    "remove_button": SchemaFlowFormStep(
        get_remove_button_schema, validate_user_input=validate_remove_button
    ),
    "controller_settings": SchemaFlowFormStep(
        DATA_SCHEMA_CONTROLLER_SETTINGS,
        suggested_values=get_controller_settings_suggested_values,
        validate_user_input=validate_controller_settings,
    ),
    "import_csv": SchemaFlowFormStep(
        vol.Schema(
            {
                vol.Required("csv_file"): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                )
            }
        ),
        validate_user_input=async_parse_csv,
        next_step="confirm_import",
    ),
    "confirm_import": SchemaFlowFormStep(
        get_confirm_import_schema, validate_user_input=validate_confirm_import
    ),
    "review_config": SchemaFlowFormStep(
        get_review_config_schema, validate_user_input=validate_review_config
    ),
    "import_xml": SchemaFlowFormStep(
        vol.Schema(
            {
                vol.Required("xml_file"): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                )
            }
        ),
        validate_user_input=async_parse_xml,
        next_step="xml_area_mapping",
    ),
    "xml_area_mapping": SchemaFlowFormStep(
        get_xml_area_mapping_schema,
        validate_user_input=validate_xml_area_mapping,
        next_step="xml_device_selection",
    ),
    "xml_device_selection": SchemaFlowFormStep(
        get_xml_device_selection_schema,
        validate_user_input=validate_xml_device_selection,
        next_step="xml_classify_cco",
    ),
    "xml_classify_cco": SchemaFlowFormStep(
        get_xml_cco_classify_schema,
        validate_user_input=validate_xml_cco_classify,
        next_step="xml_classify_cci",
    ),
    "xml_classify_cci": SchemaFlowFormStep(
        get_xml_cci_classify_schema,
        validate_user_input=validate_xml_cci_classify,
        next_step="xml_confirm_import",
    ),
    "xml_confirm_import": SchemaFlowFormStep(
        get_xml_confirm_schema,
        validate_user_input=validate_xml_confirm_import,
        description_placeholders=get_xml_confirm_description_placeholders,
    ),
}


class HomeworksConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Lutron Homeworks.

    Credentials (host, port, username, password) are stored in entry.data.
    Non-secrets (devices, settings) are stored in entry.options.
    """

    VERSION = 3

    def __init__(self) -> None:
        """Initialize."""
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user setup."""
        errors = {}
        if user_input:
            name = user_input[CONF_NAME]
            host = user_input[CONF_HOST]
            port = int(user_input[CONF_PORT])
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)
            controller_id = slugify(name)

            # Check for duplicates
            for entry in self._async_current_entries():
                if (
                    entry.data.get(CONF_HOST) == host
                    and entry.data.get(CONF_PORT) == port
                ):
                    return self.async_abort(reason="already_configured")
                if entry.options.get(CONF_CONTROLLER_ID) == controller_id:
                    errors["base"] = "duplicated_controller_id"
                    break

            if errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=DATA_SCHEMA_ADD_CONTROLLER,
                    errors=errors,
                )

            try:
                await _try_connection(host, port, username, password)
            except SchemaFlowError as err:
                errors["base"] = str(err)
            else:
                # Credentials in entry.data (secrets)
                data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                # Non-secrets in entry.options
                options = {
                    CONF_CONTROLLER_ID: controller_id,
                    CONF_CCO_DEVICES: [],
                    CONF_DIMMERS: [],
                    CONF_KEYPADS: [],
                    CONF_RPM_COVERS: [],
                    CONF_QED_COVERS: [],
                    CONF_CCI_DEVICES: [],
                    CONF_KLS_POLL_INTERVAL: DEFAULT_KLS_POLL_INTERVAL,
                    CONF_KLS_WINDOW_OFFSET: DEFAULT_KLS_WINDOW_OFFSET,
                }
                return self.async_create_entry(title=name, data=data, options=options)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA_ADD_CONTROLLER, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation."""
        errors = {}

        if user_input is not None and self._reauth_entry is not None:
            host = self._reauth_entry.data[CONF_HOST]
            port = self._reauth_entry.data[CONF_PORT]
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)

            try:
                await _try_connection(host, port, username, password)
            except SchemaFlowError as err:
                errors["base"] = str(err)
            else:
                # Update entry.data with new credentials
                new_data = dict(self._reauth_entry.data)
                new_data[CONF_USERNAME] = username
                new_data[CONF_PASSWORD] = password

                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=DATA_SCHEMA_REAUTH,
            errors=errors,
            description_placeholders={
                "host": self._reauth_entry.data.get(CONF_HOST, "")
                if self._reauth_entry
                else ""
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfigure."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        errors = {}
        suggested = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_PORT: entry.data[CONF_PORT],
            CONF_USERNAME: entry.data.get(CONF_USERNAME),
            CONF_PASSWORD: entry.data.get(CONF_PASSWORD),
        }

        if user_input:
            host = user_input[CONF_HOST]
            port = int(user_input[CONF_PORT])
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)

            # Check for duplicates (excluding self)
            for other in self._async_current_entries():
                if other.entry_id == entry.entry_id:
                    continue
                if (
                    other.data.get(CONF_HOST) == host
                    and other.data.get(CONF_PORT) == port
                ):
                    errors["base"] = "duplicated_host_port"
                    break

            if not errors:
                try:
                    await _try_connection(host, port, username, password)
                except SchemaFlowError as err:
                    errors["base"] = str(err)

            if not errors:
                new_data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

            suggested = {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            }

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA_RECONFIGURE, suggested
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SchemaOptionsFlowHandler:
        """Options flow handler."""
        return SchemaOptionsFlowHandlerWithReload(config_entry, OPTIONS_FLOW)

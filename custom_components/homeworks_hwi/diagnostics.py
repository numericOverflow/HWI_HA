"""Diagnostics support for Lutron Homeworks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import HomeworksData, HomeworksHWIConfigEntry
from .const import (
    CONF_CCO_DEVICES,
    CONF_CCOS,
    CONF_CONTROLLER_ID,
    CONF_COVERS,
    CONF_DIMMERS,
    CONF_KEYPADS,
    CONF_LOCKS,
    DOMAIN,
)

# Keys to redact from diagnostics
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_HOST,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeworksHWIConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    coordinator = data.coordinator

    # Collect health metrics
    health = coordinator.health
    health_data = {
        "connected": health.connected,
        "last_message_time": (
            health.last_message_time.isoformat() if health.last_message_time else None
        ),
        "last_kls_time": (
            health.last_kls_time.isoformat() if health.last_kls_time else None
        ),
        "reconnect_count": health.reconnect_count,
        "poll_failure_count": health.poll_failure_count,
        "parse_error_count": health.parse_error_count,
        "last_error": health.last_error,
    }

    # Collect device counts
    device_counts = {
        "cco_devices": len(entry.options.get(CONF_CCO_DEVICES, [])),
        "legacy_ccos": len(entry.options.get(CONF_CCOS, [])),
        "legacy_covers": len(entry.options.get(CONF_COVERS, [])),
        "legacy_locks": len(entry.options.get(CONF_LOCKS, [])),
        "dimmers": len(entry.options.get(CONF_DIMMERS, [])),
        "keypads": len(entry.options.get(CONF_KEYPADS, [])),
    }

    # Collect registered CCO states (without addresses)
    cco_state_summary = {
        "total_registered": coordinator.cco_device_count,
        "states_cached": coordinator.cco_state_count,
    }

    # Collect KLS cache info
    kls_cache_info = {
        "addresses_monitored": coordinator.kls_poll_address_count,
        "states_cached": coordinator.keypad_led_state_count,
    }

    # Collect dimmer state info
    dimmer_state_info = {
        "addresses_registered": coordinator.dimmer_address_count,
        "states_cached": coordinator.dimmer_state_count,
    }

    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "controller_id": entry.options.get(CONF_CONTROLLER_ID),
            "title": entry.title,
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "health": health_data,
        "device_counts": device_counts,
        "cco_state_summary": cco_state_summary,
        "kls_cache_info": kls_cache_info,
        "dimmer_state_info": dimmer_state_info,
    }

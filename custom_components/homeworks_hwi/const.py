"""Constants for the Lutron Homeworks integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "homeworks_hwi"

# Configuration keys
CONF_CONTROLLER_ID: Final = "controller_id"
CONF_ADDR: Final = "addr"
CONF_DIMMERS: Final = "dimmers"
CONF_KEYPADS: Final = "keypads"
CONF_BUTTONS: Final = "buttons"
CONF_NUMBER: Final = "number"
CONF_INDEX: Final = "index"
CONF_RATE: Final = "rate"
CONF_LED: Final = "led"
CONF_RELEASE_DELAY: Final = "release_delay"

# CCO-specific configuration
CONF_CCOS: Final = "ccos"
CONF_CCO_DEVICES: Final = "cco_devices"
CONF_RELAY_NUMBER: Final = "relay_number"
CONF_BUTTON_NUMBER: Final = "button_number"
CONF_ENTITY_TYPE: Final = "entity_type"
CONF_INVERTED: Final = "inverted"
CONF_AREA: Final = "area"

# Legacy CCO config (for migration)
CONF_LED_ADDR: Final = "led_addr"
CONF_LED_NUMBER: Final = "led_number"

# Cover-specific configuration
CONF_COVERS: Final = "covers"

# RPM Motor Cover configuration
CONF_RPM_COVERS: Final = "rpm_covers"

# QED Shade configuration
CONF_QED_COVERS: Final = "qed_covers"

# Lock-specific configuration
CONF_LOCKS: Final = "locks"

# CCI-specific configuration
CONF_CCI_DEVICES: Final = "cci_devices"
CONF_INPUT_NUMBER: Final = "input_number"
CONF_DEVICE_CLASS: Final = "device_class"

# Controller settings
CONF_KLS_POLL_INTERVAL: Final = "kls_poll_interval"
CONF_KLS_WINDOW_OFFSET: Final = "kls_window_offset"

# Controller clock sync settings
CONF_CLOCK_SYNC_ENABLED: Final = "clock_sync_enabled"
DEFAULT_CLOCK_SYNC_ENABLED: Final = False
CONF_CLOCK_SYNC_TIMEZONE: Final = "clock_sync_timezone"
CLOCK_SYNC_TZ_AUTO: Final = "auto"
CONF_CLOCK_SYNC_FREQUENCY: Final = "clock_sync_frequency"
CLOCK_SYNC_FREQ_WEEKLY: Final = "weekly"
CLOCK_SYNC_FREQ_MONTHLY_FIRST: Final = "monthly_first"
CONF_CLOCK_SYNC_WEEKDAY: Final = "clock_sync_weekday"
DEFAULT_CLOCK_SYNC_WEEKDAY: Final = "sun"
# The index of each weekday equals date.weekday()
CLOCK_SYNC_WEEKDAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CONF_CLOCK_SYNC_TIME: Final = "clock_sync_time"
DEFAULT_CLOCK_SYNC_TIME: Final = "04:00:00"
CONF_CLOCK_SYNC_MANAGE_DST: Final = "clock_sync_manage_dst"
DEFAULT_CLOCK_SYNC_MANAGE_DST: Final = False
# The slowest observed clock reply was 47 ms
CLOCK_REPLY_TIMEOUT_S: Final = 2.0
# Stays above the 1 s phase error of ST (whole seconds only)
CLOCK_SYNC_RETRY_THRESHOLD_S: Final = 2.0
CLOCK_SYNC_MAX_RETRIES: Final = 1
DST_JOB_SETTLE: Final = timedelta(minutes=5)
DST_SEARCH_HORIZON: Final = timedelta(days=366)
DST_SEARCH_STEP: Final = timedelta(hours=1)

# Controller clock sync status (states of the "Last clock sync" sensor)
CLOCK_SYNC_STATUS_NEVER_SYNCED: Final = "never_synced"
CLOCK_SYNC_STATUS_SYNCING: Final = "syncing"
CLOCK_SYNC_STATUS_SUCCESS: Final = "success"
CLOCK_SYNC_STATUS_FAILED: Final = "failed"
CLOCK_SYNC_STATUS_SKIPPED: Final = "skipped"
CLOCK_SYNC_STATUSES: Final = (
    CLOCK_SYNC_STATUS_NEVER_SYNCED,
    CLOCK_SYNC_STATUS_SYNCING,
    CLOCK_SYNC_STATUS_SUCCESS,
    CLOCK_SYNC_STATUS_FAILED,
    CLOCK_SYNC_STATUS_SKIPPED,
)
# What started a clock sync attempt
CLOCK_SYNC_TRIGGER_BUTTON: Final = "button"
CLOCK_SYNC_TRIGGER_SCHEDULED: Final = "scheduled"
CLOCK_SYNC_TRIGGER_DST_TRANSITION: Final = "dst_transition"
CLOCK_SYNC_TRIGGER_RECONNECT: Final = "reconnect"
# Clock sync status attributes
ATTR_SYNCED_AT: Final = "synced_at"
ATTR_LAST_ATTEMPT: Final = "last_attempt"
ATTR_TRIGGER: Final = "trigger"
ATTR_OFFSET_BEFORE: Final = "offset_before"
ATTR_OFFSET_AFTER: Final = "offset_after"
ATTR_LAST_ERROR: Final = "last_error"

# Default values
DEFAULT_FADE_RATE: Final = 0
# Fade rate that older versions saved as the default. It went out as "0.0"
# (instant), so the v3.2 migration rewrites it to DEFAULT_FADE_RATE.
LEGACY_DEFAULT_FADE_RATE: Final = 0.01
# HA brightness 1-255 maps to L232 intensity 1-100 percent.
DIMMER_BRIGHTNESS_SCALE: Final = (1, 100)
DEFAULT_BUTTON_NAME: Final = "Homeworks button"
DEFAULT_KEYPAD_NAME: Final = "Homeworks keypad"
DEFAULT_LIGHT_NAME: Final = "Homeworks light"
DEFAULT_CCO_NAME: Final = "Homeworks CCO"
DEFAULT_COVER_NAME: Final = "Homeworks Cover"
DEFAULT_RPM_COVER_NAME: Final = "Homeworks Motor Cover"
DEFAULT_QED_COVER_NAME: Final = "Homeworks QED Shade"
DEFAULT_FAN_NAME: Final = "Homeworks Fan"
DEFAULT_CLIMATE_NAME: Final = "Homeworks Climate"
DEFAULT_LOCK_NAME: Final = "Homeworks Lock"
DEFAULT_SWITCH_NAME: Final = "Homeworks Switch"
DEFAULT_CCI_NAME: Final = "Homeworks Input"

# Polling intervals (in seconds)
DEFAULT_KLS_POLL_INTERVAL: Final = 10
DEFAULT_DIMMER_POLL_INTERVAL: Final = 30

# Default release delay for Master Raise/Lower buttons (seconds).
# These buttons require a KBR (release) command to stop dimmer ramping.
# Without a non-zero delay, KBP fires but KBR never follows, causing
# the dimmer to ramp to min/max uncontrollably.
DEFAULT_RAISE_LOWER_RELEASE_DELAY: Final = 0.5
# RPM motor command values (FADEDIM levels for HW-RPM-4M-230 modules)
RPM_MOTOR_UP: Final = 16
RPM_MOTOR_DOWN: Final = 35
RPM_MOTOR_STOP: Final = 0
# Maximum delay allowed in send_command service (milliseconds)
MAX_COMMAND_DELAY_MS: Final = 60000

# CSV import limits
MAX_CSV_SIZE: Final = 1_000_000  # 1MB
MAX_CSV_ROWS: Final = 5000

# KLS button window (0-indexed start of 8-button window in 24-digit KLS string)
DEFAULT_KLS_WINDOW_OFFSET: Final = 9

# CCO entity types for config flow
CCO_TYPE_SWITCH: Final = "switch"
CCO_TYPE_LIGHT: Final = "light"
CCO_TYPE_COVER: Final = "cover"
CCO_TYPE_LOCK: Final = "lock"
CCO_TYPE_CLIMATE: Final = "climate"
CCO_TYPE_FAN: Final = "fan"

# Event names
EVENT_BUTTON_PRESS: Final = "homeworks_button_press"
EVENT_BUTTON_RELEASE: Final = "homeworks_button_release"
EVENT_BUTTON_HOLD: Final = "homeworks_button_hold"
EVENT_BUTTON_DOUBLE_TAP: Final = "homeworks_button_double_tap"

# Event types reported by keypad button event entities.
# These match the values dispatched by the coordinator for the
# KBP / KBR / KBH / KBDT monitoring messages, in that order.
BUTTON_EVENT_PRESSED: Final = "pressed"
BUTTON_EVENT_RELEASED: Final = "released"
BUTTON_EVENT_HOLD: Final = "hold"
BUTTON_EVENT_DOUBLE_TAP: Final = "double_tap"
BUTTON_EVENT_TYPES: Final = (
    BUTTON_EVENT_PRESSED,
    BUTTON_EVENT_RELEASED,
    BUTTON_EVENT_HOLD,
    BUTTON_EVENT_DOUBLE_TAP,
)

# Entity state attributes
ATTR_HOMEWORKS_ADDRESS: Final = "homeworks_address"
ATTR_BUTTON_NUMBER: Final = "button_number"

# Service names
SERVICE_SEND_COMMAND: Final = "send_command"
SERVICE_REQUEST_STATE: Final = "request_state"

# Diagnostic keys
DIAG_CONNECTED: Final = "connected"
DIAG_LAST_MESSAGE_TIME: Final = "last_message_time"
DIAG_LAST_KLS_TIME: Final = "last_kls_time"
DIAG_RECONNECT_COUNT: Final = "reconnect_count"
DIAG_POLL_FAILURE_COUNT: Final = "poll_failure_count"
DIAG_PARSE_ERROR_COUNT: Final = "parse_error_count"
DIAG_CCO_DEVICE_COUNT: Final = "cco_device_count"
DIAG_CCI_DEVICE_COUNT: Final = "cci_device_count"
DIAG_DIMMER_COUNT: Final = "dimmer_count"
DIAG_KEYPAD_COUNT: Final = "keypad_count"
DIAG_RPM_COVER_COUNT: Final = "rpm_cover_count"

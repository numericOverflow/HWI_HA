"""Command builders for Homeworks protocol.

This module provides typed functions for building RS-232 command strings.
All commands follow the protocol specification - no invented commands.

Command format: COMMAND, param1, param2, ...
Terminated with CRLF (handled by transport layer).
"""

from __future__ import annotations

from .protocol import normalize_address


# =============================================================================
# Number formatting (L232 fields take whole numbers only)
# =============================================================================


# L232 intensity field: whole percent (fadedim.htm:40, flashdim.htm:39).
INTENSITY_MIN = 0
INTENSITY_MAX = 100
# Lowest result of whole_units() for a value of 0 or less.
MIN_UNITS = 0
# Lowest result for any raw value above 0 (1 percent or 1 second).
MIN_NONZERO_UNITS = 1
# Decimals kept before the fraction is dropped. Removes binary float noise
# and small math error (28.999999999999996 -> 29, 1.996 -> 2).
FLOAT_NOISE_DECIMALS = 2
_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


def whole_units(value: float) -> int:
    """Return a value as whole L232 units (percent or seconds).

    The value is rounded to FLOAT_NOISE_DECIMALS, then the fraction is
    dropped. A raw value above 0 gives at least MIN_NONZERO_UNITS, so a
    small request never becomes 0. A value of 0 or less gives MIN_UNITS.

    Raises TypeError for None, ValueError for NaN, and OverflowError for
    infinity.
    """
    whole = max(MIN_UNITS, int(round(value, FLOAT_NOISE_DECIMALS)))
    if value > 0:
        return max(MIN_NONZERO_UNITS, whole)
    return whole


def _format_intensity(percent: float) -> str:
    """Return an L232 intensity field: whole percent, clamped to 0-100."""
    return str(min(INTENSITY_MAX, max(INTENSITY_MIN, whole_units(percent))))


def _format_time(seconds: float) -> str:
    """Return an L232 time field as HH:MM:SS (time_formatting.htm:27-33)."""
    minutes, secs = divmod(whole_units(seconds), _SECONDS_PER_MINUTE)
    hours, minutes = divmod(minutes, _MINUTES_PER_HOUR)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# =============================================================================
# Dimmer Commands
# =============================================================================


def fade_dim(
    address: str,
    intensity: float,
    fade_time: float = 0.0,
    delay_time: float = 0.0,
) -> str:
    """Build FADEDIM command.

    Fades a dimmer to target intensity. Every numeric field is sent as a
    whole number (see whole_units): intensity in percent 0-100, and both
    times as HH:MM:SS. Any value above 0 gives at least 1.

    Args:
        address: Dimmer address
        intensity: Target intensity 0-100 percent
        fade_time: Fade time in seconds
        delay_time: Delay before starting in seconds

    Returns:
        Command string
    """
    return (
        f"FADEDIM, {_format_intensity(intensity)}, "
        f"{_format_time(fade_time)}, {_format_time(delay_time)}, {address}"
    )


def raise_dim(address: str) -> str:
    """Build RAISEDIM command."""
    return f"RAISEDIM, {address}"


def lower_dim(address: str) -> str:
    """Build LOWERDIM command."""
    return f"LOWERDIM, {address}"


def stop_dim(address: str) -> str:
    """Build STOPDIM command."""
    return f"STOPDIM, {address}"


def flash_dim(address: str, intensity: float, flash_rate: float = 2.0) -> str:
    """Build FLASHDIM command."""
    return (
        f"FLASHDIM, {_format_intensity(intensity)}, "
        f"{_format_time(flash_rate)}, {address}"
    )


def stop_flash(address: str) -> str:
    """Build STOPFLASH command."""
    return f"STOPFLASH, {address}"


def request_dimmer_level(address: str) -> str:
    """Build RDL (Request Dimmer Level) command."""
    return f"RDL, {address}"


# =============================================================================
# RPM Motor Cover Commands
# =============================================================================


# RPM motor command values
RPM_MOTOR_UP = 16
RPM_MOTOR_STOP = 0
RPM_MOTOR_DOWN = 35


def motor_cover_up(address: str) -> str:
    """Build command to raise a motor cover.

    Uses DL command with value 16 for up.

    Args:
        address: Motor address [pp:ll:mi:mo:ou]

    Returns:
        Command string
    """
    return f"FADEDIM, {RPM_MOTOR_UP}, 0, 0, {address}"


def motor_cover_down(address: str) -> str:
    """Build command to lower a motor cover.

    Uses DL command with value 35 for down.

    Args:
        address: Motor address [pp:ll:mi:mo:ou]

    Returns:
        Command string
    """
    return f"FADEDIM, {RPM_MOTOR_DOWN}, 0, 0, {address}"


def motor_cover_stop(address: str) -> str:
    """Build command to stop a motor cover.

    Uses DL command with value 0 for stop.

    Args:
        address: Motor address [pp:ll:mi:mo:ou]

    Returns:
        Command string
    """
    return f"FADEDIM, {RPM_MOTOR_STOP}, 0, 0, {address}"


# =============================================================================
# CCO (Contact Closure Output) Commands
# =============================================================================


# L232 CCOPULSE pulse field: count of 0.5 s steps, 1-245 (ccopulse.htm:52-61).
CCO_PULSE_STEP_SECONDS = 0.5
CCO_PULSE_MIN_STEPS = 1
CCO_PULSE_MAX_STEPS = 245

def cco_close(address: str, relay: int) -> str:
    """Build CCOCLOSE command.

    Closes a CCO relay (turns it ON).

    Args:
        address: CCO address [pp:ll:aa]
        relay: Relay number 1-8

    Returns:
        Command string
    """
    return f"CCOCLOSE, {address}, {relay}"


def cco_open(address: str, relay: int) -> str:
    """Build CCOOPEN command.

    Opens a CCO relay (turns it OFF).

    Args:
        address: CCO address [pp:ll:aa]
        relay: Relay number 1-8

    Returns:
        Command string
    """
    return f"CCOOPEN, {address}, {relay}"


def cco_pulse(address: str, relay: int, duration_seconds: float) -> str:
    """Build CCOPULSE command.

    Pulses a CCO relay for a specified duration.

    Args:
        address: CCO address [pp:ll:aa]
        relay: Relay number 1-8
        duration_seconds: Pulse duration (0.5-122.5 seconds)

    Returns:
        Command string
    """
    # Whole 0.5 s steps; the fraction is dropped (ccopulse.htm:52-61).
    steps = int(duration_seconds / CCO_PULSE_STEP_SECONDS)
    increments = max(CCO_PULSE_MIN_STEPS, min(CCO_PULSE_MAX_STEPS, steps))
    return f"CCOPULSE, {address}, {relay}, {increments}"


# =============================================================================
# Keypad Commands
# =============================================================================


def keypad_button_press(address: str, button: int) -> str:
    """Build KBP (Keypad Button Press) command."""
    return f"KBP, {address}, {button}"


def keypad_button_release(address: str, button: int) -> str:
    """Build KBR (Keypad Button Release) command."""
    return f"KBR, {address}, {button}"


def keypad_button_hold(address: str, button: int) -> str:
    """Build KBH (Keypad Button Hold) command."""
    return f"KBH, {address}, {button}"


def keypad_button_double_tap(address: str, button: int) -> str:
    """Build KBDT (Keypad Button Double Tap) command."""
    return f"KBDT, {address}, {button}"


def keypad_enable(address: str) -> str:
    """Build KE (Keypad Enable) command."""
    return f"KE, {address}"


def keypad_disable(address: str) -> str:
    """Build KD (Keypad Disable) command."""
    return f"KD, {address}"


def request_keypad_enable_state(address: str) -> str:
    """Build RKES (Request Keypad Enable State) command."""
    return f"RKES, {address}"


def set_led(address: str, led_number: int, state: int) -> str:
    """Build SETLED command.

    Args:
        address: Keypad address
        led_number: LED number 1-24
        state: 0=Off, 1=On, 2=Flash1, 3=Flash2

    Returns:
        Command string
    """
    return f"SETLED, {address}, {led_number}, {state}"


def set_leds(address: str, led_states: str) -> str:
    """Build SETLEDS command.

    Args:
        address: Keypad address
        led_states: LED state string (0-3 or x for no change)

    Returns:
        Command string
    """
    return f"SETLEDS, {address}, {led_states}"


def request_keypad_led_states(address: str) -> str:
    """Build RKLS (Request Keypad LED States) command."""
    return f"RKLS, {address}"


def request_keypad_last_button(address: str) -> str:
    """Build RKLBP (Request Keypad Last Button Press) command."""
    return f"RKLBP, {address}"


# =============================================================================
# GRAFIK Eye Commands
# =============================================================================


def grafik_eye_scene_select(address: str, scene: int) -> str:
    """Build GSS (GRAFIK Eye Scene Select) command.

    Args:
        address: GRAFIK Eye address
        scene: Scene number 0-16 (0 = Off)

    Returns:
        Command string
    """
    return f"GSS, {address}, {scene}"


def request_grafik_eye_scene(address: str) -> str:
    """Build RGS (Request GRAFIK Eye Scene) command."""
    return f"RGS, {address}"


# =============================================================================
# Sivoia Commands
# =============================================================================


def sivoia_scene_select(address: str, command: str, delay_time: float = 0.0) -> str:
    """Build SVSS (Sivoia Scene Select) command.

    Args:
        address: Sivoia control address
        command: Scene command (1, 2, 3, R, L, C, O, S)
        delay_time: Delay in seconds, sent as HH:MM:SS. 0 or less leaves
            the field out.

    Returns:
        Command string
    """
    if delay_time > 0:
        return f"SVSS, {address}, {command}, {_format_time(delay_time)}"
    return f"SVSS, {address}, {command}"


def request_sivoia_scene(address: str) -> str:
    """Build RSVS (Request Sivoia Scene) command."""
    return f"RSVS, {address}"


# =============================================================================
# Monitoring Commands
# =============================================================================


def enable_dimmer_monitoring() -> str:
    """Build DLMON command."""
    return "DLMON"


def disable_dimmer_monitoring() -> str:
    """Build DLMOFF command."""
    return "DLMOFF"


def enable_keypad_button_monitoring() -> str:
    """Build KBMON command."""
    return "KBMON"


def disable_keypad_button_monitoring() -> str:
    """Build KBMOFF command."""
    return "KBMOFF"


def enable_keypad_led_monitoring() -> str:
    """Build KLMON command."""
    return "KLMON"


def disable_keypad_led_monitoring() -> str:
    """Build KLMOFF command."""
    return "KLMOFF"


def enable_grafik_eye_monitoring() -> str:
    """Build GSMON command."""
    return "GSMON"


def disable_grafik_eye_monitoring() -> str:
    """Build GSMOFF command."""
    return "GSMOFF"


# =============================================================================
# System Commands
# =============================================================================


def prompt_off() -> str:
    """Build PROMPTOFF command."""
    return "PROMPTOFF"


def prompt_on() -> str:
    """Build PROMPTON command."""
    return "PROMPTON"


def login(credentials: str) -> str:
    """Build LOGIN command.

    Args:
        credentials: Either "password" or "username, password"

    Returns:
        Command string (just the credentials, LOGIN: prompt is from controller)
    """
    return credentials


def logout(port_address: str | None = None) -> str:
    """Build LOGOUT command."""
    if port_address:
        return f"LOGOUT, {port_address}"
    return "LOGOUT"


def request_processor_address() -> str:
    """Build PROCADDR command."""
    return "PROCADDR"


def request_os_revision() -> str:
    """Build OSREV command."""
    return "OSREV"


def get_baud_rate(port_address: str | None = None) -> str:
    """Build GETBAUD command."""
    if port_address:
        return f"GETBAUD, {port_address}"
    return "GETBAUD"


def set_baud_rate(baud_rate: int) -> str:
    """Build SETBAUD command."""
    return f"SETBAUD, {baud_rate}"


def get_handshaking(port_address: str | None = None) -> str:
    """Build GETHAND command."""
    if port_address:
        return f"GETHAND, {port_address}"
    return "GETHAND"


def set_handshaking(mode: str) -> str:
    """Build SETHAND command.

    Args:
        mode: "NONE" or "HW"

    Returns:
        Command string
    """
    return f"SETHAND, {mode}"


def help_command(command: str | None = None) -> str:
    """Build HELP command."""
    if command:
        return f"HELP, {command}"
    return "HELP"


# =============================================================================
# Time Clock Commands
# =============================================================================


def set_time(time_24h: str) -> str:
    """Build ST (Set Time) command.

    Args:
        time_24h: Time in HH:MM:SS format

    Returns:
        Command string
    """
    return f"ST, {time_24h}"


def request_time() -> str:
    """Build RST (Request System Time) command."""
    return "RST"


def request_time_with_seconds() -> str:
    """Build RST2 command."""
    return "RST2"


def set_date(date: str) -> str:
    """Build SD (Set Date) command.

    Args:
        date: Date in MM/DD/YYYY format

    Returns:
        Command string
    """
    return f"SD, {date}"


def request_date() -> str:
    """Build RSD (Request System Date) command."""
    return "RSD"


def timeclock_enable() -> str:
    """Build TCE command."""
    return "TCE"


def timeclock_disable() -> str:
    """Build TCD command."""
    return "TCD"


def request_timeclock_state() -> str:
    """Build TCS command."""
    return "TCS"


def request_sunrise() -> str:
    """Build SUNRISE command."""
    return "SUNRISE"


def request_sunset() -> str:
    """Build SUNSET command."""
    return "SUNSET"

"""Typed message structures for Homeworks protocol.

This module defines dataclasses for all message types that can be
received from a Homeworks controller. These provide type safety
and clear structure for parsed protocol messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto


class MessageType(Enum):
    """Types of messages from the controller."""

    # Keypad/button events
    BUTTON_PRESSED = auto()
    BUTTON_RELEASED = auto()
    BUTTON_HOLD = auto()
    BUTTON_DOUBLE_TAP = auto()

    # State changes
    KEYPAD_LED_CHANGED = auto()
    DIMMER_LEVEL_CHANGED = auto()
    KEYPAD_ENABLE_CHANGED = auto()
    GRAFIK_EYE_SCENE_CHANGED = auto()
    SIVOIA_SCENE_CHANGED = auto()

    # Connection events
    LOGIN_REQUIRED = auto()
    LOGIN_SUCCESS = auto()
    LOGIN_FAILED = auto()

    # Unknown/unparsed
    UNKNOWN = auto()


class ButtonEventType(Enum):
    """Types of button events."""

    PRESSED = "pressed"
    RELEASED = "released"
    HOLD = "hold"
    DOUBLE_TAP = "double_tap"


@dataclass(frozen=True)
class HomeworksMessage:
    """Base class for all Homeworks messages."""

    raw: str  # Original message string
    timestamp: datetime

    @classmethod
    def create(cls, raw: str) -> "HomeworksMessage":
        """Create a message with current timestamp."""
        return cls(raw=raw, timestamp=datetime.now(tz=timezone.utc))


# CCO button window configuration
# The 8 CCO relay states are embedded within the 24-digit KLS string.
# Default: positions 10-17 (1-indexed) = indices 9-16 (0-indexed)
CCO_BUTTON_WINDOW_OFFSET = 9  # 0-indexed start of 8-button window
CCO_BUTTON_WINDOW_LENGTH = 8  # Number of buttons in window

# KLS digit that indicates a CCO relay is CLOSED (device ON).
# WARNING: This is counter-intuitive. The L232 protocol docs define
# digit 1="On" and digit 2="Flash", which suggests 1=ON. But for CCO
# modules specifically, Lutron uses FLASHING LED (digit 2) to indicate
# the relay is CLOSED/energized, and SOLID LED (digit 1) to indicate
# the relay is OPEN/de-energized. This was verified empirically via
# telnet to a live HWI processor (2026-06-26) and is documented in
# L232/cco_kls_state.htm. DO NOT "fix" this to 1.
CCO_RELAY_CLOSED_DIGIT = 2

# KLS digit that indicates a CCO relay is OPEN (device OFF).
# Per L232/cco_kls_state.htm this is the RESTING value: "an idle relay
# reports 1, not Off". Digit 0 is explicitly UNDOCUMENTED & UNDISCOVERED
# for the relay window and has never been observed on a real module, so
# it must NOT be treated as OFF — see cco_relay_digit_to_state().
CCO_RELAY_OPEN_DIGIT = 1

# These digit meanings apply ONLY to the relay window of a KLS string
# addressed to a CCO module. Keypad LEDs keep the kls_mon.htm meanings
# (0=Off, 1=On, 2=Flash1, 3=Flash2), which are the OPPOSITE sense for
# digit 1. Relay position and LED state share the same underlying
# register, so the same digit means different things depending on
# whether the module is a CCO or a keypad.


def cco_relay_digit_to_state(digit: int) -> bool | None:
    """Interpret a raw KLS relay-window digit as a CCO relay position.

    This is the single source of truth for CCO digit semantics. It applies
    only to digits inside the relay window of a CCO module's KLS string —
    keypad LED digits use the kls_mon.htm meanings instead.

    Args:
        digit: Raw digit from the relay window of a KLS string.

    Returns:
        True if the relay is closed (energized, device ON).
        False if the relay is open (de-energized, device OFF).
        None if the digit has no documented meaning — currently 0 and 3.
        Callers must surface None as "unknown", never as OFF: a CCO relay
        is latching, so guessing a default is wrong roughly half the time.

    A window of all-zeros is the signature of a misconfigured window
    offset pointing outside the relay region. Returning None there makes
    that fail visibly instead of reporting every relay as confidently off.
    """
    if digit == CCO_RELAY_CLOSED_DIGIT:
        return True
    if digit == CCO_RELAY_OPEN_DIGIT:
        return False
    return None


@dataclass(frozen=True)
class KLSMessage(HomeworksMessage):
    """Keypad LED State message.

    Format: KLS, [pp:ll:aa], <24-digit led states>

    The same message serves two kinds of module, and the digits mean
    DIFFERENT things depending on which sent it.

    On a keypad (L232/kls_mon.htm) every digit is an LED state:
    - 0 = Off
    - 1 = On
    - 2 = Flash 1
    - 3 = Flash 2
    Use get_led_state() for this.

    On a CCO module (L232/cco_kls_state.htm) the 8 relay positions occupy
    digit positions 10-17 (1-indexed) = indices 9-16 (0-indexed), and
    within that window the digits are repurposed:
    - 1 = relay OPEN (de-energized, device OFF) — the resting value
    - 2 = relay CLOSED (energized, device ON)
    - 0 = undocumented, never observed
    Use get_cco_relay_state() / get_cco_relay_digit() for this. Note that
    digit 1 means ON for a keypad LED but OFF for a CCO relay.

    Example — CCO module:
        KLS, [01:05:03], 000000000121111110000000
                         ^^^^^^^^^        ^^^^^^^^
                         ignored   12111111  ignored
                                   └─ 8-relay window (indices 9-16)

        Relay 1 = index 9  = 1 (OFF, relay open)
        Relay 2 = index 10 = 2 (ON, relay closed)
        Relay 3 = index 11 = 1 (OFF)
        Relay 4 = index 12 = 1 (OFF)
        Relay 5 = index 13 = 1 (OFF)
        Relay 6 = index 14 = 1 (OFF)
        Relay 7 = index 15 = 1 (OFF)
        Relay 8 = index 16 = 1 (OFF)
    """

    address: str  # Normalized [pp:ll:aa] format
    led_states: tuple[int, ...]  # 24 integers, immutable

    def get_led_state(self, position: int) -> int:
        """Get raw LED state at position (1-24).

        This returns the raw digit from the KLS string at the given
        1-indexed position. For CCO relay state, use get_cco_relay_state().
        """
        if 1 <= position <= len(self.led_states):
            return self.led_states[position - 1]
        return 0

    def get_cco_relay_digit(
        self,
        relay: int,
        window_offset: int = CCO_BUTTON_WINDOW_OFFSET,
    ) -> int | None:
        """Get the raw relay-window digit for a CCO relay.

        Returns the digit uninterpreted so callers can distinguish a
        documented value from one with no known meaning. Use
        cco_relay_digit_to_state() to interpret it.

        Args:
            relay: Relay number (1-8)
            window_offset: 0-indexed start of the 8-relay window (default: 9)

        Returns:
            The raw digit, or None if the relay number is out of range or
            the window offset places the relay past the end of the string.
        """
        if not (1 <= relay <= CCO_BUTTON_WINDOW_LENGTH):
            return None

        index = window_offset + (relay - 1)

        if index >= len(self.led_states):
            return None

        return self.led_states[index]

    def get_cco_relay_state(
        self,
        relay: int,
        window_offset: int = CCO_BUTTON_WINDOW_OFFSET,
    ) -> bool | None:
        """Get CCO relay state from the relay window.

        The CCO relay states are embedded in a specific 8-digit window
        within the 24-digit KLS string. By default, this window starts
        at 0-indexed position 9 (1-indexed position 10).

        Args:
            relay: Relay number (1-8)
            window_offset: 0-indexed start of the 8-relay window (default: 9)

        Returns:
            True if the relay is closed (ON), False if open (OFF), or None
            if the position is unreadable or the digit has no documented
            meaning. None means "unknown" and must not be shown as OFF.

        Example:
            For KLS string "000000000121111110000000":
            - Relay 2 → index = 9 + (2-1) = 10 → digit '2' → True (ON)

            For KLS string "000000000111111110000000":
            - Relay 2 → index = 9 + (2-1) = 10 → digit '1' → False (OFF)
        """
        digit = self.get_cco_relay_digit(relay, window_offset)
        if digit is None:
            return None
        return cco_relay_digit_to_state(digit)


@dataclass(frozen=True)
class DimmerLevelMessage(HomeworksMessage):
    """Dimmer Level message.

    Format: DL, [address], <level>
    """

    address: str  # Full dimmer address
    level: int  # 0-100 percent


@dataclass(frozen=True)
class ButtonEventMessage(HomeworksMessage):
    """Button event message (press, release, hold, double-tap).

    Formats:
    - KBP, [pp:ll:aa], <button>  (keypad press)
    - KBR, [pp:ll:aa], <button>  (keypad release)
    - KBH, [pp:ll:aa], <button>  (keypad hold)
    - KBDT, [pp:ll:aa], <button> (keypad double-tap)
    - DBP, DBR, DBH, DBDT        (dimmer button variants)
    - SVBP, SVBR, SVBH, SVBDT    (Sivoia control variants)
    """

    address: str
    button: int
    event_type: ButtonEventType
    source: str  # "keypad", "dimmer", or "sivoia"


@dataclass(frozen=True)
class KeypadEnableMessage(HomeworksMessage):
    """Keypad enable/disable state message.

    Format: KES, [pp:ll:aa], <enabled|disabled>
    """

    address: str
    enabled: bool


@dataclass(frozen=True)
class GrafikEyeSceneMessage(HomeworksMessage):
    """GRAFIK Eye scene selection message.

    Format: GSS, [pp:ll:aa], <scene>
    """

    address: str
    scene: int  # 0 = Off, 1-16 = scene number


@dataclass(frozen=True)
class SivoiaSceneMessage(HomeworksMessage):
    """Sivoia scene command message.

    Format: SVS, [pp:ll:aa], <command>, <status>
    """

    address: str
    command: str  # 1, 2, 3, R, L, C, O, S
    status: str  # STOPPED or MOVING


@dataclass(frozen=True)
class UnknownMessage(HomeworksMessage):
    """Unknown or unparsed message."""

    parts: tuple[str, ...]


# Type alias for any message
AnyMessage = (
    KLSMessage
    | DimmerLevelMessage
    | ButtonEventMessage
    | KeypadEnableMessage
    | GrafikEyeSceneMessage
    | SivoiaSceneMessage
    | UnknownMessage
)

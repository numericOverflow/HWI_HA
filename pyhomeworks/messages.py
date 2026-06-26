"""Typed message structures for Homeworks protocol.

This module defines dataclasses for all message types that can be
received from a Homeworks controller. These provide type safety
and clear structure for parsed protocol messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any


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
        return cls(raw=raw, timestamp=datetime.now())


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
# telnet to a live HWI processor (2026-06-26). DO NOT "fix" this to 1.
CCO_RELAY_CLOSED_DIGIT = 2


@dataclass(frozen=True)
class KLSMessage(HomeworksMessage):
    """Keypad LED State message.

    Format: KLS, [pp:ll:aa], <24-digit led states>

    Each digit represents an LED state:
    - 0 = Off/Unknown
    - 1 = On (solid LED; for CCO: relay OPEN/OFF)
    - 2 = Flash1 (for CCO: relay CLOSED/ON)
    - 3 = Flash2

    For CCO devices, the 8 relay states are in a specific window within
    the 24-digit string. Default window is positions 10-17 (1-indexed),
    which corresponds to 0-indexed positions 9-16.

    Example:
        KLS, [01:05:03], 000000000121111110000000
                         ^^^^^^^^^        ^^^^^^^^
                         ignored   12111111  ignored
                                   └─ 8-button window (indices 9-16)

        Button 1 = index 9  = 1 (OFF, solid LED)
        Button 2 = index 10 = 2 (ON, relay closed)
        Button 3 = index 11 = 1 (OFF)
        Button 4 = index 12 = 1 (OFF)
        Button 5 = index 13 = 1 (OFF)
        Button 6 = index 14 = 1 (OFF)
        Button 7 = index 15 = 1 (OFF)
        Button 8 = index 16 = 1 (OFF)
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

    def get_cco_relay_state(
        self,
        relay: int,
        window_offset: int = CCO_BUTTON_WINDOW_OFFSET,
    ) -> bool:
        """Get CCO relay state from the button window.

        The CCO relay states are embedded in a specific 8-digit window
        within the 24-digit KLS string. By default, this window starts
        at 0-indexed position 9 (1-indexed position 10).

        Args:
            relay: Relay/button number (1-8)
            window_offset: 0-indexed start of the 8-button window (default: 9)

        Returns:
            True if relay is closed/ON (digit == CCO_RELAY_CLOSED_DIGIT)
            False otherwise

        Example:
            For KLS string "000000000121111110000000":
            - Relay 2 → index = 9 + (2-1) = 10 → digit '2' → True (ON)

            For KLS string "000000000111111110000000":
            - Relay 2 → index = 9 + (2-1) = 10 → digit '1' → False (OFF)
        """
        if not (1 <= relay <= CCO_BUTTON_WINDOW_LENGTH):
            return False

        index = window_offset + (relay - 1)

        if index >= len(self.led_states):
            return False

        return self.led_states[index] == CCO_RELAY_CLOSED_DIGIT


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

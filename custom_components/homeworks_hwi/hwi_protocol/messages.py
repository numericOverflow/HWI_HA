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


@dataclass(frozen=True)
class KLSMessage(HomeworksMessage):
    """Keypad LED State message.

    Format: KLS, [pp:ll:aa], <24-digit led states>

    Each digit represents an LED state:
    - 0 = Off/Unknown
    - 1 = On (for CCO: relay closed)
    - 2 = Flash1 (for CCO: relay open/OFF)
    - 3 = Flash2

    For CCO devices, the 8 relay states are in a specific window within
    the 24-digit string. Default window is positions 10-17 (1-indexed),
    which corresponds to 0-indexed positions 9-16.

    Example:
        KLS, [02:06:03], 000000000222112110000000
                         ^^^^^^^^^        ^^^^^^^^
                         ignored   22211211  ignored
                                   └─ 8-button window (indices 9-16)

        Button 1 = index 9  = 2 (OFF)
        Button 2 = index 10 = 2 (OFF)
        Button 3 = index 11 = 2 (OFF)
        Button 4 = index 12 = 1 (ON)
        Button 5 = index 13 = 1 (ON)
        Button 6 = index 14 = 2 (OFF)
        Button 7 = index 15 = 1 (ON)
        Button 8 = index 16 = 1 (ON)
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
            True if relay is closed/ON (digit value is 1)
            False if relay is open/OFF (digit value is 2, or any other value)

        Example:
            For KLS string "000000000222112110000000":
            - Relay 6 → index = 9 + (6-1) = 14 → digit '2' → False (OFF)

            For KLS string "000000000222111110000000":
            - Relay 6 → index = 9 + (6-1) = 14 → digit '1' → True (ON)
        """
        if not (1 <= relay <= CCO_BUTTON_WINDOW_LENGTH):
            return False

        # Calculate index: window_offset + (relay - 1)
        # For relay 1: index = 9 + 0 = 9
        # For relay 6: index = 9 + 5 = 14
        index = window_offset + (relay - 1)

        if index >= len(self.led_states):
            return False

        # 1 = ON (relay closed), anything else = OFF
        return self.led_states[index] == 1


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

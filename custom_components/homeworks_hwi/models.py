"""Data models for Lutron Homeworks integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto

from .hwi_protocol.messages import (
    CCO_BUTTON_WINDOW_LENGTH,
    CCO_BUTTON_WINDOW_OFFSET,
    CCO_RELAY_CLOSED_DIGIT,
)


class CCOEntityType(Enum):
    """Semantic type for CCO-controlled endpoints."""

    SWITCH = auto()
    LIGHT = auto()
    LOCK = auto()
    COVER = auto()
    CLIMATE = auto()
    FAN = auto()


@dataclass
class CCOAddress:
    """Represents a canonical CCO address.

    Format: processor:link:address,button
    Example: 2:6:3,6 means processor 2, link 6, keypad address 3, button 6
    """

    processor: int
    link: int
    address: int
    button: int

    @classmethod
    def from_string(cls, addr_str: str) -> "CCOAddress":
        """Parse CCO address from string format.

        Accepts formats:
        - "2:6:3,6" (processor:link:address,button)
        - "[02:06:03],6" (bracketed address with button)
        - "2:6:3:6" (all colon-separated)
        """
        addr_str = addr_str.strip()

        # Handle comma-separated button
        if "," in addr_str:
            addr_part, button_str = addr_str.rsplit(",", 1)
            button = int(button_str.strip())
        else:
            # Assume last element is button (colon-separated)
            parts = addr_str.strip("[]").split(":")
            if len(parts) >= 4:
                button = int(parts[-1])
                addr_part = ":".join(parts[:-1])
            else:
                raise ValueError(f"Invalid CCO address format: {addr_str}")

        # Parse the address part
        addr_part = addr_part.strip("[]")
        parts = addr_part.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"CCO address must have processor:link:address: {addr_str}"
            )

        return cls(
            processor=int(parts[0]),
            link=int(parts[1]),
            address=int(parts[2]),
            button=button,
        )

    def to_kls_address(self) -> str:
        """Return the [pp:ll:aa] format for KLS matching."""
        return f"[{self.processor:02d}:{self.link:02d}:{self.address:02d}]"

    def to_command_address(self) -> str:
        """Return address format for CCO commands."""
        return f"[{self.processor}:{self.link}:{self.address}]"

    def __str__(self) -> str:
        """Return canonical string representation."""
        return f"{self.processor}:{self.link}:{self.address},{self.button}"

    @property
    def unique_key(self) -> tuple[int, int, int, int]:
        """Return unique key for this CCO endpoint."""
        return (self.processor, self.link, self.address, self.button)


@dataclass
class DimmerAddress:
    """Represents a dimmer address.

    Format varies by dimmer type:
    - RPM: processor:link:MI:module:zone (5 parts)
    - D48/H48: processor:link:router:bus:dimmer (5 parts)
    - RF: processor:link:device_type:dimmer (4 parts)
    """

    parts: list[int]

    @classmethod
    def from_string(cls, addr_str: str) -> "DimmerAddress":
        """Parse dimmer address from string."""
        addr_str = addr_str.strip("[]")
        parts = [int(p) for p in addr_str.split(":")]
        return cls(parts=parts)

    def to_normalized(self) -> str:
        """Return normalized [pp:ll:...] format."""
        formatted = ":".join(f"{p:02d}" for p in self.parts)
        return f"[{formatted}]"

    def __str__(self) -> str:
        return self.to_normalized()


@dataclass
class CCODevice:
    """Configuration for a CCO-controlled device."""

    address: CCOAddress
    name: str
    entity_type: CCOEntityType
    inverted: bool = False  # If True, ON/OFF semantics are reversed
    area: str | None = None

    @property
    def unique_id(self) -> str:
        """Generate unique ID for this device."""
        return f"cco_{self.address.processor}_{self.address.link}_{self.address.address}_{self.address.button}"

    def interpret_state(self, kls_digit: int) -> bool:
        """Interpret KLS digit as ON/OFF state.

        KLS LED values for CCO feedback (verified via telnet to processor):
        - 0 = not used/not applicable
        - 1 = relay is OPEN (device OFF) - LED solid
        - 2 = relay is CLOSED (device ON) - LED flashing
        - 3 = fast flash (not typically used for CCO)

        With inversion support for devices wired in reverse.
        """
        is_on = kls_digit == CCO_RELAY_CLOSED_DIGIT

        if self.inverted:
            is_on = not is_on

        return is_on


@dataclass
class LightDevice:
    """Configuration for a dimmable light."""

    address: str  # Normalized address string
    name: str
    fade_rate: float = 1.0
    area: str | None = None

    @property
    def unique_id(self) -> str:
        """Generate unique ID for this device."""
        return f"light_{self.address.replace(':', '_').strip('[]')}"


@dataclass
class KeypadDevice:
    """Configuration for a keypad."""

    address: str  # Normalized address string [pp:ll:aa]
    name: str
    buttons: list[KeypadButton] = field(default_factory=list)
    area: str | None = None

    @property
    def unique_id(self) -> str:
        """Generate unique ID for this device."""
        return f"keypad_{self.address.replace(':', '_').strip('[]')}"


@dataclass
class KeypadButton:
    """Configuration for a keypad button."""

    number: int  # 1-24
    name: str
    has_led: bool = False
    release_delay: float = 0.0


@dataclass
class KLSState:
    """Represents the LED state of a keypad/CCO.

    The 24-digit KLS string contains LED states, but for CCO devices,
    only an 8-digit window within the string is meaningful. This window
    starts at 0-indexed position 9 (1-indexed position 10) by default.

    Example:
        KLS string: 000000000121111110000000
                    ^^^^^^^^^        ^^^^^^^^
                    ignored   12111111  ignored
                              └─ 8-button window (indices 9-16)

        Button 1 → index 9 + 0 = 9 → digit '1' → OFF (solid LED)
        Button 2 → index 9 + 1 = 10 → digit '2' → ON (flashing LED)
    """

    address: str  # Normalized [pp:ll:aa] format
    led_states: list[int]  # 24 integers (0-3)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_button_state(self, button: int) -> int:
        """Get raw LED state for a specific button (1-24).

        This returns the raw digit from the KLS string. For CCO relay
        state interpretation, use get_cco_state() instead.
        """
        if 1 <= button <= 24 and button <= len(self.led_states):
            return self.led_states[button - 1]  # Convert to 0-indexed
        return 0

    def get_cco_state(
        self,
        button: int,
        window_offset: int = CCO_BUTTON_WINDOW_OFFSET,
    ) -> bool:
        """Get CCO relay state from the button window.

        Args:
            button: Button/relay number (1-8)
            window_offset: 0-indexed start of the 8-button window (default: 9)

        Returns:
            True if relay is closed/ON, False otherwise.
        """
        if not (1 <= button <= CCO_BUTTON_WINDOW_LENGTH):
            return False

        index = window_offset + (button - 1)

        if index >= len(self.led_states):
            return False

        return self.led_states[index] == CCO_RELAY_CLOSED_DIGIT


@dataclass
class ControllerHealth:
    """Health metrics for a controller connection."""

    connected: bool = False
    last_message_time: datetime | None = None
    last_kls_time: datetime | None = None
    reconnect_count: int = 0
    poll_failure_count: int = 0
    parse_error_count: int = 0
    last_error: str | None = None

    def record_message(self) -> None:
        """Record that a message was received."""
        self.last_message_time = datetime.now(timezone.utc)

    def record_kls(self) -> None:
        """Record that a KLS message was received."""
        self.last_kls_time = datetime.now(timezone.utc)
        self.last_message_time = datetime.now(timezone.utc)

    def record_reconnect(self) -> None:
        """Record a reconnection event."""
        self.reconnect_count += 1

    def record_poll_failure(self, error: str) -> None:
        """Record a polling failure."""
        self.poll_failure_count += 1
        self.last_error = error

    def record_parse_error(self, error: str) -> None:
        """Record a parse error."""
        self.parse_error_count += 1
        self.last_error = error


try:
    from .hwi_protocol.protocol import normalize_address  # noqa: F401 — re-exported
except ImportError:
    from hwi_protocol.protocol import normalize_address  # noqa: F401 — standalone test mode


def parse_kls_address(addr: str) -> tuple[int, int, int]:
    """Parse KLS address into (processor, link, address) tuple."""
    addr = addr.strip("[]")
    parts = addr.split(":")
    if len(parts) != 3:
        raise ValueError(f"KLS address must have 3 parts: {addr}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))

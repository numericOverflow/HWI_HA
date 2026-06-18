"""Protocol parsing for Homeworks RS-232 messages.

This module handles:
- Message framing (CRLF-delimited)
- Parsing incoming messages into typed structures
- Address normalization

All parsing is stateless - just input bytes, output messages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from .messages import (
    AnyMessage,
    ButtonEventMessage,
    ButtonEventType,
    DimmerLevelMessage,
    GrafikEyeSceneMessage,
    KeypadEnableMessage,
    KLSMessage,
    SivoiaSceneMessage,
    UnknownMessage,
)

_LOGGER = logging.getLogger(__name__)

# Command separator
CRLF = b"\r\n"

# Messages that indicate monitoring is enabled (informational, no action needed)
IGNORED_MESSAGES = frozenset(
    {
        "Keypad button monitoring enabled",
        "Keypad button monitoring disabled",
        "GrafikEye scene monitoring enabled",
        "GrafikEye scene monitoring disabled",
        "Dimmer level monitoring enabled",
        "Dimmer level monitoring disabled",
        "Keypad led monitoring enabled",
        "Keypad led monitoring disabled",
        "CCO monitoring enabled",
        "Cover monitoring enabled",
    }
)


def normalize_address(address: str) -> str:
    """Normalize an address to [pp:ll:aa:...] format.

    Examples:
        "1:2:3" -> "[01:02:03]"
        "[1:2:3]" -> "[01:02:03]"
        "[01:02:03]" -> "[01:02:03]"
    """
    addr = address.strip("[]")
    parts = addr.split(":")
    formatted = ":".join(p.zfill(2) for p in parts)
    return f"[{formatted}]"


def parse_address(address: str) -> tuple[int, ...]:
    """Parse an address string into integer components.

    Args:
        address: Address string like "[01:02:03]" or "1:2:3"

    Returns:
        Tuple of integers (processor, link, address, ...)
    """
    addr = address.strip("[]")
    return tuple(int(p) for p in addr.split(":"))


class MessageParser:
    """Parser for Homeworks protocol messages.

    This class handles buffering of incoming bytes and parsing
    complete messages into typed structures.
    """

    def __init__(self) -> None:
        """Initialize the parser."""
        self._buffer = b""

    def feed(self, data: bytes) -> list[AnyMessage]:
        """Feed bytes to the parser and return any complete messages.

        Args:
            data: Raw bytes from socket

        Returns:
            List of parsed messages (may be empty)
        """
        self._buffer += data
        messages = []

        while CRLF in self._buffer:
            line, self._buffer = self._buffer.split(CRLF, 1)
            if line:
                try:
                    msg = self._parse_line(line.decode("utf-8"))
                    if msg:
                        messages.append(msg)
                except UnicodeDecodeError:
                    _LOGGER.warning("Invalid message encoding: %s", line)
                except Exception as err:
                    _LOGGER.warning("Failed to parse message: %s - %s", line, err)

        return messages

    def reset(self) -> None:
        """Clear the buffer."""
        self._buffer = b""

    def _parse_line(self, line: str) -> AnyMessage | None:
        """Parse a single line into a message.

        Args:
            line: Decoded message line (without CRLF)

        Returns:
            Parsed message or None if ignored
        """
        line = line.strip()
        if not line or line in IGNORED_MESSAGES:
            return None

        # Split by comma-space
        parts = [p.strip() for p in line.split(", ")]
        if not parts:
            return None

        command = parts[0].upper()
        timestamp = datetime.now(tz=timezone.utc)

        # Route to specific parser based on command
        parser = _PARSERS.get(command)
        if parser:
            return parser(line, parts, timestamp)

        # Unknown message
        return UnknownMessage(
            raw=line,
            timestamp=timestamp,
            parts=tuple(parts),
        )


# =============================================================================
# Individual Message Parsers
# =============================================================================


def _parse_kls(line: str, parts: list[str], ts: datetime) -> KLSMessage | None:
    """Parse KLS (Keypad LED State) message.

    Format: KLS, [pp:ll:aa], <24-digit led states>
    """
    if len(parts) < 3:
        return None

    address = normalize_address(parts[1])
    led_string = parts[2]

    # Parse LED states - each character is a digit 0-3
    try:
        led_states = tuple(int(c) for c in led_string if c.isdigit())
        if len(led_states) != 24:
            _LOGGER.warning(
                "Invalid KLS led states length: %d for %s",
                len(led_states),
                address,
            )
            # Pad or truncate to 24
            if len(led_states) < 24:
                led_states = led_states + (0,) * (24 - len(led_states))
            else:
                led_states = led_states[:24]
    except ValueError:
        return None

    return KLSMessage(
        raw=line,
        timestamp=ts,
        address=address,
        led_states=led_states,
    )


def _parse_dl(line: str, parts: list[str], ts: datetime) -> DimmerLevelMessage | None:
    """Parse DL (Dimmer Level) message.

    Format: DL, [address], <level>
    Level may be integer ("75") or float ("97.00") depending on device type.
    Sivoia QED shades report floats; standard dimmers report integers.
    """
    if len(parts) < 3:
        return None

    address = normalize_address(parts[1])
    try:
        level = int(round(float(parts[2])))
    except ValueError:
        return None

    return DimmerLevelMessage(
        raw=line,
        timestamp=ts,
        address=address,
        level=level,
    )


def _make_button_parser(
    event_type: ButtonEventType, source: str
) -> Callable[[str, list[str], datetime], ButtonEventMessage | None]:
    """Create a button event parser for a specific event type and source."""

    def parser(line: str, parts: list[str], ts: datetime) -> ButtonEventMessage | None:
        if len(parts) < 3:
            return None

        address = normalize_address(parts[1])
        try:
            button = int(parts[2])
        except ValueError:
            return None

        return ButtonEventMessage(
            raw=line,
            timestamp=ts,
            address=address,
            button=button,
            event_type=event_type,
            source=source,
        )

    return parser


def _parse_kes(line: str, parts: list[str], ts: datetime) -> KeypadEnableMessage | None:
    """Parse KES (Keypad Enable State) message.

    Format: KES, [pp:ll:aa], <enabled|disabled>
    """
    if len(parts) < 3:
        return None

    address = normalize_address(parts[1])
    enabled = parts[2].lower() == "enabled"

    return KeypadEnableMessage(
        raw=line,
        timestamp=ts,
        address=address,
        enabled=enabled,
    )


def _parse_gss(
    line: str, parts: list[str], ts: datetime
) -> GrafikEyeSceneMessage | None:
    """Parse GSS (GRAFIK Eye Scene Select) message.

    Format: GSS, [pp:ll:aa], <scene>
    """
    if len(parts) < 3:
        return None

    address = normalize_address(parts[1])
    try:
        scene = int(parts[2])
    except ValueError:
        return None

    return GrafikEyeSceneMessage(
        raw=line,
        timestamp=ts,
        address=address,
        scene=scene,
    )


def _parse_svs(line: str, parts: list[str], ts: datetime) -> SivoiaSceneMessage | None:
    """Parse SVS (Sivoia Scene) message.

    Format: SVS, [pp:ll:aa], <command>, <status>
    """
    if len(parts) < 4:
        return None

    address = normalize_address(parts[1])
    command = parts[2]
    status = parts[3]

    return SivoiaSceneMessage(
        raw=line,
        timestamp=ts,
        address=address,
        command=command,
        status=status,
    )


# =============================================================================
# Parser Registry
# =============================================================================

# Map command prefixes to parser functions
_PARSERS: dict[str, Callable[[str, list[str], datetime], AnyMessage | None]] = {
    # Keypad LED state
    "KLS": _parse_kls,
    # Dimmer level
    "DL": _parse_dl,
    # Keypad button events
    "KBP": _make_button_parser(ButtonEventType.PRESSED, "keypad"),
    "KBR": _make_button_parser(ButtonEventType.RELEASED, "keypad"),
    "KBH": _make_button_parser(ButtonEventType.HOLD, "keypad"),
    "KBDT": _make_button_parser(ButtonEventType.DOUBLE_TAP, "keypad"),
    # Dimmer button events
    "DBP": _make_button_parser(ButtonEventType.PRESSED, "dimmer"),
    "DBR": _make_button_parser(ButtonEventType.RELEASED, "dimmer"),
    "DBH": _make_button_parser(ButtonEventType.HOLD, "dimmer"),
    "DBDT": _make_button_parser(ButtonEventType.DOUBLE_TAP, "dimmer"),
    # Sivoia control button events
    "SVBP": _make_button_parser(ButtonEventType.PRESSED, "sivoia"),
    "SVBR": _make_button_parser(ButtonEventType.RELEASED, "sivoia"),
    "SVBH": _make_button_parser(ButtonEventType.HOLD, "sivoia"),
    "SVBDT": _make_button_parser(ButtonEventType.DOUBLE_TAP, "sivoia"),
    # Keypad enable state
    "KES": _parse_kes,
    # GRAFIK Eye scene
    "GSS": _parse_gss,
    # Sivoia scene
    "SVS": _parse_svs,
}

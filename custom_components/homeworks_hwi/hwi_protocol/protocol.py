"""Protocol parsing for Homeworks RS-232 messages.

This module handles:
- Message framing (CRLF-delimited)
- Parsing incoming messages into typed structures
- Address normalization

All parsing is stateless - just input bytes, output messages.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import (
    UTC,
    date,
    datetime,
    time,
)

from .messages import (
    AnyMessage,
    ButtonEventMessage,
    ButtonEventType,
    DimmerLevelMessage,
    DstChangedMessage,
    DstManualUnsupportedMessage,
    DstStateMessage,
    GrafikEyeSceneMessage,
    KeypadEnableMessage,
    KLSMessage,
    ProcessorDateMessage,
    ProcessorTimeMessage,
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
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("RX: %s", line.decode("utf-8", "replace"))
                try:
                    msg = self._parse_line(line.decode("utf-8"))
                    if msg:
                        messages.append(msg)
                except UnicodeDecodeError:
                    _LOGGER.warning("Invalid message encoding: %s", line)
                except Exception as err:  # noqa: BLE001 - a bad line must not stop parsing
                    _LOGGER.warning("Failed to parse message: %s - %s", line, err)

        return messages

    def reset(self) -> None:
        """Clear the buffer."""
        if self._buffer:
            _LOGGER.debug("RX (discarded partial): %r", self._buffer)
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

        # Clock replies have no comma, so match them by prefix first.
        for pattern, clock_parser in _CLOCK_PARSERS:
            match = pattern.fullmatch(line)
            if match:
                return clock_parser(line, match, datetime.now(tz=UTC))

        # Split on commas. The protocol spec (L232/command_formatting.htm)
        # states spaces are insignificant, so do not rely on ", " as the
        # delimiter — a processor emitting "KBP,[01:04:04],1" must parse too.
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            return None

        command = parts[0].upper()
        timestamp = datetime.now(tz=UTC)

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
        level = round(float(parts[2]))
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
# Clock Reply Parsers (no comma, matched by pattern)
# =============================================================================


def _parse_processor_time(
    line: str, match: re.Match[str], ts: datetime
) -> ProcessorTimeMessage:
    """Parse an ST ack (HH:MM) or RST2 reply (HH:MM:SS).

    Format: Processor Time: HH:MM[:SS]
    """
    hour, minute, second = match.groups()
    # Validate the values; time() raises ValueError for an invalid field.
    time(int(hour), int(minute), int(second or 0))
    return ProcessorTimeMessage(
        raw=line,
        timestamp=ts,
        hour=int(hour),
        minute=int(minute),
        second=int(second) if second is not None else None,
    )


def _parse_processor_date(
    line: str, match: re.Match[str], ts: datetime
) -> ProcessorDateMessage:
    """Parse an RSD reply or SD ack.

    Format: Processor Date: <Weekday> MM/DD/YYYY
    """
    month, day, year = match.groups()
    return ProcessorDateMessage(
        raw=line,
        timestamp=ts,
        date=date(int(year), int(month), int(day)),
    )


def _parse_dst_state(line: str, match: re.Match[str], ts: datetime) -> DstStateMessage:
    """Parse an RDST reply.

    Format: DST = True|False
    """
    return DstStateMessage(
        raw=line,
        timestamp=ts,
        active=match.group(1).lower() == "true",
    )


def _parse_dst_manual_unsupported(
    line: str, match: re.Match[str], ts: datetime
) -> DstManualUnsupportedMessage:
    """Parse the STARTDST/ENDDST rejection of an automatic-DST database."""
    return DstManualUnsupportedMessage(raw=line, timestamp=ts)


def _parse_dst_changed(
    line: str, match: re.Match[str], ts: datetime
) -> DstChangedMessage:
    """Parse a STARTDST/ENDDST acceptance.

    Format: Daylight Savings Time Started|Ended
    """
    return DstChangedMessage(
        raw=line,
        timestamp=ts,
        started=match.group(1).lower() == "started",
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

# Clock replies, tried in order before the comma split. Hardware strings
# are in the clock sync design doc and tests/test_clock_protocol.py.
_CLOCK_PARSERS: tuple[
    tuple[re.Pattern[str], Callable[[str, re.Match[str], datetime], AnyMessage]],
    ...,
] = (
    (
        re.compile(r"processor time:\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", re.IGNORECASE),
        _parse_processor_time,
    ),
    (
        re.compile(
            r"processor date:\s*(?:[a-z]+\s+)?(\d{2})/(\d{2})/(\d{4})\s*",
            re.IGNORECASE,
        ),
        _parse_processor_date,
    ),
    (
        re.compile(r"dst\s*=\s*(true|false)\s*", re.IGNORECASE),
        _parse_dst_state,
    ),
    (
        re.compile(r".*does not support manual dst.*", re.IGNORECASE),
        _parse_dst_manual_unsupported,
    ),
    (
        re.compile(r"daylight savings time (started|ended)\s*", re.IGNORECASE),
        _parse_dst_changed,
    ),
)

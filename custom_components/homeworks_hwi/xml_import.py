"""XML import parser for Lutron HomeWorks Designer Maximum export files.

Parses the structured XML export from Lutron Designer software and extracts
all importable devices (dimmers, QED shades, motor covers, CCO relays,
keypads with buttons, and CCI inputs).

This module is pure Python with no Home Assistant dependencies, allowing
standalone testing and reuse.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Final

from .const import DEFAULT_RAISE_LOWER_RELEASE_DELAY

# XML size limit (25MB — large installations produce big exports)
MAX_XML_SIZE: Final = 25_000_000

# Device types to skip during keypad/input import
_SKIP_DEVICE_TYPES: Final = frozenset(
    {
        "NON-SYSTEM DEVICE",
        "HHP",
        "HOMEWORKS VAREO DIMMER/SWITCH",
        "REMOTE DIMMER/SWITCH",
    }
)

# Output types that we import
_IMPORTABLE_OUTPUT_TYPES: Final = frozenset(
    {
        "DIMMER",
        "QED SHADE",
        "MOTOR",
        "MAINTAINED OUTPUT",
    }
)


@dataclass
class ParsedButton:
    """A parsed button from a keypad."""

    number: int
    name: str
    has_led: bool
    release_delay: float


@dataclass
class ParsedKeypad:
    """A parsed keypad device."""

    address: str  # Raw address like "1:5:1"
    name: str  # WebKeypadName
    model: str
    buttons: list[ParsedButton] = field(default_factory=list)


@dataclass
class ParsedOutput:
    """A parsed output (dimmer, shade, motor, or CCO)."""

    address: str  # Raw address like "1:1:0:4:1"
    name: str
    output_type: str  # DIMMER, QED SHADE, MOTOR, MAINTAINED OUTPUT


@dataclass
class ParsedCCIInput:
    """A parsed CCI input."""

    address: str  # Processor address (e.g., "1")
    input_number: int  # 1-24
    name: str


@dataclass
class ParsedRoom:
    """A parsed room containing devices."""

    name: str
    room_id: int
    outputs: list[ParsedOutput] = field(default_factory=list)
    keypads: list[ParsedKeypad] = field(default_factory=list)
    cci_inputs: list[ParsedCCIInput] = field(default_factory=list)

    @property
    def importable_device_count(self) -> int:
        """Count of importable devices in this room."""
        return len(self.outputs) + len(self.keypads) + len(self.cci_inputs)


@dataclass
class ParsedArea:
    """A parsed area (floor/wing/zone) containing rooms."""

    name: str
    area_id: int
    rooms: list[ParsedRoom] = field(default_factory=list)


@dataclass
class ParsedProject:
    """Complete parsed XML project."""

    project_name: str
    areas: list[ParsedArea] = field(default_factory=list)

    @property
    def total_dimmers(self) -> int:
        """Count all dimmer outputs."""
        return sum(
            1
            for area in self.areas
            for room in area.rooms
            for output in room.outputs
            if output.output_type == "DIMMER"
        )

    @property
    def total_qed_shades(self) -> int:
        """Count all QED shade outputs."""
        return sum(
            1
            for area in self.areas
            for room in area.rooms
            for output in room.outputs
            if output.output_type == "QED SHADE"
        )

    @property
    def total_motor_covers(self) -> int:
        """Count all motor cover outputs."""
        return sum(
            1
            for area in self.areas
            for room in area.rooms
            for output in room.outputs
            if output.output_type == "MOTOR"
        )

    @property
    def total_cco_devices(self) -> int:
        """Count all maintained output (CCO) devices."""
        return sum(
            1
            for area in self.areas
            for room in area.rooms
            for output in room.outputs
            if output.output_type == "MAINTAINED OUTPUT"
        )

    @property
    def total_keypads(self) -> int:
        """Count all keypads."""
        return sum(
            1
            for area in self.areas
            for room in area.rooms
            for keypad in room.keypads
        )

    @property
    def total_buttons(self) -> int:
        """Count all programmed buttons across all keypads."""
        return sum(
            len(keypad.buttons)
            for area in self.areas
            for room in area.rooms
            for keypad in room.keypads
        )

    @property
    def total_cci_inputs(self) -> int:
        """Count all CCI inputs."""
        return sum(
            1
            for area in self.areas
            for room in area.rooms
            for cci in room.cci_inputs
        )


class XMLImportError(Exception):
    """Base exception for XML import errors."""

    def __init__(self, error_key: str, detail: str = "") -> None:
        """Initialize with an error key for translation lookup."""
        self.error_key = error_key
        self.detail = detail
        super().__init__(f"{error_key}: {detail}" if detail else error_key)


def parse_homeworks_xml(content: str) -> ParsedProject:
    """Parse a HomeWorks Maximum XML export into structured data.

    Args:
        content: Raw XML string content.

    Returns:
        ParsedProject with all discovered devices.

    Raises:
        XMLImportError: If the XML is invalid, not a Maximum export, or too large.
    """
    if len(content.encode("utf-8")) > MAX_XML_SIZE:
        raise XMLImportError("xml_too_large")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as err:
        raise XMLImportError("invalid_xml", str(err)) from err

    if root.tag != "HWProject":
        raise XMLImportError("invalid_xml", f"Root element is '{root.tag}', expected 'HWProject'")

    file_type_el = root.find("FileType")
    if file_type_el is None or file_type_el.text != "Maximum":
        raise XMLImportError("not_maximum_export")

    project_name_el = root.find("ProjectName")
    project_name = project_name_el.text if project_name_el is not None and project_name_el.text else "Unknown Project"

    project = ParsedProject(project_name=project_name)

    for area_el in root.findall("Area"):
        parsed_area = _parse_area(area_el)
        if parsed_area:
            project.areas.append(parsed_area)

    return project


def _parse_area(area_el: ET.Element) -> ParsedArea | None:
    """Parse an Area element."""
    name_el = area_el.find("Name")
    id_el = area_el.find("Id")

    name = name_el.text if name_el is not None and name_el.text else "Unknown Area"
    area_id = int(id_el.text) if id_el is not None and id_el.text else 0

    parsed_area = ParsedArea(name=name, area_id=area_id)

    for room_el in area_el.findall("Room"):
        parsed_room = _parse_room(room_el)
        if parsed_room:
            parsed_area.rooms.append(parsed_room)

    return parsed_area if parsed_area.rooms else None


def _parse_room(room_el: ET.Element) -> ParsedRoom | None:
    """Parse a Room element."""
    name_el = room_el.find("Name")
    id_el = room_el.find("Id")

    name = name_el.text if name_el is not None and name_el.text else "Unknown Room"
    room_id = int(id_el.text) if id_el is not None and id_el.text else 0

    parsed_room = ParsedRoom(name=name, room_id=room_id)

    # Parse outputs
    outputs_el = room_el.find("Outputs")
    if outputs_el is not None:
        for output_el in outputs_el.findall("Output"):
            parsed_output = _parse_output(output_el)
            if parsed_output:
                parsed_room.outputs.append(parsed_output)

    # Parse inputs (keypads and CCI)
    inputs_el = room_el.find("Inputs")
    if inputs_el is not None:
        for station_el in inputs_el.findall("ControlStation"):
            devices_el = station_el.find("Devices")
            if devices_el is None:
                continue
            for device_el in devices_el.findall("Device"):
                _parse_input_device(device_el, parsed_room)

    # Only return rooms that have importable devices
    if parsed_room.importable_device_count == 0:
        return None

    return parsed_room


def _parse_output(output_el: ET.Element) -> ParsedOutput | None:
    """Parse an Output element."""
    type_el = output_el.find("Type")
    if type_el is None or not type_el.text:
        return None

    output_type = type_el.text.strip()
    if output_type not in _IMPORTABLE_OUTPUT_TYPES:
        return None

    address_el = output_el.find("Address")
    name_el = output_el.find("Name")

    address = address_el.text.strip() if address_el is not None and address_el.text else ""
    name = name_el.text.strip() if name_el is not None and name_el.text else ""

    if not address:
        return None

    return ParsedOutput(address=address, name=name, output_type=output_type)


def _parse_input_device(device_el: ET.Element, room: ParsedRoom) -> None:
    """Parse a Device element from the Inputs section."""
    type_el = device_el.find("Type")
    if type_el is None or not type_el.text:
        return

    device_type = type_el.text.strip()

    # Skip non-importable device types
    if device_type in _SKIP_DEVICE_TYPES:
        return

    address_el = device_el.find("Address")
    address = address_el.text.strip() if address_el is not None and address_el.text else ""

    if device_type == "KEYPAD" and address:
        _parse_keypad(device_el, address, room)
    elif device_type == "ONBOARD CCI" and address:
        _parse_cci_device(device_el, address, room)
    elif device_type == "CCO":
        # CCO devices in Inputs section are the physical module — outputs
        # are already captured from the Outputs section as MAINTAINED OUTPUT.
        # Skip to avoid double-importing.
        pass


def _parse_keypad(device_el: ET.Element, address: str, room: ParsedRoom) -> None:
    """Parse a keypad device and its buttons."""
    buttons_el = device_el.find("Buttons")
    if buttons_el is None:
        return

    button_elements = buttons_el.findall("Button")
    if not button_elements:
        return

    web_name_el = device_el.find("WebKeypadName")
    model_el = device_el.find("Model")

    name = web_name_el.text.strip() if web_name_el is not None and web_name_el.text else ""
    model = model_el.text.strip() if model_el is not None and model_el.text else ""

    keypad = ParsedKeypad(address=address, name=name, model=model)

    for button_el in button_elements:
        parsed_button = _parse_button(button_el)
        if parsed_button:
            keypad.buttons.append(parsed_button)

    # Only import keypads that have at least one programmed button
    if keypad.buttons:
        room.keypads.append(keypad)


def _parse_button(button_el: ET.Element) -> ParsedButton | None:
    """Parse a single button element.

    Filters out "Not Programmed" buttons.
    Detects LED presence from DisplayProperties.
    Detects release_delay need from Master Raise/Lower type + Release action.
    """
    type_el = button_el.find("Type")
    if type_el is None or not type_el.text:
        return None

    button_type = type_el.text.strip()

    # Hard-filter: never import unprogrammed buttons
    if button_type == "Not Programmed":
        return None

    number_el = button_el.find("Number")
    name_el = button_el.find("Name")

    if number_el is None or not number_el.text:
        return None

    number = int(number_el.text.strip())
    name = name_el.text.strip() if name_el is not None and name_el.text else f"Button {number}"

    # Detect LED from DisplayProperties/Type
    has_led = _detect_has_led(button_el)

    # Detect release_delay for Master Raise/Lower buttons
    release_delay = _detect_release_delay(button_type)

    return ParsedButton(
        number=number,
        name=name,
        has_led=has_led,
        release_delay=release_delay,
    )


def _detect_has_led(button_el: ET.Element) -> bool:
    """Detect if a button has an LED from DisplayProperties.

    Rules:
    - "BUTTON WITH LED" → True
    - "BUTTON WITHOUT LED" → False
    - "RAISE BUTTON" / "LOWER BUTTON" → False
    - Missing/empty → False
    """
    display_el = button_el.find("DisplayProperties")
    if display_el is None:
        return False

    type_el = display_el.find("Type")
    if type_el is None or not type_el.text:
        return False

    display_type = type_el.text.strip().upper()
    return "WITH LED" in display_type


def _detect_release_delay(button_type: str) -> float:
    """Return appropriate release_delay for a button based on its type.

    Master Raise/Lower buttons require a non-zero release_delay so that
    KBR (release) fires after KBP (press), stopping the dimmer ramp.
    All other button types are press-only (scenes, toggles) and need 0.0.
    """
    if button_type.startswith("Master Raise/Lower"):
        return DEFAULT_RAISE_LOWER_RELEASE_DELAY
    return 0.0


def _parse_cci_device(device_el: ET.Element, address: str, room: ParsedRoom) -> None:
    """Parse a CCI (Contact Closure Input) device.

    CCI devices have buttons that represent individual inputs.
    Each input becomes a binary sensor.
    """
    buttons_el = device_el.find("Buttons")
    if buttons_el is None:
        return

    for button_el in buttons_el.findall("Button"):
        number_el = button_el.find("Number")
        name_el = button_el.find("Name")

        if number_el is None or not number_el.text:
            continue

        input_number = int(number_el.text.strip())
        name = name_el.text.strip() if name_el is not None and name_el.text else f"CCI Input {input_number}"

        room.cci_inputs.append(
            ParsedCCIInput(
                address=address,
                input_number=input_number,
                name=name,
            )
        )


def get_cco_address_parts(output_address: str) -> tuple[str, int]:
    """Split a MAINTAINED OUTPUT address into CCO keypad address + relay number.

    MAINTAINED OUTPUT addresses like "1:5:3:1" are split into:
    - CCO keypad address: "1:5:3" (first 3 parts)
    - Relay number: 1 (last part)

    Args:
        output_address: Raw address string from XML (e.g., "1:5:3:1")

    Returns:
        Tuple of (keypad_address, relay_number)

    Raises:
        ValueError: If address doesn't have exactly 4 parts.
    """
    parts = output_address.split(":")
    if len(parts) != 4:
        raise ValueError(
            f"MAINTAINED OUTPUT address must have 4 parts, got {len(parts)}: {output_address}"
        )
    keypad_address = ":".join(parts[:3])
    relay_number = int(parts[3])
    return keypad_address, relay_number

"""Tests for the XML import parser module."""

import pytest

from custom_components.homeworks_hwi.xml_import import (
    MAX_XML_SIZE,
    ParsedProject,
    XMLImportError,
    get_cco_address_parts,
    parse_homeworks_xml,
)


# === Minimal valid XML for testing ===

MINIMAL_VALID_XML = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Test Project</ProjectName>
  <FileType>Maximum</FileType>
  <Area>
    <Name>MAIN LEVEL</Name>
    <Id>1</Id>
    <Room>
      <Name>FOYER</Name>
      <Id>1</Id>
      <Outputs>
        <Output>
          <Name>OVERHEAD</Name>
          <Address>1:1:0:4:1</Address>
          <Type>DIMMER</Type>
        </Output>
      </Outputs>
      <Inputs/>
    </Room>
  </Area>
</HWProject>
"""

FULL_DEVICE_TYPES_XML = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Full Test</ProjectName>
  <FileType>Maximum</FileType>
  <Area>
    <Name>MAIN</Name>
    <Id>1</Id>
    <Room>
      <Name>LIVING ROOM</Name>
      <Id>1</Id>
      <Outputs>
        <Output>
          <Name>COVE LIGHTING</Name>
          <Address>1:1:0:6:2</Address>
          <Type>DIMMER</Type>
        </Output>
        <Output>
          <Name>LEFT SHADE</Name>
          <Address>1:6:1:5</Address>
          <Type>QED SHADE</Type>
        </Output>
        <Output>
          <Name>WINDOW TREATMENT</Name>
          <Address>1:1:1:2:1</Address>
          <Type>MOTOR</Type>
        </Output>
        <Output>
          <Name>FIREPLACE</Name>
          <Address>1:5:3:2</Address>
          <Type>MAINTAINED OUTPUT</Type>
        </Output>
      </Outputs>
      <Inputs>
        <ControlStation>
          <Name>Control Station 1</Name>
          <Id>1</Id>
          <Devices>
            <Device>
              <Id>1</Id>
              <Address>1:5:1</Address>
              <Model>ST-5BRL-NI</Model>
              <GangPosition>1</GangPosition>
              <Type>KEYPAD</Type>
              <WebEnabled>True</WebEnabled>
              <WebKeypadName>Living Room</WebKeypadName>
              <Buttons>
                <Button>
                  <Number>1</Number>
                  <Name>SCENE 1</Name>
                  <Type>Default Single Action</Type>
                  <Actions>
                    <Press>True</Press>
                    <Release>False</Release>
                  </Actions>
                  <DisplayProperties>
                    <Type>BUTTON WITH LED</Type>
                  </DisplayProperties>
                </Button>
                <Button>
                  <Number>2</Number>
                  <Name>OFF</Name>
                  <Type>Default Single Action</Type>
                  <Actions>
                    <Press>True</Press>
                    <Release>False</Release>
                  </Actions>
                  <DisplayProperties>
                    <Type>BUTTON WITH LED</Type>
                  </DisplayProperties>
                </Button>
                <Button>
                  <Number>3</Number>
                  <Name>Button 3</Name>
                  <Type>Not Programmed</Type>
                  <Actions>
                    <Press>True</Press>
                    <Release>False</Release>
                  </Actions>
                  <DisplayProperties/>
                </Button>
                <Button>
                  <Number>23</Number>
                  <Name>Button 23</Name>
                  <Type>Master Raise/Lower - Lower</Type>
                  <Actions>
                    <Press>True</Press>
                    <Release>True</Release>
                  </Actions>
                  <DisplayProperties>
                    <Type>LOWER BUTTON</Type>
                  </DisplayProperties>
                </Button>
                <Button>
                  <Number>24</Number>
                  <Name>Button 24</Name>
                  <Type>Master Raise/Lower - Raise</Type>
                  <Actions>
                    <Press>True</Press>
                    <Release>True</Release>
                  </Actions>
                  <DisplayProperties>
                    <Type>RAISE BUTTON</Type>
                  </DisplayProperties>
                </Button>
              </Buttons>
            </Device>
          </Devices>
        </ControlStation>
        <ControlStation>
          <Name>Non-system</Name>
          <Id>2</Id>
          <Devices>
            <Device>
              <Id>2</Id>
              <Address/>
              <Model>CAR-15H</Model>
              <GangPosition>1</GangPosition>
              <Type>NON-SYSTEM DEVICE</Type>
              <WebEnabled>False</WebEnabled>
              <WebKeypadName/>
              <Buttons/>
            </Device>
          </Devices>
        </ControlStation>
      </Inputs>
    </Room>
  </Area>
  <Area>
    <Name>LOWER LEVEL</Name>
    <Id>2</Id>
    <Room>
      <Name>MECHANICAL</Name>
      <Id>10</Id>
      <Outputs/>
      <Inputs>
        <ControlStation>
          <Name>Panel</Name>
          <Id>5</Id>
          <Devices>
            <Device>
              <Id>10</Id>
              <Address>1</Address>
              <Model>H8P5-D48-120</Model>
              <GangPosition>3</GangPosition>
              <Type>ONBOARD CCI</Type>
              <WebEnabled>False</WebEnabled>
              <WebKeypadName/>
              <Buttons>
                <Button>
                  <Number>1</Number>
                  <Name>Button 1</Name>
                  <Type>Not Programmed</Type>
                </Button>
                <Button>
                  <Number>2</Number>
                  <Name>Button 2</Name>
                  <Type>Not Programmed</Type>
                </Button>
              </Buttons>
            </Device>
          </Devices>
        </ControlStation>
      </Inputs>
    </Room>
  </Area>
</HWProject>
"""

SKIP_DEVICES_XML = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Skip Test</ProjectName>
  <FileType>Maximum</FileType>
  <Area>
    <Name>TEST</Name>
    <Id>1</Id>
    <Room>
      <Name>ROOM1</Name>
      <Id>1</Id>
      <Outputs>
        <Output>
          <Name>LIGHT</Name>
          <Address>1:1:0:1:1</Address>
          <Type>DIMMER</Type>
        </Output>
      </Outputs>
      <Inputs>
        <ControlStation>
          <Name>Vareo</Name>
          <Id>1</Id>
          <Devices>
            <Device>
              <Id>1</Id>
              <Address>1:4:1:2:1</Address>
              <Model>HWV-600D</Model>
              <GangPosition>1</GangPosition>
              <Type>HOMEWORKS VAREO DIMMER/SWITCH</Type>
              <WebEnabled>False</WebEnabled>
              <WebKeypadName/>
              <Buttons/>
            </Device>
          </Devices>
        </ControlStation>
        <ControlStation>
          <Name>Remote</Name>
          <Id>2</Id>
          <Devices>
            <Device>
              <Id>2</Id>
              <Address/>
              <Model>VETS-R</Model>
              <GangPosition>1</GangPosition>
              <Type>REMOTE DIMMER/SWITCH</Type>
              <WebEnabled>False</WebEnabled>
              <WebKeypadName/>
              <Buttons/>
            </Device>
          </Devices>
        </ControlStation>
        <ControlStation>
          <Name>HHP</Name>
          <Id>3</Id>
          <Devices>
            <Device>
              <Id>3</Id>
              <Address/>
              <Model>HWI-HHPJ-Q1</Model>
              <GangPosition>1</GangPosition>
              <Type>HHP</Type>
              <WebEnabled>False</WebEnabled>
              <WebKeypadName/>
              <Buttons/>
            </Device>
          </Devices>
        </ControlStation>
      </Inputs>
    </Room>
  </Area>
</HWProject>
"""


class TestXMLParserValidation:
    """Test XML validation and error handling."""

    def test_invalid_xml(self) -> None:
        """Test that malformed XML raises XMLImportError."""
        with pytest.raises(XMLImportError) as exc_info:
            parse_homeworks_xml("<not valid xml")
        assert exc_info.value.error_key == "invalid_xml"

    def test_wrong_root_element(self) -> None:
        """Test that wrong root element raises error."""
        with pytest.raises(XMLImportError) as exc_info:
            parse_homeworks_xml("<SomeOtherRoot><FileType>Maximum</FileType></SomeOtherRoot>")
        assert exc_info.value.error_key == "invalid_xml"

    def test_not_maximum_export(self) -> None:
        """Test that non-Maximum export raises error."""
        xml = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Test</ProjectName>
  <FileType>Minimum</FileType>
</HWProject>
"""
        with pytest.raises(XMLImportError) as exc_info:
            parse_homeworks_xml(xml)
        assert exc_info.value.error_key == "not_maximum_export"

    def test_missing_file_type(self) -> None:
        """Test that missing FileType raises error."""
        xml = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Test</ProjectName>
</HWProject>
"""
        with pytest.raises(XMLImportError) as exc_info:
            parse_homeworks_xml(xml)
        assert exc_info.value.error_key == "not_maximum_export"

    def test_xml_too_large(self) -> None:
        """Test that oversized XML raises error."""
        # Create content just over the limit
        large_content = "x" * (MAX_XML_SIZE + 1)
        with pytest.raises(XMLImportError) as exc_info:
            parse_homeworks_xml(large_content)
        assert exc_info.value.error_key == "xml_too_large"

    def test_valid_minimal_xml(self) -> None:
        """Test parsing a minimal valid XML."""
        result = parse_homeworks_xml(MINIMAL_VALID_XML)
        assert isinstance(result, ParsedProject)
        assert result.project_name == "Test Project"
        assert len(result.areas) == 1
        assert result.areas[0].name == "MAIN LEVEL"


class TestXMLParserOutputs:
    """Test parsing of Output elements."""

    def test_dimmer_output(self) -> None:
        """Test that DIMMER outputs are parsed correctly."""
        result = parse_homeworks_xml(MINIMAL_VALID_XML)
        room = result.areas[0].rooms[0]
        assert len(room.outputs) == 1
        assert room.outputs[0].name == "OVERHEAD"
        assert room.outputs[0].address == "1:1:0:4:1"
        assert room.outputs[0].output_type == "DIMMER"

    def test_all_output_types(self) -> None:
        """Test that all importable output types are parsed."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        room = result.areas[0].rooms[0]
        types = {o.output_type for o in room.outputs}
        assert types == {"DIMMER", "QED SHADE", "MOTOR", "MAINTAINED OUTPUT"}

    def test_output_counts(self) -> None:
        """Test aggregate device counts."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        assert result.total_dimmers == 1
        assert result.total_qed_shades == 1
        assert result.total_motor_covers == 1
        assert result.total_cco_devices == 1


class TestXMLParserKeypads:
    """Test parsing of Keypad devices."""

    def test_keypad_parsed(self) -> None:
        """Test that keypads are extracted."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        room = result.areas[0].rooms[0]
        assert len(room.keypads) == 1
        kp = room.keypads[0]
        assert kp.address == "1:5:1"
        assert kp.name == "Living Room"
        assert kp.model == "ST-5BRL-NI"

    def test_unprogrammed_buttons_filtered(self) -> None:
        """Test that 'Not Programmed' buttons are excluded."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        kp = result.areas[0].rooms[0].keypads[0]
        button_numbers = [b.number for b in kp.buttons]
        # Button 3 is "Not Programmed" — should be filtered
        assert 3 not in button_numbers
        # Buttons 1, 2, 23, 24 are programmed
        assert 1 in button_numbers
        assert 2 in button_numbers
        assert 23 in button_numbers
        assert 24 in button_numbers

    def test_button_led_detection(self) -> None:
        """Test LED detection from DisplayProperties."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        kp = result.areas[0].rooms[0].keypads[0]
        btn1 = next(b for b in kp.buttons if b.number == 1)
        btn23 = next(b for b in kp.buttons if b.number == 23)
        # Button 1 has "BUTTON WITH LED" → True
        assert btn1.has_led is True
        # Button 23 has "LOWER BUTTON" → False
        assert btn23.has_led is False

    def test_total_buttons(self) -> None:
        """Test total button count across all keypads."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        # 4 programmed buttons (1, 2, 23, 24)
        assert result.total_buttons == 4


class TestXMLParserCCI:
    """Test parsing of CCI devices."""

    def test_cci_parsed(self) -> None:
        """Test that CCI inputs are extracted."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        # CCI is in LOWER LEVEL area → MECHANICAL room
        assert len(result.areas) == 2
        lower_area = result.areas[1]
        assert lower_area.name == "LOWER LEVEL"
        mech_room = lower_area.rooms[0]
        assert mech_room.name == "MECHANICAL"
        assert len(mech_room.cci_inputs) == 2
        assert mech_room.cci_inputs[0].input_number == 1
        assert mech_room.cci_inputs[1].input_number == 2

    def test_cci_address(self) -> None:
        """Test CCI address extraction."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        mech_room = result.areas[1].rooms[0]
        assert mech_room.cci_inputs[0].address == "1"


class TestXMLParserSkipDevices:
    """Test that non-importable device types are skipped."""

    def test_skip_vareo(self) -> None:
        """Test that HOMEWORKS VAREO DIMMER/SWITCH is skipped."""
        result = parse_homeworks_xml(SKIP_DEVICES_XML)
        room = result.areas[0].rooms[0]
        # Only the dimmer output should be present, no keypads from skipped devices
        assert len(room.keypads) == 0

    def test_skip_nonsystem(self) -> None:
        """Test that NON-SYSTEM DEVICE is skipped."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        room = result.areas[0].rooms[0]
        # Only 1 keypad (the real one), not the NON-SYSTEM DEVICE
        assert len(room.keypads) == 1


class TestXMLParserEmptyRooms:
    """Test that rooms with no importable devices are excluded."""

    def test_empty_room_excluded(self) -> None:
        """Test that rooms with only non-importable devices are skipped."""
        xml = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Empty Test</ProjectName>
  <FileType>Maximum</FileType>
  <Area>
    <Name>TEST</Name>
    <Id>1</Id>
    <Room>
      <Name>EMPTY ROOM</Name>
      <Id>1</Id>
      <Outputs/>
      <Inputs>
        <ControlStation>
          <Name>CS</Name>
          <Id>1</Id>
          <Devices>
            <Device>
              <Id>1</Id>
              <Address/>
              <Model>CAR-15H</Model>
              <GangPosition>1</GangPosition>
              <Type>NON-SYSTEM DEVICE</Type>
              <WebEnabled>False</WebEnabled>
              <WebKeypadName/>
              <Buttons/>
            </Device>
          </Devices>
        </ControlStation>
      </Inputs>
    </Room>
    <Room>
      <Name>VALID ROOM</Name>
      <Id>2</Id>
      <Outputs>
        <Output>
          <Name>LIGHT</Name>
          <Address>1:1:0:1:1</Address>
          <Type>DIMMER</Type>
        </Output>
      </Outputs>
      <Inputs/>
    </Room>
  </Area>
</HWProject>
"""
        result = parse_homeworks_xml(xml)
        # Only VALID ROOM should appear (EMPTY ROOM has 0 importable devices)
        assert len(result.areas[0].rooms) == 1
        assert result.areas[0].rooms[0].name == "VALID ROOM"


class TestCCOAddressParts:
    """Test the CCO address splitting utility."""

    def test_valid_4_part_address(self) -> None:
        """Test splitting a valid 4-part MAINTAINED OUTPUT address."""
        addr, relay = get_cco_address_parts("1:5:3:1")
        assert addr == "1:5:3"
        assert relay == 1

    def test_valid_4_part_address_higher_relay(self) -> None:
        """Test with higher relay numbers."""
        addr, relay = get_cco_address_parts("1:5:3:8")
        assert addr == "1:5:3"
        assert relay == 8

    def test_invalid_3_part_address(self) -> None:
        """Test that 3-part address raises ValueError."""
        with pytest.raises(ValueError):
            get_cco_address_parts("1:5:3")

    def test_invalid_5_part_address(self) -> None:
        """Test that 5-part address raises ValueError."""
        with pytest.raises(ValueError):
            get_cco_address_parts("1:5:3:1:2")


class TestXMLParserRealWorldStructure:
    """Test with a structure matching real-world HomeWorks exports."""

    def test_multiple_areas(self) -> None:
        """Test parsing multiple areas."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        assert len(result.areas) == 2
        assert result.areas[0].name == "MAIN"
        assert result.areas[1].name == "LOWER LEVEL"

    def test_project_name(self) -> None:
        """Test project name extraction."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        assert result.project_name == "Full Test"

    def test_room_ids(self) -> None:
        """Test room ID extraction."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        room = result.areas[0].rooms[0]
        assert room.room_id == 1
        assert room.name == "LIVING ROOM"

    def test_importable_device_count(self) -> None:
        """Test importable_device_count property."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        room = result.areas[0].rooms[0]
        # 4 outputs + 1 keypad + 0 CCI = 5
        assert room.importable_device_count == 5

    def test_maintained_output_address(self) -> None:
        """Test MAINTAINED OUTPUT addresses are preserved raw."""
        result = parse_homeworks_xml(FULL_DEVICE_TYPES_XML)
        room = result.areas[0].rooms[0]
        cco = next(o for o in room.outputs if o.output_type == "MAINTAINED OUTPUT")
        assert cco.address == "1:5:3:2"
        # Verify it can be split
        addr, relay = get_cco_address_parts(cco.address)
        assert addr == "1:5:3"
        assert relay == 2

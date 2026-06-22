"""Tests for XML import config flow integration.

Tests the config flow steps end-to-end: parsing, area mapping,
device selection, CCO/CCI classification, and commit logic.
"""

import pytest
from unittest.mock import MagicMock

from custom_components.homeworks_hwi.config_flow import (
    _find_existing_by_address,
    _is_duplicate_by_address,
    _is_duplicate_cco,
    _is_duplicate_cci,
    _is_duplicate_dimmer,
    _is_duplicate_keypad,
    _is_duplicate_qed_cover,
    _is_duplicate_rpm_cover,
    async_parse_xml,
    get_xml_cco_classify_schema,
    get_xml_cci_classify_schema,
    get_xml_confirm_description_placeholders,
    validate_xml_area_mapping,
    validate_xml_cco_classify,
    validate_xml_cci_classify,
    validate_xml_confirm_import,
    validate_xml_device_selection,
)
from custom_components.homeworks_hwi.const import (
    CONF_ADDR,
    CONF_AREA,
    CONF_BUTTON_NUMBER,
    CONF_BUTTONS,
    CONF_CCI_DEVICES,
    CONF_CCO_DEVICES,
    CONF_DIMMERS,
    CONF_ENTITY_TYPE,
    CONF_INPUT_NUMBER,
    CONF_KEYPADS,
    CONF_LED,
    CONF_NAME,
    CONF_NUMBER,
    CONF_QED_COVERS,
    CONF_RPM_COVERS,
    CCO_TYPE_SWITCH,
    CCO_TYPE_LIGHT,
    CONF_DEVICE_CLASS,
    CONF_RELEASE_DELAY,
)
from custom_components.homeworks_hwi.xml_import import (
    XMLImportError,
    parse_homeworks_xml,
)

pytestmark = [
    pytest.mark.asyncio,
]


# === Test XML Fixtures ===

SIMPLE_XML = """\
<?xml version="1.0"?>
<HWProject>
  <ProjectName>Test House</ProjectName>
  <FileType>Maximum</FileType>
  <Area>
    <Name>MAIN</Name>
    <Id>1</Id>
    <Room>
      <Name>KITCHEN</Name>
      <Id>1</Id>
      <Outputs>
        <Output>
          <Name>OVERHEAD</Name>
          <Address>1:1:0:2:1</Address>
          <Type>DIMMER</Type>
        </Output>
        <Output>
          <Name>FIREPLACE</Name>
          <Address>1:5:3:1</Address>
          <Type>MAINTAINED OUTPUT</Type>
        </Output>
      </Outputs>
      <Inputs>
        <ControlStation>
          <Name>CS1</Name>
          <Id>1</Id>
          <Devices>
            <Device>
              <Id>1</Id>
              <Address>1:5:1</Address>
              <Model>ST-5BRL-NI</Model>
              <GangPosition>1</GangPosition>
              <Type>KEYPAD</Type>
              <WebEnabled>True</WebEnabled>
              <WebKeypadName>Kitchen</WebKeypadName>
              <Buttons>
                <Button>
                  <Number>1</Number>
                  <Name>ON</Name>
                  <Type>Default Single Action</Type>
                  <Actions><Press>True</Press></Actions>
                  <DisplayProperties><Type>BUTTON WITH LED</Type></DisplayProperties>
                </Button>
                <Button>
                  <Number>2</Number>
                  <Name>OFF</Name>
                  <Type>Default Single Action</Type>
                  <Actions><Press>True</Press></Actions>
                  <DisplayProperties><Type>BUTTON WITH LED</Type></DisplayProperties>
                </Button>
                <Button>
                  <Number>3</Number>
                  <Name>Button 3</Name>
                  <Type>Not Programmed</Type>
                  <Actions><Press>True</Press></Actions>
                  <DisplayProperties/>
                </Button>
              </Buttons>
            </Device>
          </Devices>
        </ControlStation>
      </Inputs>
    </Room>
    <Room>
      <Name>LIVING ROOM</Name>
      <Id>2</Id>
      <Outputs>
        <Output>
          <Name>SHADE</Name>
          <Address>1:6:1:5</Address>
          <Type>QED SHADE</Type>
        </Output>
      </Outputs>
      <Inputs/>
    </Room>
  </Area>
  <Area>
    <Name>LOWER</Name>
    <Id>2</Id>
    <Room>
      <Name>MECH</Name>
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
              </Buttons>
            </Device>
          </Devices>
        </ControlStation>
      </Inputs>
    </Room>
  </Area>
</HWProject>
"""


def _make_handler(options: dict | None = None) -> MagicMock:
    """Create a mock SchemaCommonFlowHandler with options and flow_state."""
    handler = MagicMock()
    handler.options = options or {
        CONF_DIMMERS: [],
        CONF_CCO_DEVICES: [],
        CONF_KEYPADS: [],
        CONF_RPM_COVERS: [],
        CONF_QED_COVERS: [],
        CONF_CCI_DEVICES: [],
    }
    handler.flow_state = {}
    handler.parent_handler = MagicMock()
    handler.parent_handler.hass = MagicMock()
    return handler


# =============================================================================
# Duplicate Detection Tests (F8 refactored generics)
# =============================================================================


class TestDuplicateDetection:
    """Test the generic and type-specific duplicate detection functions."""

    def test_find_existing_by_address_found(self) -> None:
        """Test finding existing device by address."""
        handler = _make_handler({
            CONF_DIMMERS: [
                {CONF_ADDR: "[01:01:00:02:01]", CONF_NAME: "Light"},
            ],
        })
        result = _find_existing_by_address(handler, CONF_DIMMERS, "1:1:0:2:1")
        assert result == 0

    def test_find_existing_by_address_not_found(self) -> None:
        """Test not finding device by address."""
        handler = _make_handler({CONF_DIMMERS: []})
        result = _find_existing_by_address(handler, CONF_DIMMERS, "1:1:0:2:1")
        assert result is None

    def test_is_duplicate_dimmer(self) -> None:
        """Test dimmer duplicate detection delegates to generic."""
        handler = _make_handler({
            CONF_DIMMERS: [{CONF_ADDR: "[01:01:00:02:01]", CONF_NAME: "X"}],
        })
        assert _is_duplicate_dimmer(handler, "[01:01:00:02:01]") is True
        assert _is_duplicate_dimmer(handler, "[01:01:00:02:02]") is False

    def test_is_duplicate_rpm_cover(self) -> None:
        """Test RPM cover duplicate detection."""
        handler = _make_handler({
            CONF_RPM_COVERS: [{CONF_ADDR: "[01:01:01:02:01]", CONF_NAME: "C"}],
        })
        assert _is_duplicate_rpm_cover(handler, "[01:01:01:02:01]") is True
        assert _is_duplicate_rpm_cover(handler, "[01:01:01:02:02]") is False

    def test_is_duplicate_qed_cover(self) -> None:
        """Test QED cover duplicate detection."""
        handler = _make_handler({
            CONF_QED_COVERS: [{CONF_ADDR: "[01:06:01:05]", CONF_NAME: "S"}],
        })
        assert _is_duplicate_qed_cover(handler, "[01:06:01:05]") is True

    def test_is_duplicate_keypad(self) -> None:
        """Test keypad duplicate detection."""
        handler = _make_handler({
            CONF_KEYPADS: [{CONF_ADDR: "[01:05:01]", CONF_NAME: "K", CONF_BUTTONS: []}],
        })
        assert _is_duplicate_keypad(handler, "[01:05:01]") is True
        assert _is_duplicate_keypad(handler, "[01:05:02]") is False

    def test_is_duplicate_cci_compound_key(self) -> None:
        """Test CCI duplicate detection uses address + input_number."""
        handler = _make_handler({
            CONF_CCI_DEVICES: [
                {CONF_ADDR: "[01]", CONF_INPUT_NUMBER: 1, CONF_NAME: "I"},
            ],
        })
        assert _is_duplicate_cci(handler, "[01]", 1) is True
        assert _is_duplicate_cci(handler, "[01]", 2) is False


# =============================================================================
# XML Parse Step Tests
# =============================================================================


class TestAsyncParseXml:
    """Test the XML upload/parse step."""

    async def test_valid_xml_parsed(self) -> None:
        """Test that valid XML is parsed and stored in flow_state."""
        handler = _make_handler()
        await async_parse_xml(handler, {"xml_file": SIMPLE_XML})
        parsed = handler.flow_state["xml_parsed"]
        assert parsed.project_name == "Test House"
        assert len(parsed.areas) == 2

    async def test_invalid_xml_raises_error(self) -> None:
        """Test that invalid XML raises SchemaFlowError."""
        from homeassistant.helpers.schema_config_entry_flow import SchemaFlowError
        handler = _make_handler()
        with pytest.raises(SchemaFlowError):
            await async_parse_xml(handler, {"xml_file": "<not valid"})

    async def test_non_maximum_raises_error(self) -> None:
        """Test that non-Maximum export raises error."""
        from homeassistant.helpers.schema_config_entry_flow import SchemaFlowError
        handler = _make_handler()
        xml = '<?xml version="1.0"?><HWProject><FileType>Minimum</FileType></HWProject>'
        with pytest.raises(SchemaFlowError):
            await async_parse_xml(handler, {"xml_file": xml})


# =============================================================================
# Device Selection + Classification Tests
# =============================================================================


class TestValidateDeviceSelection:
    """Test the device selection validation step."""

    async def test_cco_devices_collected(self) -> None:
        """Test that selected CCO devices are collected for classification."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "DIMMER", "address": "1:1:0:2:1", "name": "L", "room_key": "r"},
            {"type": "MAINTAINED OUTPUT", "address": "1:5:3:1", "name": "F", "room_key": "r"},
        ]
        await validate_xml_device_selection(handler, {"devices": ["0", "1"]})
        assert len(handler.flow_state["xml_cco_to_classify"]) == 1
        assert handler.flow_state["xml_cco_to_classify"][0]["name"] == "F"

    async def test_cci_devices_collected(self) -> None:
        """Test that selected CCI devices are collected for classification."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "CCI", "address": "1", "name": "Button 1", "room_key": "r", "input_number": 1},
        ]
        await validate_xml_device_selection(handler, {"devices": ["0"]})
        assert len(handler.flow_state["xml_cci_to_classify"]) == 1

    async def test_no_cco_no_cci(self) -> None:
        """Test that empty lists are set when no CCO/CCI selected."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "DIMMER", "address": "1:1:0:2:1", "name": "L", "room_key": "r"},
        ]
        await validate_xml_device_selection(handler, {"devices": ["0"]})
        assert handler.flow_state["xml_cco_to_classify"] == []
        assert handler.flow_state["xml_cci_to_classify"] == []


class TestCCOClassifySchema:
    """Test CCO classification step."""

    async def test_returns_none_when_empty(self) -> None:
        """Test schema returns None when no CCOs to classify (auto-skip)."""
        handler = _make_handler()
        handler.flow_state["xml_cco_to_classify"] = []
        result = await get_xml_cco_classify_schema(handler)
        assert result is None

    async def test_returns_schema_with_ccos(self) -> None:
        """Test schema is built when CCOs exist."""
        handler = _make_handler()
        handler.flow_state["xml_cco_to_classify"] = [
            {"idx": 0, "address": "1:5:3:1", "name": "Fire"},
        ]
        result = await get_xml_cco_classify_schema(handler)
        assert result is not None

    async def test_classify_stores_entity_type(self) -> None:
        """Test that CCO classification stores entity type."""
        handler = _make_handler()
        handler.flow_state["xml_cco_to_classify"] = [
            {"idx": 0, "address": "1:5:3:1", "name": "Fire"},
        ]
        await validate_xml_cco_classify(handler, {"cco_0": CCO_TYPE_LIGHT})
        assert handler.flow_state["xml_cco_to_classify"][0]["entity_type"] == CCO_TYPE_LIGHT


class TestCCIClassifySchema:
    """Test CCI classification step."""

    async def test_returns_none_when_empty(self) -> None:
        """Test schema returns None when no CCIs to classify (auto-skip)."""
        handler = _make_handler()
        handler.flow_state["xml_cci_to_classify"] = []
        result = await get_xml_cci_classify_schema(handler)
        assert result is None

    async def test_returns_schema_with_ccis(self) -> None:
        """Test schema is built when CCIs exist."""
        handler = _make_handler()
        handler.flow_state["xml_cci_to_classify"] = [
            {"idx": 0, "address": "1", "name": "Button 1", "input_number": 1},
        ]
        result = await get_xml_cci_classify_schema(handler)
        assert result is not None

    async def test_classify_stores_name_and_class(self) -> None:
        """Test that CCI classification stores name and device_class."""
        handler = _make_handler()
        handler.flow_state["xml_cci_to_classify"] = [
            {"idx": 0, "address": "1", "name": "Button 1", "input_number": 1},
        ]
        await validate_xml_cci_classify(
            handler, {"cci_name_0": "Front Door", "cci_class_0": "door"}
        )
        cci = handler.flow_state["xml_cci_to_classify"][0]
        assert cci["name"] == "Front Door"
        assert cci["device_class"] == "door"


# =============================================================================
# Confirm + Commit Tests
# =============================================================================


class TestConfirmDescriptionPlaceholders:
    """Test the confirm step description placeholders."""

    async def test_counts_computed(self) -> None:
        """Test that device counts are computed correctly."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "DIMMER"},
            {"type": "DIMMER"},
            {"type": "QED SHADE"},
            {"type": "MAINTAINED OUTPUT"},
            {"type": "KEYPAD", "buttons": [{"n": 1}, {"n": 2}]},
            {"type": "CCI"},
        ]
        handler.flow_state["xml_selected_devices"] = ["0", "1", "2", "3", "4", "5"]
        placeholders = await get_xml_confirm_description_placeholders(handler)
        assert placeholders["lights"] == "2"
        assert placeholders["qed_shades"] == "1"
        assert placeholders["cco_devices"] == "1"
        assert placeholders["keypads"] == "1"
        assert placeholders["total_buttons"] == "2"
        assert placeholders["cci_inputs"] == "1"


class TestValidateConfirmImport:
    """Test the commit logic."""

    async def test_dimmer_committed(self) -> None:
        """Test that selected dimmers are committed to config."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "DIMMER", "address": "1:1:0:2:1", "name": "Light", "room_key": "room_1_1"},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"room_1_1": "__create__Kitchen"}
        handler.flow_state["xml_cco_to_classify"] = []

        await validate_xml_confirm_import(handler, {})
        dimmers = handler.options[CONF_DIMMERS]
        assert len(dimmers) == 1
        assert dimmers[0][CONF_ADDR] == "[01:01:00:02:01]"
        assert dimmers[0][CONF_NAME] == "Light"
        assert dimmers[0][CONF_AREA] == "Kitchen"

    async def test_cco_committed_with_type(self) -> None:
        """Test that CCO devices are committed with classified entity type."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "MAINTAINED OUTPUT", "address": "1:5:3:1", "name": "Fire", "room_key": "room_1_1"},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"room_1_1": "__create__Den"}
        handler.flow_state["xml_cco_to_classify"] = [
            {"idx": 0, "entity_type": CCO_TYPE_SWITCH, "address": "1:5:3:1", "name": "Fire"},
        ]

        await validate_xml_confirm_import(handler, {})
        ccos = handler.options[CONF_CCO_DEVICES]
        assert len(ccos) == 1
        assert ccos[0][CONF_ADDR] == "[01:05:03]"
        assert ccos[0][CONF_BUTTON_NUMBER] == 1
        assert ccos[0][CONF_ENTITY_TYPE] == CCO_TYPE_SWITCH

    async def test_keypad_committed_with_buttons(self) -> None:
        """Test that keypads are committed with their buttons."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {
                "type": "KEYPAD",
                "address": "1:5:1",
                "name": "Kitchen",
                "room_key": "room_1_1",
                "buttons": [
                    {"number": 1, "name": "ON", "has_led": True, "release_delay": 0.0},
                    {"number": 2, "name": "OFF", "has_led": True, "release_delay": 0.0},
                ],
            },
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"room_1_1": "__create__Kitchen"}
        handler.flow_state["xml_cco_to_classify"] = []

        await validate_xml_confirm_import(handler, {})
        keypads = handler.options[CONF_KEYPADS]
        assert len(keypads) == 1
        assert keypads[0][CONF_ADDR] == "[01:05:01]"
        assert len(keypads[0][CONF_BUTTONS]) == 2
        assert keypads[0][CONF_BUTTONS][0][CONF_NUMBER] == 1
        assert keypads[0][CONF_BUTTONS][0][CONF_LED] is True

    async def test_qed_shade_committed(self) -> None:
        """Test that QED shades are committed."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "QED SHADE", "address": "1:6:1:5", "name": "Shade", "room_key": "room_1_2"},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"room_1_2": "__create__Living Room"}
        handler.flow_state["xml_cco_to_classify"] = []

        await validate_xml_confirm_import(handler, {})
        qeds = handler.options[CONF_QED_COVERS]
        assert len(qeds) == 1
        assert qeds[0][CONF_ADDR] == "[01:06:01:05]"

    async def test_cci_committed_with_device_class(self) -> None:
        """Test CCI devices committed with classification data from classify step.

        The real flow stores classification data (name, device_class) on
        copies in xml_cci_to_classify, NOT on the originals in xml_device_list.
        This test verifies the cci_data_map bridge works correctly.
        """
        handler = _make_handler()
        # Original in device_list has raw XML name, NO device_class
        handler.flow_state["xml_device_list"] = [
            {"type": "CCI", "address": "1", "name": "Button 1", "room_key": "room_2_10",
             "input_number": 1},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"room_2_10": "__create__Mech"}
        handler.flow_state["xml_cco_to_classify"] = []
        # Classification step wrote to the COPY in xml_cci_to_classify
        handler.flow_state["xml_cci_to_classify"] = [
            {"idx": 0, "address": "1", "name": "Front Door", "input_number": 1,
             "device_class": "door"},
        ]

        await validate_xml_confirm_import(handler, {})
        ccis = handler.options[CONF_CCI_DEVICES]
        assert len(ccis) == 1
        assert ccis[0][CONF_NAME] == "Front Door"
        assert ccis[0][CONF_DEVICE_CLASS] == "door"

    async def test_cci_committed_without_classification(self) -> None:
        """Test CCI devices committed when no classification step ran."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "CCI", "address": "1", "name": "Button 1", "room_key": "room_2_10",
             "input_number": 1},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"room_2_10": "__create__Mech"}
        handler.flow_state["xml_cco_to_classify"] = []
        handler.flow_state["xml_cci_to_classify"] = []

        await validate_xml_confirm_import(handler, {})
        ccis = handler.options[CONF_CCI_DEVICES]
        assert len(ccis) == 1
        assert ccis[0][CONF_NAME] == "Button 1"
        assert CONF_DEVICE_CLASS not in ccis[0]

    async def test_duplicate_dimmer_skipped(self) -> None:
        """Test that duplicate dimmers are not re-imported."""
        handler = _make_handler({
            CONF_DIMMERS: [{CONF_ADDR: "[01:01:00:02:01]", CONF_NAME: "Existing"}],
            CONF_CCO_DEVICES: [],
            CONF_KEYPADS: [],
            CONF_RPM_COVERS: [],
            CONF_QED_COVERS: [],
            CONF_CCI_DEVICES: [],
        })
        handler.flow_state["xml_device_list"] = [
            {"type": "DIMMER", "address": "1:1:0:2:1", "name": "Same", "room_key": "r"},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"r": "__create__X"}
        handler.flow_state["xml_cco_to_classify"] = []

        await validate_xml_confirm_import(handler, {})
        assert len(handler.options[CONF_DIMMERS]) == 1
        assert handler.options[CONF_DIMMERS][0][CONF_NAME] == "Existing"

    async def test_area_create_stores_name(self) -> None:
        """Test that __create__ sentinel stores the human-readable name."""
        handler = _make_handler()
        handler.flow_state["xml_device_list"] = [
            {"type": "DIMMER", "address": "1:1:0:2:1", "name": "L", "room_key": "r"},
        ]
        handler.flow_state["xml_selected_devices"] = ["0"]
        handler.flow_state["xml_area_mapping"] = {"r": "__create__Master Suite"}
        handler.flow_state["xml_cco_to_classify"] = []

        await validate_xml_confirm_import(handler, {})
        assert handler.options[CONF_DIMMERS][0][CONF_AREA] == "Master Suite"

    async def test_existing_area_stores_name_not_id(self) -> None:
        """Test that existing area selection stores the area NAME, not ID (F10)."""
        from homeassistant.helpers import area_registry as ar

        handler = _make_handler()
        # Mock area registry to return a real area entry
        mock_area = MagicMock()
        mock_area.id = "living_room"
        mock_area.name = "Living Room"
        mock_reg = MagicMock()
        mock_reg.async_get_area.return_value = mock_area

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ar, "async_get", lambda hass: mock_reg)

            handler.flow_state["xml_device_list"] = [
                {"type": "DIMMER", "address": "1:1:0:2:1", "name": "L", "room_key": "r"},
            ]
            handler.flow_state["xml_selected_devices"] = ["0"]
            handler.flow_state["xml_area_mapping"] = {"r": "living_room"}
            handler.flow_state["xml_cco_to_classify"] = []

            await validate_xml_confirm_import(handler, {})
            # Must store NAME not ID
            assert handler.options[CONF_DIMMERS][0][CONF_AREA] == "Living Room"

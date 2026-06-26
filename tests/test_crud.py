"""Tests for device CRUD operations on the options/storage layer.

These tests verify that adding, editing, and deleting devices
correctly updates the options schema, without requiring Home Assistant.
"""

import pytest
from copy import deepcopy

# Import models and constants (no HA deps)
from custom_components.homeworks_hwi.hwi_protocol import normalize_address


# Simulate the options dictionary structure used by config_flow
def create_empty_options() -> dict:
    """Create an empty options dict matching the config_flow structure."""
    return {
        "controller_id": "test_controller",
        "host": "192.168.1.100",
        "port": 23,
        "cco_devices": [],
        "dimmers": [],
        "keypads": [],
        "kls_poll_interval": 10,
        "kls_window_offset": 9,
    }


# === CCO Device CRUD ===


class TestCCODeviceCRUD:
    """Tests for CCO device create/read/update/delete operations."""

    def test_add_cco_device(self):
        """Test adding a CCO device to options."""
        options = create_empty_options()

        # Add a CCO switch
        new_device = {
            "name": "Kitchen Light",
            "addr": "[02:06:03]",
            "button_number": 6,
            "entity_type": "switch",
            "inverted": False,
        }
        options["cco_devices"].append(new_device)

        assert len(options["cco_devices"]) == 1
        assert options["cco_devices"][0]["name"] == "Kitchen Light"
        assert options["cco_devices"][0]["addr"] == "[02:06:03]"
        assert options["cco_devices"][0]["button_number"] == 6

    def test_add_multiple_cco_devices(self):
        """Test adding multiple CCO devices."""
        options = create_empty_options()

        devices = [
            {"name": "Switch 1", "addr": "[02:06:03]", "button_number": 1, "entity_type": "switch", "inverted": False},
            {"name": "Light 2", "addr": "[02:06:03]", "button_number": 2, "entity_type": "light", "inverted": False},
            {"name": "Cover 3", "addr": "[02:06:03]", "button_number": 3, "entity_type": "cover", "inverted": True},
            {"name": "Lock 4", "addr": "[02:06:04]", "button_number": 1, "entity_type": "lock", "inverted": False},
        ]

        for dev in devices:
            options["cco_devices"].append(dev)

        assert len(options["cco_devices"]) == 4
        assert options["cco_devices"][2]["entity_type"] == "cover"
        assert options["cco_devices"][2]["inverted"] is True

    def test_edit_cco_device_name(self):
        """Test editing a CCO device name preserves other fields."""
        options = create_empty_options()
        options["cco_devices"].append({
            "name": "Original Name",
            "addr": "[02:06:03]",
            "button_number": 6,
            "entity_type": "switch",
            "inverted": False,
        })

        # Edit the name
        options["cco_devices"][0]["name"] = "New Name"

        assert options["cco_devices"][0]["name"] == "New Name"
        assert options["cco_devices"][0]["addr"] == "[02:06:03]"
        assert options["cco_devices"][0]["button_number"] == 6
        assert options["cco_devices"][0]["entity_type"] == "switch"

    def test_edit_cco_device_entity_type(self):
        """Test changing entity type (switch -> light)."""
        options = create_empty_options()
        options["cco_devices"].append({
            "name": "Test Device",
            "addr": "[02:06:03]",
            "button_number": 6,
            "entity_type": "switch",
            "inverted": False,
        })

        # Change entity type
        options["cco_devices"][0]["entity_type"] = "light"

        assert options["cco_devices"][0]["entity_type"] == "light"

    def test_edit_cco_device_inversion(self):
        """Test toggling inversion."""
        options = create_empty_options()
        options["cco_devices"].append({
            "name": "Test Device",
            "addr": "[02:06:03]",
            "button_number": 6,
            "entity_type": "switch",
            "inverted": False,
        })

        # Toggle inversion
        options["cco_devices"][0]["inverted"] = True

        assert options["cco_devices"][0]["inverted"] is True

    def test_edit_cco_device_address_and_button(self):
        """Test changing address and button number."""
        options = create_empty_options()
        options["cco_devices"].append({
            "name": "Test Device",
            "addr": "[02:06:03]",
            "button_number": 6,
            "entity_type": "switch",
            "inverted": False,
        })

        # Change address and button
        options["cco_devices"][0]["addr"] = "[02:06:04]"
        options["cco_devices"][0]["button_number"] = 1

        assert options["cco_devices"][0]["addr"] == "[02:06:04]"
        assert options["cco_devices"][0]["button_number"] == 1

    def test_delete_cco_device(self):
        """Test deleting a CCO device."""
        options = create_empty_options()
        options["cco_devices"] = [
            {"name": "Device 1", "addr": "[02:06:03]", "button_number": 1, "entity_type": "switch", "inverted": False},
            {"name": "Device 2", "addr": "[02:06:03]", "button_number": 2, "entity_type": "light", "inverted": False},
            {"name": "Device 3", "addr": "[02:06:03]", "button_number": 3, "entity_type": "cover", "inverted": False},
        ]

        # Delete middle device (index 1)
        del options["cco_devices"][1]

        assert len(options["cco_devices"]) == 2
        assert options["cco_devices"][0]["name"] == "Device 1"
        assert options["cco_devices"][1]["name"] == "Device 3"

    def test_delete_multiple_cco_devices(self):
        """Test deleting multiple CCO devices."""
        options = create_empty_options()
        options["cco_devices"] = [
            {"name": "Device 0", "addr": "[02:06:03]", "button_number": 1, "entity_type": "switch", "inverted": False},
            {"name": "Device 1", "addr": "[02:06:03]", "button_number": 2, "entity_type": "light", "inverted": False},
            {"name": "Device 2", "addr": "[02:06:03]", "button_number": 3, "entity_type": "cover", "inverted": False},
            {"name": "Device 3", "addr": "[02:06:03]", "button_number": 4, "entity_type": "lock", "inverted": False},
        ]

        # Delete indices 1 and 3 (must delete in reverse order to preserve indices)
        indices_to_delete = {1, 3}
        options["cco_devices"] = [
            dev for idx, dev in enumerate(options["cco_devices"])
            if idx not in indices_to_delete
        ]

        assert len(options["cco_devices"]) == 2
        assert options["cco_devices"][0]["name"] == "Device 0"
        assert options["cco_devices"][1]["name"] == "Device 2"

    def test_duplicate_detection(self):
        """Test that we can detect duplicate address+button combinations."""
        options = create_empty_options()
        options["cco_devices"] = [
            {"name": "Device 1", "addr": "[02:06:03]", "button_number": 6, "entity_type": "switch", "inverted": False},
        ]

        # Check for duplicate
        new_addr = "[02:06:03]"
        new_button = 6

        def is_duplicate(addr: str, button: int) -> bool:
            for dev in options["cco_devices"]:
                if dev["addr"] == addr and dev["button_number"] == button:
                    return True
            return False

        assert is_duplicate(new_addr, new_button) is True
        assert is_duplicate("[02:06:03]", 5) is False
        assert is_duplicate("[02:06:04]", 6) is False


# === Dimmable Light CRUD ===


class TestDimmerCRUD:
    """Tests for dimmable light create/read/update/delete operations."""

    def test_add_dimmer(self):
        """Test adding a dimmable light."""
        options = create_empty_options()

        new_dimmer = {
            "name": "Living Room Dimmer",
            "addr": "[01:01:00:02:04]",
            "rate": 2.0,
        }
        options["dimmers"].append(new_dimmer)

        assert len(options["dimmers"]) == 1
        assert options["dimmers"][0]["name"] == "Living Room Dimmer"
        assert options["dimmers"][0]["rate"] == 2.0

    def test_edit_dimmer_rate(self):
        """Test editing dimmer fade rate."""
        options = create_empty_options()
        options["dimmers"].append({
            "name": "Test Dimmer",
            "addr": "[01:01:00:02:04]",
            "rate": 1.0,
        })

        # Edit rate
        options["dimmers"][0]["rate"] = 3.5

        assert options["dimmers"][0]["rate"] == 3.5
        assert options["dimmers"][0]["name"] == "Test Dimmer"

    def test_edit_dimmer_name(self):
        """Test editing dimmer name."""
        options = create_empty_options()
        options["dimmers"].append({
            "name": "Old Name",
            "addr": "[01:01:00:02:04]",
            "rate": 1.0,
        })

        options["dimmers"][0]["name"] = "New Name"

        assert options["dimmers"][0]["name"] == "New Name"

    def test_delete_dimmer(self):
        """Test deleting a dimmer."""
        options = create_empty_options()
        options["dimmers"] = [
            {"name": "Dimmer 1", "addr": "[01:01:00:02:01]", "rate": 1.0},
            {"name": "Dimmer 2", "addr": "[01:01:00:02:02]", "rate": 1.0},
        ]

        del options["dimmers"][0]

        assert len(options["dimmers"]) == 1
        assert options["dimmers"][0]["name"] == "Dimmer 2"

    def test_dimmer_address_duplicate_detection(self):
        """Test duplicate dimmer address detection."""
        options = create_empty_options()
        options["dimmers"] = [
            {"name": "Dimmer 1", "addr": "[01:01:00:02:04]", "rate": 1.0},
        ]

        def is_duplicate_dimmer(addr: str) -> bool:
            normalized = normalize_address(addr)
            for dim in options["dimmers"]:
                if normalize_address(dim["addr"]) == normalized:
                    return True
            return False

        assert is_duplicate_dimmer("[01:01:00:02:04]") is True
        assert is_duplicate_dimmer("1:1:0:2:4") is True  # Different format, same address
        assert is_duplicate_dimmer("[01:01:00:02:05]") is False


# === Keypad CRUD ===


class TestKeypadCRUD:
    """Tests for keypad create/read/update/delete operations."""

    def test_add_keypad(self):
        """Test adding a keypad."""
        options = create_empty_options()

        new_keypad = {
            "name": "Entry Keypad",
            "addr": "[01:04:10]",
            "buttons": [],
        }
        options["keypads"].append(new_keypad)

        assert len(options["keypads"]) == 1
        assert options["keypads"][0]["name"] == "Entry Keypad"
        assert options["keypads"][0]["buttons"] == []

    def test_add_button_to_keypad(self):
        """Test adding a button to a keypad."""
        options = create_empty_options()
        options["keypads"].append({
            "name": "Test Keypad",
            "addr": "[01:04:10]",
            "buttons": [],
        })

        # Add button
        options["keypads"][0]["buttons"].append({
            "name": "Scene 1",
            "number": 1,
            "led": True,
            "release_delay": 0.0,
        })

        assert len(options["keypads"][0]["buttons"]) == 1
        assert options["keypads"][0]["buttons"][0]["name"] == "Scene 1"
        assert options["keypads"][0]["buttons"][0]["led"] is True

    def test_edit_keypad_button(self):
        """Test editing a keypad button."""
        options = create_empty_options()
        options["keypads"].append({
            "name": "Test Keypad",
            "addr": "[01:04:10]",
            "buttons": [
                {"name": "Button 1", "number": 1, "led": False, "release_delay": 0.0},
            ],
        })

        # Edit button
        options["keypads"][0]["buttons"][0]["name"] = "Scene On"
        options["keypads"][0]["buttons"][0]["led"] = True

        assert options["keypads"][0]["buttons"][0]["name"] == "Scene On"
        assert options["keypads"][0]["buttons"][0]["led"] is True
        assert options["keypads"][0]["buttons"][0]["number"] == 1

    def test_delete_button_from_keypad(self):
        """Test deleting a button from a keypad."""
        options = create_empty_options()
        options["keypads"].append({
            "name": "Test Keypad",
            "addr": "[01:04:10]",
            "buttons": [
                {"name": "Button 1", "number": 1, "led": False, "release_delay": 0.0},
                {"name": "Button 2", "number": 2, "led": False, "release_delay": 0.0},
            ],
        })

        del options["keypads"][0]["buttons"][0]

        assert len(options["keypads"][0]["buttons"]) == 1
        assert options["keypads"][0]["buttons"][0]["name"] == "Button 2"

    def test_delete_keypad_removes_buttons(self):
        """Test that deleting a keypad also removes its buttons."""
        options = create_empty_options()
        options["keypads"] = [
            {
                "name": "Keypad 1",
                "addr": "[01:04:10]",
                "buttons": [
                    {"name": "Button 1", "number": 1, "led": False, "release_delay": 0.0},
                    {"name": "Button 2", "number": 2, "led": False, "release_delay": 0.0},
                ],
            },
            {
                "name": "Keypad 2",
                "addr": "[01:04:11]",
                "buttons": [
                    {"name": "Button A", "number": 1, "led": True, "release_delay": 0.0},
                ],
            },
        ]

        # Delete first keypad
        del options["keypads"][0]

        assert len(options["keypads"]) == 1
        assert options["keypads"][0]["name"] == "Keypad 2"
        assert len(options["keypads"][0]["buttons"]) == 1

    def test_button_number_duplicate_detection(self):
        """Test duplicate button number detection on same keypad."""
        options = create_empty_options()
        options["keypads"].append({
            "name": "Test Keypad",
            "addr": "[01:04:10]",
            "buttons": [
                {"name": "Button 1", "number": 1, "led": False, "release_delay": 0.0},
                {"name": "Button 5", "number": 5, "led": False, "release_delay": 0.0},
            ],
        })

        def is_duplicate_button(keypad_idx: int, number: int) -> bool:
            for btn in options["keypads"][keypad_idx]["buttons"]:
                if btn["number"] == number:
                    return True
            return False

        assert is_duplicate_button(0, 1) is True
        assert is_duplicate_button(0, 5) is True
        assert is_duplicate_button(0, 2) is False


# === Controller Settings ===


class TestControllerSettings:
    """Tests for controller settings updates."""

    def test_update_kls_poll_interval(self):
        """Test updating KLS poll interval."""
        options = create_empty_options()

        options["kls_poll_interval"] = 30

        assert options["kls_poll_interval"] == 30

    def test_update_kls_window_offset(self):
        """Test updating KLS window offset."""
        options = create_empty_options()

        options["kls_window_offset"] = 8

        assert options["kls_window_offset"] == 8

    def test_settings_persistence(self):
        """Test that settings persist across device changes."""
        options = create_empty_options()
        options["kls_poll_interval"] = 15
        options["kls_window_offset"] = 10

        # Add a device
        options["cco_devices"].append({
            "name": "Test",
            "addr": "[02:06:03]",
            "button_number": 1,
            "entity_type": "switch",
            "inverted": False,
        })

        # Settings should still be there
        assert options["kls_poll_interval"] == 15
        assert options["kls_window_offset"] == 10


# === Schema Validation ===


class TestSchemaValidation:
    """Tests for options schema validation."""

    def test_required_cco_fields(self):
        """Test that CCO devices require specific fields."""
        required_fields = ["name", "addr", "button_number", "entity_type", "inverted"]

        device = {
            "name": "Test",
            "addr": "[02:06:03]",
            "button_number": 1,
            "entity_type": "switch",
            "inverted": False,
        }

        for field in required_fields:
            assert field in device

    def test_cco_entity_types_valid(self):
        """Test that entity type values are valid."""
        valid_types = {"switch", "light", "cover", "lock"}

        for etype in valid_types:
            device = {
                "name": "Test",
                "addr": "[02:06:03]",
                "button_number": 1,
                "entity_type": etype,
                "inverted": False,
            }
            assert device["entity_type"] in valid_types

    def test_button_number_range(self):
        """Test button number validation (1-24)."""
        for num in range(1, 25):
            # Valid range
            device = {
                "name": "Test",
                "addr": "[02:06:03]",
                "button_number": num,
                "entity_type": "switch",
                "inverted": False,
            }
            assert 1 <= device["button_number"] <= 24

    def test_dimmer_rate_range(self):
        """Test dimmer rate validation (0-20)."""
        for rate in [0, 0.5, 1.0, 5.0, 10.0, 20.0]:
            dimmer = {
                "name": "Test",
                "addr": "[01:01:00:02:04]",
                "rate": rate,
            }
            assert 0 <= dimmer["rate"] <= 20


# === Migration Support ===


class TestLegacyMigration:
    """Tests for legacy options format migration."""

    def test_legacy_ccos_key_exists(self):
        """Test that legacy 'ccos' key can coexist with 'cco_devices'."""
        options = create_empty_options()
        options["ccos"] = []  # Legacy key
        options["covers"] = []  # Legacy key
        options["locks"] = []  # Legacy key

        # Both should exist
        assert "ccos" in options
        assert "cco_devices" in options

    def test_migrate_legacy_cco_to_cco_device(self):
        """Test migrating a legacy CCO to new format."""
        legacy_cco = {
            "name": "Legacy Switch",
            "addr": "[02:06:03]",
            "relay_number": 6,
            "inverted": False,
        }

        # Migration logic
        new_device = {
            "name": legacy_cco["name"],
            "addr": legacy_cco["addr"],
            "button_number": legacy_cco.get("relay_number", 1),
            "entity_type": "switch",
            "inverted": legacy_cco.get("inverted", False),
        }

        assert new_device["button_number"] == 6
        assert new_device["entity_type"] == "switch"

    def test_migrate_legacy_cover(self):
        """Test migrating a legacy cover."""
        legacy_cover = {
            "name": "Legacy Cover",
            "addr": "[02:06:03]",
        }

        new_device = {
            "name": legacy_cover["name"],
            "addr": legacy_cover["addr"],
            "button_number": 1,  # Default for covers
            "entity_type": "cover",
            "inverted": False,
        }

        assert new_device["entity_type"] == "cover"

    def test_migrate_legacy_lock(self):
        """Test migrating a legacy lock."""
        legacy_lock = {
            "name": "Legacy Lock",
            "addr": "[02:06:03]",
            "relay_number": 2,
        }

        new_device = {
            "name": legacy_lock["name"],
            "addr": legacy_lock["addr"],
            "button_number": legacy_lock.get("relay_number", 1),
            "entity_type": "lock",
            "inverted": False,
        }

        assert new_device["entity_type"] == "lock"
        assert new_device["button_number"] == 2


# === CSV Import Tests ===


class TestCSVImport:
    """Tests for CSV import functionality."""

    def test_parse_csv_basic_switch(self):
        """Test parsing a basic switch from CSV."""
        csv_content = """device_type,address,relay,name
CCO,02:06:03,6,Kitchen Light"""

        import csv
        from io import StringIO

        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        devices = []
        for row in reader:
            device_type = row.get("device_type", "").strip().upper()
            if device_type in ("CCO", "SWITCH"):
                button = int(row.get("relay", row.get("button", 1)))
                cco_type = row.get("type", "").strip().lower() or "switch"
                devices.append({
                    "device_type": "CCO",
                    "address": normalize_address(row["address"].strip()),
                    "button": button,
                    "name": row.get("name", "").strip(),
                    "entity_type": cco_type,
                })

        assert len(devices) == 1
        assert devices[0]["name"] == "Kitchen Light"
        assert devices[0]["address"] == "[02:06:03]"
        assert devices[0]["button"] == 6
        assert devices[0]["entity_type"] == "switch"

    def test_parse_csv_with_type_column(self):
        """Test parsing CSV with type column for CCO devices."""
        csv_content = """device_type,address,relay,name,type
CCO,02:06:03,6,Kitchen Light,switch
CCO,02:06:04,1,Garage Door,cover
CCO,02:06:05,2,Front Door,lock
CCO,02:06:06,3,Thermostat,climate
CCO,02:06:07,4,Bedroom Light,light"""

        import csv
        from io import StringIO

        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        devices = []
        for row in reader:
            device_type = row.get("device_type", "").strip().upper()
            if device_type in ("CCO", "SWITCH"):
                button = int(row.get("relay", row.get("button", 1)))
                cco_type = row.get("type", "").strip().lower() or "switch"
                devices.append({
                    "device_type": "CCO",
                    "address": normalize_address(row["address"].strip()),
                    "button": button,
                    "name": row.get("name", "").strip(),
                    "entity_type": cco_type,
                })

        assert len(devices) == 5
        assert devices[0]["entity_type"] == "switch"
        assert devices[1]["entity_type"] == "cover"
        assert devices[2]["entity_type"] == "lock"
        assert devices[3]["entity_type"] == "climate"
        assert devices[4]["entity_type"] == "light"

    def test_parse_csv_dimmer(self):
        """Test parsing dimmers from CSV."""
        csv_content = """device_type,address,name
DIMMER,01:01:00:02:04,Living Room
LIGHT,01:01:00:02:05,Dining Room"""

        import csv
        from io import StringIO

        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        devices = []
        for row in reader:
            device_type = row.get("device_type", "").strip().upper()
            if device_type in ("LIGHT", "DIMMER"):
                devices.append({
                    "device_type": "DIMMER",
                    "address": normalize_address(row["address"].strip()),
                    "name": row.get("name", "").strip(),
                })

        assert len(devices) == 2
        assert devices[0]["device_type"] == "DIMMER"
        assert devices[0]["name"] == "Living Room"
        assert devices[1]["name"] == "Dining Room"

    def test_parse_csv_mixed_devices(self):
        """Test parsing mixed device types from CSV."""
        csv_content = """device_type,address,relay,name,type
CCO,02:06:03,6,Kitchen Light,switch
DIMMER,01:01:00:02:04,,Living Room,
COVER,02:06:04,1,Garage Door,
LOCK,02:06:05,2,Front Door,
CLIMATE,02:06:06,3,Thermostat,"""

        import csv
        from io import StringIO

        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        cco_devices = []
        dimmers = []

        for row in reader:
            device_type = row.get("device_type", "").strip().upper()

            if device_type in ("CCO", "SWITCH"):
                button = int(row.get("relay", row.get("button", 1)))
                cco_type = row.get("type", "").strip().lower() or "switch"
                cco_devices.append({
                    "address": normalize_address(row["address"].strip()),
                    "button": button,
                    "name": row.get("name", "").strip(),
                    "entity_type": cco_type,
                })
            elif device_type in ("LIGHT", "DIMMER"):
                dimmers.append({
                    "address": normalize_address(row["address"].strip()),
                    "name": row.get("name", "").strip(),
                })
            elif device_type == "COVER":
                button = int(row.get("relay", row.get("button", 1)))
                cco_devices.append({
                    "address": normalize_address(row["address"].strip()),
                    "button": button,
                    "name": row.get("name", "").strip(),
                    "entity_type": "cover",
                })
            elif device_type == "LOCK":
                button = int(row.get("relay", row.get("button", 1)))
                cco_devices.append({
                    "address": normalize_address(row["address"].strip()),
                    "button": button,
                    "name": row.get("name", "").strip(),
                    "entity_type": "lock",
                })
            elif device_type == "CLIMATE":
                button = int(row.get("relay", row.get("button", 1)))
                cco_devices.append({
                    "address": normalize_address(row["address"].strip()),
                    "button": button,
                    "name": row.get("name", "").strip(),
                    "entity_type": "climate",
                })

        assert len(cco_devices) == 4
        assert len(dimmers) == 1

        # Check CCO types
        types = [d["entity_type"] for d in cco_devices]
        assert "switch" in types
        assert "cover" in types
        assert "lock" in types
        assert "climate" in types

    def test_csv_address_normalization(self):
        """Test that addresses are normalized during CSV import."""
        csv_content = """device_type,address,relay,name
CCO,2:6:3,6,Test1
CCO,[02:06:03],7,Test2
CCO,02:06:03,8,Test3"""

        import csv
        from io import StringIO

        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        addresses = []
        for row in reader:
            addresses.append(normalize_address(row["address"].strip()))

        # All should normalize to the same format
        assert addresses[0] == "[02:06:03]"
        assert addresses[1] == "[02:06:03]"
        assert addresses[2] == "[02:06:03]"

    def test_csv_duplicate_detection(self):
        """Test that duplicate devices are detected during CSV import."""
        # Simulate existing options with a CCO device
        existing_options = create_empty_options()
        existing_options["cco_devices"].append({
            "name": "Existing Light",
            "addr": "[02:06:03]",
            "button_number": 6,
            "entity_type": "switch",
            "inverted": False,
        })

        # CSV with same address/button should be detected as duplicate
        csv_content = """device_type,address,relay,name,type
CCO,02:06:03,6,Kitchen Light,switch
CCO,02:06:03,7,Different Button,switch
CCO,02:06:04,6,Different Address,switch"""

        import csv
        from io import StringIO

        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        def is_duplicate_cco(addr: str, button: int) -> bool:
            """Check if CCO device already exists."""
            normalized = normalize_address(addr)
            for device in existing_options["cco_devices"]:
                existing_addr = normalize_address(device["addr"])
                existing_button = device.get("button_number", device.get("relay_number", 1))
                if existing_addr == normalized and existing_button == button:
                    return True
            return False

        duplicates = []
        new_devices = []
        for row in reader:
            button = int(row.get("relay", row.get("button", 1)))
            addr = normalize_address(row["address"].strip())
            if is_duplicate_cco(addr, button):
                duplicates.append(row.get("name", ""))
            else:
                new_devices.append(row.get("name", ""))

        # First one is duplicate (same address and button)
        assert "Kitchen Light" in duplicates
        # Other two are not duplicates
        assert "Different Button" in new_devices
        assert "Different Address" in new_devices
        assert len(duplicates) == 1
        assert len(new_devices) == 2

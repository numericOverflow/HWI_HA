# Lutron Homeworks HWI Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for Lutron Homeworks Series 4 and Series 8 lighting control systems.

## Features

- **CCO Relay Control**: Switch, light, cover, and lock entities backed by CCO relays
- **Dimmable Lights**: Full brightness control for RPM, D48, H48, and RF dimmers
- **Keypad Buttons**: Expose keypad buttons as button entities with LED state feedback
- **Physical Button Events**: Every keypad button also gets an `event` entity that timestamps presses, releases, holds, and double taps reported by the processor (`KBP`/`KBR`/`KBH`/`KBDT`), so automations can react to presses made on the physical keypad
- **KLS State Engine**: Automatic state synchronization via KLS polling
- **Inversion Support**: Handle normally-closed relay configurations
- **Auto-Reconnect**: Automatic reconnection on connection loss

## Requirements

- Home Assistant 2024.1.0 or newer
- Lutron Homeworks Series 4 or Series 8 processor
- Network access to processor (typically via Ethernet-to-serial adapter on port 23)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner
3. Select "Custom repositories"
4. Add this repository URL: `https://github.com/kaaspad/HWI_HA`
5. Select "Integration" as the category
6. Click "Add"
7. Search for "Lutron Homeworks HWI" in HACS
8. Click "Download"
9. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Copy the `custom_components/homeworks_hwi` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Lutron Homeworks HWI"
3. Enter the connection details:
   - **Controller Name**: A friendly name for this controller
   - **Host**: IP address or hostname of the processor
   - **Port**: TCP port (default: 23)
   - **Username/Password**: Optional authentication credentials

### Adding Devices

After initial setup, use the **Configure** button to add devices:

#### CCO Devices (Switches, Lights, Covers, Locks)

CCO devices are relay-controlled outputs. To add one:

1. Go to **Options** → **Manage CCO devices** → **Add CCO device**
2. Enter:
   - **Device name**: Friendly name
   - **Address**: Format `[processor:link:address]` (e.g., `[02:06:03]`)
   - **Button/Relay number**: 1-8 for CCO modules, 1-24 for keypads
   - **Device type**: Switch, Light, Cover, or Lock
   - **Invert on/off**: Enable if relay is normally-closed

#### Dimmable Lights

For dimmers with brightness control:

1. Go to **Options** → **Manage dimmable lights** → **Add dimmable light**
2. Enter:
   - **Light name**: Friendly name
   - **Dimmer address**: Varies by dimmer type (RPM, D48, H48, RF)
   - **Fade rate**: Transition time in seconds

#### Keypads

To receive button events:

1. Go to **Options** → **Manage keypads** → **Add keypad**
2. Enter the keypad address
3. Add individual buttons with LED tracking if needed

### Controller Settings

Configure protocol-level settings:

- **KLS Poll Interval**: How often to poll for CCO state (default: 10 seconds)
- **KLS Window Offset**: Starting index of button window in KLS string (default: 9)

### CSV Import

Bulk import devices using CSV with columns:
- `device_type`: CCO, SWITCH, LIGHT, DIMMER, COVER, LOCK
- `address`: Device address
- `relay` or `button`: Button/relay number (for CCO devices)
- `name`: Device name

Example:
```csv
device_type,address,relay,name
CCO,02:06:03,6,Kitchen Light
DIMMER,01:01:00:02:04,,Living Room
```

## Technical Details

### Address Formats

- **CCO/Keypad**: `[processor:link:address]` (e.g., `[02:06:03]`)
- **Dimmer**: `[processor:link:router:bus:dimmer]` (varies by type)

### KLS State Engine

CCO devices do not have direct monitoring. State is derived from the KLS (Keypad LED State) response, which contains a 24-digit string. The meaningful 8-digit "button window" starts at a configurable offset (default: index 9).

For button N (1-8): `index = window_offset + (N-1)`

Digit values:
- `1` = ON (relay closed)
- `2` = OFF (relay open)
- `0` = Not applicable

### Protocol Commands

The integration uses these Homeworks commands:
- `RKLS`: Request Keypad LED States
- `CCOCLOSE`: Close CCO relay (turn ON)
- `CCOOPEN`: Open CCO relay (turn OFF)
- `FADEDIM`: Fade dimmer to level

## Known Limitations

1. **Cover Position**: CCO-based covers show only open/closed state, not position
2. **Polling Latency**: CCO state updates depend on KLS poll interval
3. **Single Processor**: Each integration instance supports one processor

## Troubleshooting

### Connection Issues

1. Verify the processor IP address and port
2. Check firewall rules allow connection
3. Try connecting with telnet: `telnet <host> <port>`

### Wrong CCO State

1. Check the KLS window offset in Controller Settings
2. Verify the button/relay number matches your wiring
3. Check if inversion is needed for your relay configuration

### Enable Debug Logging

Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.homeworks_hwi: debug
```

## Services

### `homeworks.send_command`

Send raw commands to the processor:

```yaml
service: homeworks.send_command
data:
  controller_id: lutron_homeworks
  command:
    - "FADEDIM, 50, 2.0, 0, [01:01:00:02:04]"
    - "delay 500"
    - "RKLS, [02:06:03]"
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

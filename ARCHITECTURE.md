# Lutron Homeworks Integration Architecture

## Overview

This integration provides Home Assistant support for Lutron Homeworks Series 4 and Series 8 lighting control systems. The key architectural challenge is handling CCO (Contact Closure Output) devices which have no direct state feedback - their state must be derived from KLS (Keypad LED State) polling.

## Key Concepts

### CCO State Engine

CCOs have **NO direct monitoring**. There is no `CCOMON` command or push feedback for CCO state. The only way to determine CCO state is by:

1. Polling KLS (Keypad LED State) for the CCO's address
2. Parsing the 24-digit LED state string
3. Mapping the button number to the correct position in the string
4. Interpreting the digit: `1 = ON (relay closed)`, `2 = OFF (relay open)`

This is implemented as a centralized state engine in the `HomeworksCoordinator`.

### Address Model

**CCO Addressing**: `processor:link:address,button`
- Example: `2:6:3,6` means processor 2, link 6, CCO address 3, button/relay 6
- The `(processor, link, address)` tuple identifies the keypad/CCO unit
- The `button` (1-24) selects which output/relay

**KLS Address**: `[pp:ll:aa]`
- Always 3 parts, zero-padded
- Example: `[02:06:03]`

**Dimmer Addressing**: Varies by type (3-5 parts)
- RPM: `processor:link:MI:module:zone`
- D48/H48: `processor:link:router:bus:dimmer`

### Device Types

1. **Dimmable Lights** - Use `FADEDIM` command, receive `DL` (Dimmer Level) feedback
2. **CCO Switches** - Use `CCOCLOSE`/`CCOOPEN`, derive state from KLS
3. **CCO Lights** - Same as switches, but exposed as light entities (on/off only)
4. **CCO Covers** - Same protocol, exposed as cover entities
5. **CCO Locks** - Same protocol, exposed as lock entities

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Home Assistant Core                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Light     │  │   Switch    │  │   Cover     │  ...         │
│  │  Platform   │  │  Platform   │  │  Platform   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              HomeworksCoordinator                            │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │                 CCO State Engine                        │ │ │
│  │  │  • Maintains CCO device registry                        │ │ │
│  │  │  • Caches KLS states by address                         │ │ │
│  │  │  • Maps buttons to state values                         │ │ │
│  │  │  • Handles inversion logic                              │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  │                          │                                    │ │
│  │                          ▼                                    │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │                 HomeworksClient                         │ │ │
│  │  │  • Async socket communication                           │ │ │
│  │  │  • Automatic reconnection                               │ │ │
│  │  │  • Message parsing                                      │ │ │
│  │  │  • Command rate limiting                                │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                          │                                        │
└──────────────────────────┼────────────────────────────────────────┘
                           │
                           ▼
              ┌───────────────────────┐
              │  Lutron Homeworks     │
              │  Controller (RS-232)  │
              │  via NPort/IP adapter │
              └───────────────────────┘
```

## Component Responsibilities

### `client.py` - HomeworksClient

- Async TCP socket connection to controller
- Handles login sequence if credentials required
- Subscribes to monitoring events (KBMON, DLMON, KLMON, GSMON)
- Parses incoming messages (KLS, DL, KBP, etc.)
- Provides command methods (fade_dim, cco_close, cco_open, etc.)
- Automatic reconnection with exponential backoff
- Health metrics tracking

### `coordinator.py` - HomeworksCoordinator

- Extends `DataUpdateCoordinator` for periodic polling
- **CCO State Engine**: Central registry of all CCO devices
- KLS polling for all registered CCO addresses
- Dimmer level tracking
- State caching with timestamps
- Dispatches updates to entities

### `models.py` - Data Models

- `CCOAddress`: Canonical address representation
- `CCODevice`: Device configuration with type and inversion
- `KLSState`: Parsed LED state with timestamp
- `ControllerHealth`: Health metrics

### Platform Files

- `light.py`: Dimmable lights and CCO on/off lights
- `switch.py`: CCO-backed switches
- `cover.py`: CCO-backed covers
- `lock.py`: CCO-backed locks
- `sensor.py`: Health/diagnostic sensors
- `binary_sensor.py`: Keypad LED indicators
- `button.py`: Keypad button simulation (actuator only — `ButtonEntity.state` is `@final` and only reflects presses made through Home Assistant)
- `event.py`: Keypad button activations reported by the processor (`KBP`/`KBR`/`KBH`/`KBDT`), which is where physical presses show up

## Configuration Structure

```python
{
    "controller_id": "lutron_homeworks",
    "host": "192.168.1.100",
    "port": 23,
    "username": "...",  # Optional
    "password": "...",  # Optional

    # Dimmable lights (RPM, D48, H48, RF dimmers)
    "dimmers": [
        {"addr": "[01:01:00:02:04]", "name": "Kitchen Light", "rate": 1.0}
    ],

    # CCO-backed devices (unified model)
    "cco_devices": [
        {
            "addr": "[02:06:03]",
            "button_number": 1,
            "name": "Garage Door",
            "entity_type": "switch",  # switch, light, cover, lock
            "inverted": false
        }
    ],

    # Keypads for button events
    "keypads": [
        {
            "addr": "[01:04:10]",
            "name": "Entry Keypad",
            "buttons": [
                {"number": 1, "name": "All Off", "led": true, "release_delay": 0}
            ]
        }
    ]
}
```

## State Flow for CCO Devices

1. **Polling**: Coordinator polls `RKLS` for each registered CCO address every 10 seconds
2. **Response**: Controller sends `KLS, [pp:ll:aa], <24-digit string>`
3. **Parsing**: Client parses KLS message, caches in coordinator
4. **Mapping**: For each registered CCO device at this address:
   - Extract button state from position `button - 1` in LED array
   - Apply inversion if configured
   - Update state cache
5. **Notification**: Coordinator calls `async_set_updated_data`
6. **Entity Update**: Entities receive `_handle_coordinator_update`, call `async_write_ha_state`

## Protocol Commands Used

| Command | Purpose | Response |
|---------|---------|----------|
| `RKLS, [addr]` | Request LED states | `KLS, [addr], <24 digits>` |
| `RDL, [addr]` | Request dimmer level | `DL, [addr], <level>` |
| `CCOCLOSE, [addr], relay` | Close CCO relay | `KLS` update |
| `CCOOPEN, [addr], relay` | Open CCO relay | `KLS` update |
| `FADEDIM, level, fade, delay, [addr]` | Fade dimmer | `DL` update |
| `KBP, [addr], button` | Keypad button press | - |
| `KBR, [addr], button` | Keypad button release | - |

## Migration from Legacy Config

The integration supports both new-style `cco_devices` and legacy separate lists:
- `ccos` → switch entities
- `covers` → cover entities
- `locks` → lock entities

Legacy configs are automatically mapped during setup. New devices should use `cco_devices` with explicit `entity_type`.

# HWI_HA — Unified Assessment v4 (Implementation Spec)

## Purpose

Single authoritative implementation spec. All verification findings resolved.
Minimum HA version: **2024.12.0**. All code examples validated against HA Core APIs.

**Status legend**:
- **ACCEPTED** — queued for implementation
- **CANT-FIX** — inherent hardware/platform limitation; acknowledged, no action
- **WONT-FIX** — standard platform pattern; properly mitigated already
- **IGNORED** — no action per user decision
- **DEFERRED** — separate document/commit required

---

## Part 1: Security Posture Summary

**Methodology**: STRIDE threat modeling, OWASP IoT Top 10, HA Integration Quality Scale

### Security Positive Patterns

| Practice | Status |
|----------|--------|
| Config flow for setup (no YAML secrets) | ✅ |
| Credentials in `entry.data`, devices in `entry.options` | ✅ |
| Diagnostics redaction (`CONF_HOST`, `CONF_PASSWORD`, `CONF_USERNAME`) | ✅ |
| Service schema validation (voluptuous) | ✅ |
| Reauth flow for credential rotation | ✅ |
| Connection timeout on config flow validation (10s) | ✅ |
| Auto-reconnect with exponential backoff (1s→60s) | ✅ |
| Command rate limiting (50ms inter-command via `asyncio.Lock`) | ✅ |

### Acknowledged Security Risks (No Action)

| Finding | Severity | Decision | Rationale |
|---------|----------|----------|-----------|
| Plaintext credential transmission over TCP | MEDIUM (CVSS 5.7) | **CANT-FIX** | Inherent to Lutron Homeworks protocol — hardware does not support TLS. Controller should be on isolated network. |
| Credentials stored as plaintext JSON on disk | MEDIUM (CVSS 4.0) | **WONT-FIX** | Standard HA `entry.data` pattern. Properly mitigated: diagnostics redaction in place, credential/device separation correct. |
| Duplicate protocol library (`pyhomeworks/` + `hwi_protocol/`) | LOW | **IGNORED** | Valid reasons to embed — upstream `pyhomeworks` PyPI package has unresolved bugs/constraints. Will switch when upstream commits fixes. |
| No rate limiting on service call level | INFORMATIONAL | **IGNORED** | Client-layer rate limiting (50ms + `asyncio.Lock`) is sufficient. No pending fix needed. |

---

## Part 2: Quality Scale Compliance

### Bronze Rules

| Rule                        | Status             | Evidence |
| --------------------------- | ------------------ | -------- |
| `config-flow`               | **Done**           | `config_flow.py` implements `ConfigFlow` + `SchemaOptionsFlowHandler` |
| `config-flow-test-coverage` | **Gap**            | No actual config flow tests — **Fix A ACCEPTED** |
| `test-before-configure`     | **Done**           | `_try_connection()` with 10s timeout validates connectivity |
| `unique-config-entry`       | **Done** (partial) | host:port check exists; missing `controller_id` — **Fix B ACCEPTED** |
| `entity-unique-id`          | **Done**           | All entities use `f"homeworks.{controller_id}...v2"` pattern |
| `has-entity-name`           | **Inconsistent**   | Two patterns coexist — **Finding 3 ACCEPTED** |
| `common-modules`            | **Gap**            | CCO boilerplate duplicated 6× — **Finding 5 ACCEPTED** |
| `runtime-data`              | **Gap**            | Uses `hass.data[DOMAIN]` — **Finding 1 ACCEPTED** |
| `dependency-transparency`   | **Done**           | `requirements: []` accurate (protocol embedded due to upstream bugs) |
| `appropriate-polling`       | **Done**           | 10s KLS, 30s dimmer — reasonable |
| `brands`                    | **N/A**            | HACS |
| `action-setup`              | **Done**           | Service registered in `async_setup()` |

### Silver Rules

| Rule                     | Status      | Evidence |
| ------------------------ | ----------- | -------- |
| `config-entry-unloading` | **Done**    | `async_unload_entry()` correct |
| `entity-unavailable`     | **Gap**     | No stale-KLS detection — **Fix C ACCEPTED** |
| `log-when-unavailable`   | **Partial** | No per-entity transition logging — **Fix D ACCEPTED** |
| `integration-owner`      | **Done**    | `@kaaspad` in manifest |
| `parallel-updates`       | **Not set** | Acceptable; `= 0` for documentation — **Finding 6-QS ACCEPTED** |
| `test-coverage`          | **Gap**     | HA integration tests placeholder — **DEFERRED (separate commit)** |
| `action-exceptions`      | **Done**    | `ServiceValidationError` raised correctly |

### Gold Rules

| Rule                  | Status      | Evidence |
| --------------------- | ----------- | -------- |
| `devices`             | **Done**    | Proper `DeviceInfo` everywhere |
| `diagnostics`         | **Done**    | Redacted health/device diagnostics |
| `entity-category`     | **Gap**     | Health sensors need `DIAGNOSTIC` — **Fix E ACCEPTED** |
| `entity-device-class` | **Partial** | Appropriate where applicable |
| `entity-translations` | **Gap**     | Entity names hardcoded |
| `icon-translations`   | **Gap**     | Icons in Python not `icons.json` — **Fix F ACCEPTED** |
| `discovery`           | **N/A**     | Hardware doesn't support discovery |

---

## Part 3: Entity Platform Compliance Matrix

| Platform                 | CoordinatorEntity | has_entity_name  | Symmetric Lifecycle | Assessment | Key Issue |
| ------------------------ | ----------------- | ---------------- | ------------------- | ---------- | --------- |
| `light.py` (dimmer)      | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `light.py` (CCO)         | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `switch.py`              | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `cover.py` (CCO)         | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `cover.py` (RPM)         | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `cover.py` (QED)         | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `lock.py`                | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `fan.py`                 | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `climate.py`             | Yes               | Not set (legacy) | ❌ No unregister    | **Warn**   | Finding 4 |
| `binary_sensor.py` (LED) | Yes               | ✅ True          | N/A (no per-entity registration) | **Pass** | Finding 13 (public API only) |
| `binary_sensor.py` (CCI) | Yes               | Not set (legacy) | ✅ Symmetric        | **Pass**   | — |
| `button.py`              | No (stateless)    | ✅ True          | N/A                 | **Pass**   | — |
| `sensor.py`              | Yes               | ✅ True          | N/A                 | **Pass**   | Needs EntityCategory |

> **Note on LED binary_sensor**: The `_kls_poll_addresses.add()` call happens once at platform setup for the whole keypad, NOT per-entity. Individual LED entities don't register/unregister — they only read coordinator state. No `async_will_remove_from_hass()` needed.

---

## Part 4: All Findings

### Finding 1: `hass.data[DOMAIN]` → `entry.runtime_data` — **ACCEPTED**

`__init__.py` uses `hass.data.setdefault(DOMAIN, {})` and `hass.data[DOMAIN][entry.entry_id]` to store `HomeworksData`. The modern HA pattern (required for Core integrations since ~2024.4) uses `entry.runtime_data`.

#### Remediation

1. Define a typed config entry alias:
   ```python
   type HomeworksHWIConfigEntry = ConfigEntry[HomeworksData]
   ```

2. In `async_setup_entry`, replace storage:
   ```python
   # Before:
   hass.data.setdefault(DOMAIN, {})
   hass.data[DOMAIN][entry.entry_id] = HomeworksData(
       coordinator=coordinator, controller_id=controller_id
   )

   # After:
   entry.runtime_data = HomeworksData(
       coordinator=coordinator, controller_id=controller_id
   )
   ```

3. In `async_unload_entry`, read from `entry.runtime_data` (auto-cleaned by HA):
   ```python
   # Before:
   data: HomeworksData = hass.data[DOMAIN].pop(entry.entry_id)

   # After:
   data = entry.runtime_data
   ```

4. Update all platform `async_setup_entry` functions:
   ```python
   # Before:
   data: HomeworksData = hass.data[DOMAIN][entry.entry_id]

   # After:
   data = entry.runtime_data
   ```

5. Remove `hass.data.setdefault(DOMAIN, {})` entirely.

6. Update `async_send_command()` to use `async_loaded_entries`:
   ```python
   # Before:
   for hw_data in hass.data[DOMAIN].values():
       if hw_data.controller_id == controller_id:
           return hw_data

   # After:
   for loaded_entry in hass.config_entries.async_loaded_entries(DOMAIN):
       data: HomeworksData = loaded_entry.runtime_data
       if data.controller_id == controller_id:
           return data
   ```

   > **Implementation note**: `async_loaded_entries()` returns `list[ConfigEntry]` (untyped). Assign `loaded_entry.runtime_data` to a typed local variable for type safety.

---

### Finding 2: `async_setup_entry()` Is Overloaded

Three cleanup functions (`_cleanup_old_entities`, `_cleanup_devices_without_areas`, `_cleanup_orphaned_devices`) run on **every entry load**.

**Recommendation**: Option B — move cleanup into `async_migrate_entry()` (Finding 6-legacy). After migration, `async_setup_entry()` reduces to: create coordinator → connect → forward platforms.

---

### Finding 3: `has_entity_name` Inconsistency — **ACCEPTED**

Two patterns coexist without runtime conflict:

**Pattern A — Modern** (`binary_sensor` LED, `button`, `sensor`):
- Sets `_attr_has_entity_name = True`
- Uses `_attr_name` for entity-specific name
- HA prepends device name automatically

**Pattern B — Legacy** (`switch`, `light`, `cover`, `lock`, `climate`, `fan`):
- Does NOT set `_attr_has_entity_name` (defaults to `False`)
- Overrides `name` property returning full name via `_entity_name`
- `DeviceInfo.name` set to same value → device and entity share name

**Clarification**: CCO entities inherit from `CoordinatorEntity`, NOT `HomeworksEntity`. No attribute collision exists — but the inconsistency blocks Core inclusion.

#### Remediation

Migrate all CCO entities to Pattern A. For single-entity devices:
```python
_attr_has_entity_name = True
_attr_name = None  # Entity IS the device — inherit device name
```

> **Device mapping note**: Each CCO entity creates its own device with a unique identifier that includes the button number (e.g., `f"{controller_id}.cco.{address}.v2"`). This is a 1:1 entity-to-device mapping. Therefore `_attr_name = None` is correct for ALL CCO entities — each entity IS its device.

Remove the `name` property override and `_entity_name` instance variable from all CCO entity classes.

---

### Finding 4: Missing `async_will_remove_from_hass()` — **ACCEPTED**

Affected: `HomeworksDimmableLight`, `HomeworksCCOLight`, `HomeworksCCOSwitch`, `HomeworksCCOCover`, `HomeworksRPMCover`, `HomeworksQEDCover`, `HomeworksCCOFan`, `HomeworksCCOClimate`, `HomeworksCCOLock`.

#### Remediation

Add symmetric cleanup to each entity class. Examples:

**Dimmer light** (`light.py`):
```python
async def async_will_remove_from_hass(self) -> None:
    """Unregister dimmer when removed from hass."""
    self.coordinator.unregister_dimmer(self._addr)
    await super().async_will_remove_from_hass()
```

**CCO-based entities** (`switch.py`, `lock.py`, `fan.py`, `climate.py`, CCO `light.py`, CCO `cover.py`):
```python
async def async_will_remove_from_hass(self) -> None:
    """Unregister CCO device when removed from hass."""
    self.coordinator.unregister_cco_device(self._device.address)
    await super().async_will_remove_from_hass()
```

**RPM cover** (`cover.py`):
```python
async def async_will_remove_from_hass(self) -> None:
    """Unregister dimmer address when removed from hass."""
    self.coordinator.unregister_dimmer(self._addr)
    await super().async_will_remove_from_hass()
```

**QED cover** (`cover.py`):
```python
async def async_will_remove_from_hass(self) -> None:
    """Unregister dimmer address when removed from hass."""
    self.coordinator.unregister_dimmer(self._addr)
    await super().async_will_remove_from_hass()
```

---

### Finding 5: CCO Device Creation Duplication — **ACCEPTED**

Compared across all 6 CCO platforms — **100% safely combinable**:

| Code Section | Identical? | Differences |
|--------------|-----------|-------------|
| Data access | ✅ Yes | — |
| CCO_TYPE filter | ✅ Only constant differs | Parameterizable |
| Address parsing | ✅ Identical across all 6 | — |
| `CCODevice(...)` construction | ✅ Same pattern | Only enum + default_name differ |
| Entity class instantiation | ✅ Same call signature | Only class differs |
| Exception handling | ✅ Identical pattern | Only log noun differs |

#### Remediation

Extract shared helper (in `__init__.py` or `helpers.py`):

```python
def _parse_cco_device_config(
    hass: HomeAssistant,
    device_config: dict[str, Any],
    entity_type: CCOEntityType,
    default_name: str,
) -> CCODevice:
    """Parse a CCO device config dict into a CCODevice."""
    addr_str = device_config[CONF_ADDR]
    button = device_config.get(
        CONF_BUTTON_NUMBER, device_config.get(CONF_RELAY_NUMBER, 1)
    )
    if "," not in addr_str:
        full_addr = f"{addr_str},{button}"
    else:
        full_addr = addr_str

    address = CCOAddress.from_string(full_addr)

    return CCODevice(
        address=address,
        name=device_config.get(CONF_NAME, default_name),
        entity_type=entity_type,
        inverted=device_config.get(CONF_INVERTED, False),
        area=resolve_area_name(hass, device_config.get(CONF_AREA)),
    )


def create_cco_entities_for_type(
    hass: HomeAssistant,
    entry: HomeworksHWIConfigEntry,
    coordinator: HomeworksCoordinator,
    controller_id: str,
    target_type: str,
    entity_type: CCOEntityType,
    entity_cls: type,
    default_name: str,
) -> list[Entity]:
    """Create CCO entities of a given type from config options.

    Constructor contract: entity_cls MUST accept keyword arguments
    (coordinator, controller_id, device). All CCO entity classes follow this.
    """
    entities = []
    for device_config in entry.options.get(CONF_CCO_DEVICES, []):
        if device_config.get(CONF_ENTITY_TYPE) != target_type:
            continue
        try:
            device = _parse_cco_device_config(hass, device_config, entity_type, default_name)
            entities.append(entity_cls(coordinator=coordinator, controller_id=controller_id, device=device))
        except (ValueError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Invalid config for %s device '%s': %s",
                target_type,
                device_config.get(CONF_NAME, "unknown"),
                err,
            )
    return entities
```

Each platform file then becomes:

```python
# fan.py async_setup_entry:
async def async_setup_entry(hass, entry, async_add_entities):
    data = entry.runtime_data
    entities = create_cco_entities_for_type(
        hass, entry, data.coordinator, entry.options[CONF_CONTROLLER_ID],
        CCO_TYPE_FAN, CCOEntityType.FAN, HomeworksCCOFan, DEFAULT_FAN_NAME,
    )
    if entities:
        async_add_entities(entities)
```

---

### Finding 6-legacy: Legacy Format Migration — **ACCEPTED**

**Current state**: Config entries at `VERSION = 1` may contain:
- `CONF_CCO_DEVICES` (new format) — unified list with `entity_type` field
- `CONF_CCOS` (legacy) — switch-only, uses `CONF_RELAY_NUMBER`
- `CONF_COVERS` (legacy) — cover-only, button defaults to 1
- `CONF_LOCKS` (legacy) — lock-only, uses `CONF_RELAY_NUMBER`

#### Migration Implementation

```python
# In config_flow.py:
class HomeworksConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    VERSION = 2  # Bump from 1

# In __init__.py:
async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry to current version."""
    if config_entry.version == 1:
        _LOGGER.info("Migrating config entry %s from v1 to v2", config_entry.entry_id)
        new_options = dict(config_entry.options)

        # Convert legacy CCOS → CCO_DEVICES
        for cco in new_options.pop(CONF_CCOS, []):
            device = {
                CONF_ADDR: cco[CONF_ADDR],
                CONF_BUTTON_NUMBER: cco.get(CONF_RELAY_NUMBER, 1),
                CONF_NAME: cco.get(CONF_NAME, ""),
                CONF_ENTITY_TYPE: CCO_TYPE_SWITCH,
                CONF_INVERTED: cco.get(CONF_INVERTED, False),
            }
            if CONF_AREA in cco:
                device[CONF_AREA] = cco[CONF_AREA]
            new_options.setdefault(CONF_CCO_DEVICES, []).append(device)

        # Convert legacy COVERS → CCO_DEVICES
        for cover in new_options.pop(CONF_COVERS, []):
            device = {
                CONF_ADDR: cover[CONF_ADDR],
                CONF_BUTTON_NUMBER: 1,
                CONF_NAME: cover.get(CONF_NAME, ""),
                CONF_ENTITY_TYPE: CCO_TYPE_COVER,
                CONF_INVERTED: cover.get(CONF_INVERTED, False),
            }
            if CONF_AREA in cover:
                device[CONF_AREA] = cover[CONF_AREA]
            new_options.setdefault(CONF_CCO_DEVICES, []).append(device)

        # Convert legacy LOCKS → CCO_DEVICES
        for lock_cfg in new_options.pop(CONF_LOCKS, []):
            device = {
                CONF_ADDR: lock_cfg[CONF_ADDR],
                CONF_BUTTON_NUMBER: lock_cfg.get(CONF_RELAY_NUMBER, 1),
                CONF_NAME: lock_cfg.get(CONF_NAME, ""),
                CONF_ENTITY_TYPE: CCO_TYPE_LOCK,
                CONF_INVERTED: lock_cfg.get(CONF_INVERTED, False),
            }
            if CONF_AREA in lock_cfg:
                device[CONF_AREA] = lock_cfg[CONF_AREA]
            new_options.setdefault(CONF_CCO_DEVICES, []).append(device)

        hass.config_entries.async_update_entry(
            config_entry, options=new_options, version=2
        )
        _LOGGER.info(
            "Migration complete: %d CCO devices total",
            len(new_options.get(CONF_CCO_DEVICES, [])),
        )

    return True
```

**Safety**: HA calls `async_migrate_entry()` before `async_setup_entry()`. If migration fails (returns `False`), the entry stays unloaded — no data loss. The original `entry.options` is preserved in `.storage/` until the next successful write.

**After migration**: Remove all legacy iteration code from `_register_cco_devices_from_options()`, `switch.py`, and `cover.py`. Keep `CONF_CCOS`, `CONF_COVERS`, `CONF_LOCKS` constants for the migration function only.

> **Phase ordering note**: Phase 2 (runtime_data, item 9) MUST maintain backward-compat with legacy key iteration (`CONF_CCOS`, `CONF_COVERS`, `CONF_LOCKS`) until Phase 3 (item 18, this migration) ships. If Phase 2 deploys without Phase 3, VERSION stays at 1 and legacy keys still exist in options. This is safe but means legacy code paths remain active.

---

### Finding 6-QS: `PARALLEL_UPDATES` — **ACCEPTED**

Set in all platform files:
```python
# Serialization handled by client-layer asyncio.Lock (50ms inter-command delay).
# 0 = unlimited HA-level parallelism — entities queue at the client lock.
PARALLEL_UPDATES = 0
```

**Clarification**: `PARALLEL_UPDATES = 0` means unlimited (no HA semaphore). `1` would mean serialized. The client's `asyncio.Lock` already serializes hardware commands — adding HA-level serialization would be redundant double-serialization and slower.

---

### Finding 7: `_parse_entity_type()` Missing `climate`/`fan` — **BUG, ACCEPTED**

**Current** (in `__init__.py`):
```python
type_map = {
    CCO_TYPE_SWITCH: CCOEntityType.SWITCH,
    CCO_TYPE_LIGHT: CCOEntityType.LIGHT,
    CCO_TYPE_COVER: CCOEntityType.COVER,
    CCO_TYPE_LOCK: CCOEntityType.LOCK,
}
return type_map.get(type_str.lower(), CCOEntityType.SWITCH)
```

**Fix** — add the missing mappings:
```python
type_map = {
    CCO_TYPE_SWITCH: CCOEntityType.SWITCH,
    CCO_TYPE_LIGHT: CCOEntityType.LIGHT,
    CCO_TYPE_COVER: CCOEntityType.COVER,
    CCO_TYPE_LOCK: CCOEntityType.LOCK,
    CCO_TYPE_CLIMATE: CCOEntityType.CLIMATE,
    CCO_TYPE_FAN: CCOEntityType.FAN,
}
return type_map.get(type_str.lower(), CCOEntityType.SWITCH)
```

Without this, climate/fan CCO devices registered through `__init__.py` are silently treated as switches in the coordinator's device registry, even though the entity platform creates them correctly.

---

### Finding 8: `callable` → `Callable` Type Annotation — **ACCEPTED**

**Current** (in `coordinator.py`):
```python
self._button_callbacks: dict[str, list[callable[[str, int, str], None]]] = {}
self._cci_callbacks: dict[tuple[int, int, int, int], list[callable[[bool], None]]] = {}
```

`callable` is a built-in function, not a type hint.

**Fix**:
```python
from collections.abc import Callable

self._button_callbacks: dict[str, list[Callable[[str, int, str], None]]] = {}
self._cci_callbacks: dict[tuple[int, int, int, int], list[Callable[[bool], None]]] = {}
```

Also fix the `register_cci_callback` and `register_button_callback` signatures:
```python
def register_cci_callback(
    self,
    address: str,
    input_number: int,
    callback: Callable[[bool], None],
) -> Callable[[], None]:

def register_button_callback(
    self,
    address: str,
    callback: Callable[[str, int, str], None],
) -> Callable[[], None]:
```

---

### Finding 9: Broad Exception Handling — **ACCEPTED**

**Current** — every entity platform wraps device creation in:
```python
except Exception as err:
    _LOGGER.error("Failed to create switch for %s: %s", device_config, err)
```

**Fix**: Narrow to expected exceptions only:
```python
except (ValueError, KeyError, TypeError) as err:
    _LOGGER.error(
        "Invalid config for %s device '%s': %s",
        target_type,
        device_config.get(CONF_NAME, "unknown"),
        err,
    )
```

Note: This narrowing is already incorporated into the `create_cco_entities_for_type()` helper in Finding 5.

---

### Finding 10: `send_command` Delay Validation — **ACCEPTED (Option A: 60s cap)**

**Security context** (CVSS 6.5): Without cap, `delay 2147483647` blocks the event loop for ~24 days.

**Implementation**:
```python
MAX_COMMAND_DELAY_MS = 60000  # 60 seconds

for command in commands:
    if command.lower().startswith("delay"):
        try:
            delay = min(int(command.partition(" ")[2]), MAX_COMMAND_DELAY_MS)
        except (ValueError, IndexError):
            _LOGGER.warning("Invalid delay command ignored: %s", command)
            continue
        _LOGGER.debug("Sleeping for %s ms", delay)
        await asyncio.sleep(delay / 1000)
    else:
        _LOGGER.debug("Sending command '%s'", command)
        await client.send_command(command)
```

---

### Finding 11: Test Coverage Gaps — **DEFERRED (separate commit)**

Deferred to `testing_and_lifecycle.md` planning document.

---

### Finding 12: HACS Manifest Enhancement — **ACCEPTED**

Bump `homeassistant` minimum to `"2024.12.0"`. Add `"content_in_root": false`. Add `"zip_release": true` when release workflow is in place.

---

### Finding 13: Direct `_kls_poll_addresses` Access — **ACCEPTED**

**Current** (in `binary_sensor.py`):
```python
coordinator._kls_poll_addresses.add(keypad_addr)
```

**Fix** — add public method to `coordinator.py`:
```python
def register_kls_poll_address(self, address: str) -> None:
    """Register an address for KLS polling."""
    normalized = normalize_address(address)
    self._kls_poll_addresses.add(normalized)
    if self._client:
        self._client.register_kls_address(normalized)
```

Update `binary_sensor.py`:
```python
# Before:
coordinator._kls_poll_addresses.add(keypad_addr)

# After:
coordinator.register_kls_poll_address(keypad_addr)
```

---

### Finding 14: Verbose Debug Logging — **ACCEPTED**

Demote `_LOGGER.info("=== ...")` development dumps to `_LOGGER.debug()` across `switch.py`, `config_flow.py`, and `__init__.py`.  

---

### Finding 15: Raw Command Injection via `send_command` — **DEFERRED (separate commit) DO NOT CODE THIS FINDING 15 !!!!!**

**Security severity**: HIGH (CVSS 7.1)

**Problem**: `send_command` service forwards arbitrary strings to the controller via `send_raw()`. No validation or allowlist.

> **Scope note**: User blocklist (commands blocked even if on allowlist) is **DEFERRED** to a future commit. This implementation covers the default allowlist + raw command toggle only.

#### Recommended: Option C (Allowlist with admin override)

**Step 1** — Define allowlist in `const.py`:

```python
SAFE_COMMAND_PREFIXES: Final = frozenset({
    # Dimmer control
    "FADEDIM", "RAISEDIM", "LOWERDIM", "STOPDIM", "FLASHDIM", "STOPFLASH",
    # Dimmer/shade queries
    "RDL",
    # Keypad button simulation
    "KBP", "KBR", "KBH", "KBDT",
    # Keypad state queries
    "RKLS", "RKLBP", "RKES",
    # LED control
    "SETLED", "SETLEDS",
    # CCO relay control
    "CCOCLOSE", "CCOOPEN", "CCOPULSE",
    # Keypad enable/disable
    "KE", "KD",
    # GRAFIK Eye
    "GSS",
    # Monitoring control
    "PROMPTOFF", "KBMON", "GSMON", "DLMON", "KLMON",
})

CONF_ALLOW_RAW_COMMANDS: Final = "allow_raw_commands"
```

**Step 2** — Add config option in `config_flow.py`:

```python
# Add to DATA_SCHEMA_CONTROLLER_SETTINGS:
vol.Optional(CONF_ALLOW_RAW_COMMANDS, default=False): selector.BooleanSelector(),
```

**Step 3** — Validate in `async_send_command()`:

```python
async def async_send_command(hass: HomeAssistant, data: Mapping[str, Any]) -> None:
    """Send command to a controller."""
    # ... existing controller lookup ...

    allow_raw = entry.options.get(CONF_ALLOW_RAW_COMMANDS, False)

    for command in commands:
        if command.lower().startswith("delay"):
            try:
                delay = min(int(command.partition(" ")[2]), MAX_COMMAND_DELAY_MS)
            except (ValueError, IndexError):
                _LOGGER.warning("Invalid delay command ignored: %s", command)
                continue
            _LOGGER.debug("Sleeping for %s ms", delay)
            await asyncio.sleep(delay / 1000)
            continue

        # Validate command against allowlist
        cmd_prefix = command.split(",")[0].strip().upper()
        if cmd_prefix not in SAFE_COMMAND_PREFIXES:
            if not allow_raw:
                _LOGGER.warning(
                    "Blocked unrecognized command '%s' — enable 'Allow raw commands' "
                    "in controller settings to send arbitrary commands",
                    cmd_prefix,
                )
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="command_not_allowed",
                    translation_placeholders={"command": cmd_prefix},
                )
            _LOGGER.warning("Sending unvalidated raw command: %s", cmd_prefix)

        _LOGGER.debug("send_command: controller=%s, command=%s", controller_id, command)
        await client.send_command(command)
```

**Step 4** — Add translation strings:

```json
"command_not_allowed": "Command '{command}' is not in the allowed command list. Enable 'Allow raw commands' in controller settings to send arbitrary commands."
```

**Step 5** — Add strings.json option label:

```json
"allow_raw_commands": "Allow raw commands (advanced — bypasses command allowlist)"
```

---

### Finding 16: CSV Import Size/Row Limits — **ACCEPTED (limits only)**

**Security severity**: MEDIUM (CVSS 4.3)

```python
MAX_CSV_SIZE = 1_000_000  # 1MB
MAX_CSV_ROWS = 5000

async def async_parse_csv(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Parse CSV content."""
    content = user_input["csv_file"]

    if len(content) > MAX_CSV_SIZE:
        raise SchemaFlowError("csv_too_large")

    # Remove BOM if present
    if content.startswith('\ufeff'):
        content = content[1:]
    f = StringIO(content)
    reader = csv.DictReader(f)

    devices = []
    row_count = 0
    try:
        for row in reader:
            row_count += 1
            if row_count > MAX_CSV_ROWS:
                raise SchemaFlowError("csv_too_many_rows")
            # ... existing row processing ...
```

Add translation strings:
```json
"csv_too_large": "CSV file exceeds maximum size (1MB)",
"csv_too_many_rows": "CSV file exceeds maximum row count (5000)"
```

---

### Finding 17: `async_remove_config_entry_device` — **ACCEPTED**

**Security severity**: MEDIUM (CVSS 3.5)

```python
async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removal of a device only if it has no active entities."""
    entity_registry = er.async_get(hass)

    has_entities = any(
        entity.device_id == device_entry.id
        for entity in entity_registry.entities.values()
        if entity.config_entry_id == entry.entry_id
    )

    if has_entities:
        _LOGGER.debug(
            "Refusing device removal — device '%s' still has active entities",
            device_entry.name,
        )
        return False

    return True
```

---

### Finding 18: Area Assignment Strategy — **ACCEPTED**

`_assign_areas_to_devices()` directly mutates the device registry, overriding user manual area assignments.

**Fix**:
1. Remove `_assign_areas_to_devices()` function entirely
2. Remove `_cleanup_devices_without_areas()` function
3. Keep `suggested_area` in `DeviceInfo` in all entity constructors — this is correct and sufficient

If area re-assignment is needed after CSV re-import, make it an explicit user action in the options flow rather than automatic on every load.

---

### Finding 19: `add_update_listener` → `SchemaOptionsFlowHandlerWithReload` — **ACCEPTED**

**Context**: HA 2026.6 deprecated using `add_update_listener` together with reload methods in config flows. Will break from HA 2026.12. The current code uses this pattern.

**Current** (`__init__.py`):
```python
entry.async_on_unload(entry.add_update_listener(update_listener))

# ...

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
```

**Current** (`config_flow.py`):
```python
@staticmethod
@callback
def async_get_options_flow(config_entry: ConfigEntry) -> SchemaOptionsFlowHandler:
    """Get the options flow."""
    return SchemaOptionsFlowHandler(config_entry, OPTIONS_FLOW)
```

#### Remediation

**Step 1** — Remove from `__init__.py` `async_setup_entry`:
```python
# DELETE this line:
entry.async_on_unload(entry.add_update_listener(update_listener))
```

**Step 2** — Remove the `update_listener` function entirely from `__init__.py`:
```python
# DELETE:
async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
```

**Step 3** — In `config_flow.py`, switch to the reload-capable handler:
```python
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
    SchemaOptionsFlowHandler,
    SchemaOptionsFlowHandlerWithReload,  # ADD THIS IMPORT
)

# Change async_get_options_flow:
@staticmethod
@callback
def async_get_options_flow(config_entry: ConfigEntry) -> SchemaOptionsFlowHandler:
    """Get the options flow."""
    return SchemaOptionsFlowHandlerWithReload(config_entry, OPTIONS_FLOW)
```

**Effect**: When the user saves options, `SchemaOptionsFlowHandlerWithReload` automatically triggers a config entry reload — same behavior as before, but via the HA-supported mechanism instead of a deprecated listener pattern.

**Compatibility**: `SchemaOptionsFlowHandlerWithReload` is available in HA 2024.12+ (our minimum). No backward-compat concern.

---

## Part 5: Coordinator Issues

### Issue 1: No `config_entry` in `DataUpdateCoordinator.__init__()` — **ACCEPTED**

**Current**:
```python
super().__init__(hass, _LOGGER, name=..., update_interval=...)
```

**Fix**:
```python
super().__init__(hass, _LOGGER, config_entry=entry, name=..., update_interval=...)
```

Pass `ConfigEntry` into `HomeworksCoordinator.__init__()` from `async_setup_entry`. Benefits:
- Coordinator auto-registers for config entry unload
- Required for Core integrations from HA 2026.8+
- Enables `self.config_entry` access inside coordinator methods

### Issue 2: `_async_update_data()` Allocation — **ACCEPTED**

**Current** — copies state dicts every poll (entities don't consume `coordinator.data`):
```python
async def _async_update_data(self) -> dict[str, Any]:
    return {
        "cco_states": dict(self._cco_states),
        "dimmer_states": dict(self._dimmer_states),
        "connected": self.connected,
        "last_update": datetime.now().isoformat(),
    }
```

**Fix** — return lightweight metadata:
```python
async def _async_update_data(self) -> dict[str, Any]:
    if not self._client or not self._client.connected:
        raise UpdateFailed("Not connected to controller")
    await self._poll_kls_states()
    self._poll_count += 1
    return {"connected": True, "poll_count": self._poll_count}
```

### Issue 3: `datetime.now()` Without Timezone — **ACCEPTED**

| File | Current | Fix |
|------|---------|-----|
| `coordinator.py` `_async_update_data()` | `datetime.now().isoformat()` | `dt_util.utcnow()` |
| `models.py` `KLSState` | `field(default_factory=datetime.now)` | `field(default_factory=lambda: datetime.now(timezone.utc))` |
| `hwi_protocol/client.py` | `self._connected_at = datetime.now()` | `datetime.now(tz=timezone.utc)` |

Note: `ControllerHealth` in `models.py` already correctly uses `datetime.now(timezone.utc)` in `record_message()` and `record_kls()`.

---

## Part 6: `normalize_address` Triplication — **ACCEPTED (with tests)**

Three identical implementations: `models.py:308`, `hwi_protocol/protocol.py:51`, `hwi_protocol/commands.py:13`.

**Fix**: Canonicalize in `hwi_protocol/protocol.py`, import in `commands.py`:

```python
# hwi_protocol/commands.py — replace local definition with import:
from .protocol import normalize_address
```

Keep `models.py` copy until PyPI migration. Add synchronization test:

```python
def test_normalize_address_implementations_match():
    """Ensure all normalize_address implementations produce identical output."""
    from custom_components.homeworks_hwi.models import normalize_address as models_norm
    from custom_components.homeworks_hwi.hwi_protocol.protocol import normalize_address as proto_norm
    from custom_components.homeworks_hwi.hwi_protocol.commands import normalize_address as cmd_norm

    test_cases = ["1:2:3", "[01:02:03]", "1:2:3:4:5", "[1:2:3:4:5]", "01:02:03"]
    for addr in test_cases:
        assert models_norm(addr) == proto_norm(addr) == cmd_norm(addr), f"Mismatch for {addr}"
```

---

## Part 7: Protocol Library Strategy

**Decision**: Embedded `hwi_protocol/` remains. Upstream `pyhomeworks` has unresolved bugs. Will switch when upstream commits fixes. No PyPI publishing action now.

---

## Part 8: Proposed Fixes (Config Flow + Entity)

### Fix A: Config Flow Test Coverage — **ACCEPTED**

Create `tests/test_config_flow.py`:

```python
async def test_user_flow_success(hass):
    """Test successful config flow setup."""
    with patch("...client.HomeworksClient.connect", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_NAME: "Test", CONF_HOST: "192.168.1.1", CONF_PORT: 23},
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY

async def test_user_flow_connection_error(hass):
    """Test connection failure shows error."""
    with patch("...client.HomeworksClient.connect", side_effect=Exception("refused")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_NAME: "Test", CONF_HOST: "192.168.1.1", CONF_PORT: 23},
        )
        assert result["errors"]["base"] == "connection_error"

async def test_user_flow_duplicate_host_port(hass):
    """Test duplicate host:port detection."""
    # Create first entry, then attempt duplicate — assert abort

async def test_reauth_flow(hass):
    """Test reauth updates credentials and reloads."""
    # ... assert entry.data updated with new password
```

### Fix B: `controller_id` Duplicate Check — **ACCEPTED**

Add after the host:port check in `async_step_user()`:

```python
for entry in self._async_current_entries():
    if entry.options.get(CONF_CONTROLLER_ID) == controller_id:
        return self.async_abort(reason="duplicated_controller_id")
```

Add to `strings.json` → `config` → `abort`:
```json
"duplicated_controller_id": "A controller with this name already exists"
```

### Fix C: Stale KLS Unavailability — **ACCEPTED**

Override `available` in a shared mixin for CCO-based entities:

```python
class HomeworksCCOAvailabilityMixin:
    """Mixin providing stale-KLS unavailability for CCO entities."""

    @property
    def available(self) -> bool:
        """Return True if coordinator connected and KLS data fresh."""
        if not super().available or not self.coordinator.connected:
            return False
        health = self.coordinator.health
        if health.last_kls_time is None:
            return False
        if not self.coordinator.update_interval:
            return True  # Can't check freshness without interval
        age = (dt_util.utcnow() - health.last_kls_time).total_seconds()
        return age < (self.coordinator.update_interval.total_seconds() * 3)
```

This marks entities unavailable if KLS data is older than 3× the poll interval.

CCO entity classes use this mixin:
```python
class HomeworksCCOSwitch(HomeworksCCOAvailabilityMixin, CoordinatorEntity[HomeworksCoordinator], SwitchEntity):
    ...
```

> **MRO note**: Place mixin BEFORE `CoordinatorEntity` so its `available` property takes precedence and `super().available` resolves to `CoordinatorEntity.available`.

### Fix D: Availability Transition Logging — **ACCEPTED**

Add to the same `HomeworksCCOAvailabilityMixin`:

```python
class HomeworksCCOAvailabilityMixin:
    """Mixin providing stale-KLS unavailability + transition logging."""

    _was_available: bool | None = None

    @property
    def available(self) -> bool:
        """Return True if coordinator connected and KLS data fresh."""
        if not super().available or not self.coordinator.connected:
            return False
        health = self.coordinator.health
        if health.last_kls_time is None:
            return False
        if not self.coordinator.update_interval:
            return True
        age = (dt_util.utcnow() - health.last_kls_time).total_seconds()
        return age < (self.coordinator.update_interval.total_seconds() * 3)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator with availability logging."""
        now_available = self.available
        if self._was_available is not None:
            if self._was_available and not now_available:
                _LOGGER.warning("%s became unavailable (stale KLS data)", self.entity_id)
            elif not self._was_available and now_available:
                _LOGGER.info("%s is available again", self.entity_id)
        self._was_available = now_available
        self.async_write_ha_state()
```

> **Entity override requirement**: All CCO entity classes that previously overrode `_handle_coordinator_update` (most just called `self.async_write_ha_state()`) should remove their override and let the mixin handle it. If an entity needs custom logic, it must call `super()._handle_coordinator_update()`.

### Fix E: `EntityCategory.DIAGNOSTIC` for Health Sensors — **ACCEPTED**

Add to `HomeworksHealthSensor` base class in `sensor.py`:

```python
from homeassistant.const import EntityCategory

class HomeworksHealthSensor(CoordinatorEntity[HomeworksCoordinator], SensorEntity):
    """Base class for Homeworks health sensors."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
```

The connection status sensor keeps its `_attr_entity_registry_enabled_default = True` override — it's the one diagnostic users typically want visible, but it should still be categorized as `DIAGNOSTIC` for correct device page placement.

### Fix F: Icon Translations via `icons.json` — **ACCEPTED**

Replace hardcoded `@property def icon()` methods. Each sensor sets `_attr_translation_key`:

```json
{
  "entity": {
    "sensor": {
      "connection": {
        "default": "mdi:check-network",
        "state": {
          "disconnected": "mdi:network-off"
        }
      },
      "last_kls_time": { "default": "mdi:clock-check" },
      "reconnect_count": { "default": "mdi:connection" },
      "poll_failure_count": { "default": "mdi:alert-circle" },
      "parse_error_count": { "default": "mdi:alert" }
    }
  },
  "services": {
    "send_command": {
      "service": "mdi:console"
    }
  }
}
```

Each sensor class then sets `_attr_translation_key` and removes its `icon` property:

```python
class HomeworksConnectionSensor(HomeworksHealthSensor):
    _attr_entity_registry_enabled_default = True
    _attr_translation_key = "connection"

    def __init__(self, coordinator, controller_id):
        super().__init__(coordinator, controller_id, "connection", "Connection Status")
        # Remove icon property — icons.json handles it via translation_key + state
```

The `"state"` sub-key in `icons.json` handles the connection sensor's conditional icon natively — HA maps `native_value` to the corresponding icon.

> **Note on service icon format**: Per HA 2024.8+ schema, service icons use `{"service": "mdi:..."}` object format, not bare string.

---

## Part 9: Risks and Mitigations

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Raw commands to controller | HIGH (CVSS 7.1) | Command allowlist + configurable override | **Finding 15 ACCEPTED** |
| Unbounded delay in `send_command` | MEDIUM (CVSS 6.5) | Cap at 60s + ValueError handling | **Finding 10 ACCEPTED** |
| KLS poll failure → stale state | MEDIUM | Entity unavailability after 3× interval | **Fix C ACCEPTED** |
| CSV import DoS | MEDIUM (CVSS 4.3) | 1MB size + 5000 row limits | **Finding 16 ACCEPTED** |
| Unconditional device removal | MEDIUM (CVSS 3.5) | Check for active entities | **Finding 17 ACCEPTED** |
| Area override conflicts | MEDIUM | Remove forced assignment; `suggested_area` only | **Finding 18 ACCEPTED** |
| HA API breakage | MEDIUM | Bump `hacs.json` minimum; `runtime_data` migration | **Finding 1 ACCEPTED** |
| Legacy config corruption | MEDIUM | `async_migrate_entry()` with HA safety net | **Finding 6-legacy ACCEPTED** |
| Silent entity failures | MEDIUM | Narrow exception handling | **Finding 9 ACCEPTED** |
| Options listener deprecation | MEDIUM | Migrate to `SchemaOptionsFlowHandlerWithReload` | **Finding 19 ACCEPTED** |
| Plaintext credentials on wire | MEDIUM | **CANT-FIX** — hardware limitation | Acknowledged |
| Credentials on disk | MEDIUM | **WONT-FIX** — standard HA, diagnostics redacted | Acknowledged |

---

## Part 10: Consolidated Action Plan

### Phase 1: Bugs & Security (implement immediately)

| # | Item | Source | Severity |
|---|------|--------|----------|
| 1 | Fix `_parse_entity_type()` — add `climate`/`fan` | Finding 7 | BUG |
| 2 | Cap `delay` at 60s + handle `ValueError` | Finding 10 | HIGH |
| 3 | Add command allowlist + configurable raw override | Finding 15 | HIGH |
| 4 | Add CSV import size/row limits | Finding 16 | MEDIUM |
| 5 | Fix `async_remove_config_entry_device` to check entities | Finding 17 | MEDIUM |
| 6 | Fix `callable` → `Callable` type annotations | Finding 8 | LOW |
| 7 | Replace `coordinator._kls_poll_addresses.add()` with public method | Finding 13 | LOW |
| 8 | Demote `_LOGGER.info` debug dumps to `_LOGGER.debug` | Finding 14 | LOW |

### Phase 2: HA Best Practice Alignment

| # | Item | Source |
|---|------|--------|
| 9 | Migrate to `entry.runtime_data` (typed ConfigEntry) | Finding 1 |
| 10 | Pass `config_entry=entry` to coordinator super() | Coordinator Issue 1 |
| 11 | Add `async_will_remove_from_hass()` symmetry to all entities | Finding 4 |
| 12 | Add `controller_id` duplicate check in config flow | Fix B |
| 13 | Add `EntityCategory.DIAGNOSTIC` to health sensors | Fix E |
| 14 | Make all timestamps timezone-aware | Coordinator Issue 3 |
| 15 | Set `PARALLEL_UPDATES = 0` in all platform files | Finding 6-QS |
| 16 | Remove forced area assignment; rely on `suggested_area` only | Finding 18 |
| 17 | Migrate `add_update_listener` → `SchemaOptionsFlowHandlerWithReload` | Finding 19 |

### Phase 3: Structural Improvement

| # | Item | Source |
|---|------|--------|
| 18 | Implement `async_migrate_entry()` for legacy format conversion | Finding 6-legacy |
| 19 | Extract shared CCO device creation helper | Finding 5 |
| 20 | Migrate CCO entities to `_attr_has_entity_name = True` | Finding 3 |
| 21 | Reduce `_async_update_data()` to lightweight metadata | Coordinator Issue 2 |
| 22 | Narrow exception handling in entity setup | Finding 9 |
| 23 | Move health sensor icons to `icons.json` | Fix F |

### Phase 4: Observability & Resilience

| # | Item | Source |
|---|------|--------|
| 24 | Add `HomeworksCCOAvailabilityMixin` (stale-KLS + transition logging) | Fix C + Fix D |
| 25 | Deduplicate `normalize_address` + add sync test | normalize_address |
| 26 | Bump `hacs.json` minimum to `2024.12.0`; add `content_in_root: false` | Finding 12 |

### Phase 5: Testing & CI (separate commit/document)

| # | Item | Source |
|---|------|--------|
| 27 | Add config flow tests | Fix A |
| 28 | Add coordinator + entity lifecycle tests | Finding 11 |
| 29 | Add CI pipeline (GitHub Actions with HACS action) | Architecture doc |
| 30 | `normalize_address` synchronization test | normalize_address |

---


---

## Deferred Items (separate documents) THAT SHOULD NOT BE CODED AT THIS TIME!

- **Testing & Code Lifecycle Plan** — full test infrastructure, CI pipeline, coverage targets
- **PyPI Publishing Plan** — when upstream `pyhomeworks` constraints are resolved
- **User command blocklist** — admin-configurable list of commands blocked even if on allowlist (Finding 15 follow-up)
- **`future_improvements.md`** — standalone `ValueError` delay parsing tracking (already handled by Finding 10's `try/except` but user wants tracked separately)

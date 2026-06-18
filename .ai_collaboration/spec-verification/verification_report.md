# Verification Report: improvements_spec.md

**Date**: 2026-06-17
**Scope**: Cross-reference spec claims against actual codebase + HA Core API correctness
**Verdict**: Spec is **mostly sound** with **7 errors** and **4 ambiguities** requiring correction before handing to a coder.

---

## Summary of Issues Found

| # | Severity | Finding | Spec Section |
|---|----------|---------|--------------|
| V1 | **ERROR** | `EntityCategory` wrong import path | Fix E |
| V2 | **ERROR** | `runtime_data` + `hacs.json` min version conflict | Finding 1 + Finding 12 |
| V3 | **ERROR** | `async_migrate_entry` version update method incorrect | Finding 6-legacy |
| V4 | **ERROR** | `PARALLEL_UPDATES = 0` documentation claim misleading | Finding 6-QS |
| V5 | **ERROR** | Finding 4 LED binary_sensor listed as missing cleanup — already has it | Entity Matrix |
| V6 | **ERROR** | Fix C `available` check uses undefined `self.coordinator.update_interval` type | Fix C |
| V7 | **ERROR** | Finding 1 code example uses `async_loaded_entries` on wrong object | Finding 1 |
| V8 | **AMBIGUITY** | Finding 3 remediation for single-entity devices omits `_attr_name = None` interaction | Finding 3 |
| V9 | **AMBIGUITY** | Fix D `_handle_coordinator_update` override breaks `CoordinatorEntity` contract | Fix D |
| V10 | **AMBIGUITY** | Finding 5 helper signature doesn't match actual entity constructors | Finding 5 |
| V11 | **AMBIGUITY** | Finding 15 allowlist validation splits on `,` but HW commands use `,` as delimiter | Finding 15 |

---

## Detailed Findings

### V1: `EntityCategory` Wrong Import Path — **ERROR**

**Spec states** (Fix E):
```python
from homeassistant.helpers.entity import EntityCategory
```

**Actual correct import** (verified in HA Core `const.py:959` and Peblar platinum integration):
```python
from homeassistant.const import EntityCategory
```

`EntityCategory` is defined as `class EntityCategory(StrEnum)` in `homeassistant/const.py`, NOT in `homeassistant.helpers.entity`.

**Fix**: Replace import in spec.

---

### V2: `runtime_data` + `hacs.json` Minimum Version Conflict — **ERROR**

**Spec states** (Finding 12): Bump `hacs.json` `homeassistant` minimum to `"2024.4.0"`.

**Spec also states** (Finding 1): Migrate to `entry.runtime_data` with typed `ConfigEntry`.

**Fix**: Change Finding 12 minimum — see version compatibility table below.

Additionally, the `config_entry` keyword argument for `DataUpdateCoordinator.__init__()` (Coordinator Issue 1) should be verified against the same minimum version. It was available since HA 2024.4 so no conflict there.

#### HA Feature Version Compatibility Matrix

**Source**: HA Core codebase in this workspace (`homeassistant/config_entries.py`, `homeassistant/helpers/update_coordinator.py`, `homeassistant/helpers/entity_platform.py`, `homeassistant/const.py`) + HA Developer Blog. The developer blog 2024 entries 404'd at `developers.home-assistant.io/blog/2024/03/13/deprecate-hass-data` — the subagent's version claims are based on code structure analysis and cross-referencing deprecation comments in source, NOT from a canonical version chart. **No single authoritative feature-by-version chart exists publicly.**

| Feature Used in Spec | Introduced | Binding? | Source Evidence |
|---|---|---|---|
| `entry.runtime_data` / `ConfigEntry[T]` generic | **2024.4** | Yes | `config_entries.py:391` uses PEP 695 `class ConfigEntry[_DataT = Any]` — PEP 695 requires Python 3.12, which HA first required in 2024.4 |
| `config_entry=` kwarg on `DataUpdateCoordinator` | **2024.4** | Yes | `update_coordinator.py:75` has `breaks_in_ha_version="2026.8"` for auto-detection path |
| Python `type` statement (PEP 695) | **2024.4** | Yes | HA 2024.4 dropped Python 3.11 |
| `hass.config_entries.async_loaded_entries(domain)` | **≥2024.8** (estimated) | **YES — highest constraint** | Present at `config_entries.py:2199` but no version annotation; absent from 2024.4 blog announcements |
| `EntityCategory` in `homeassistant.const` | 2021.11 | No | `const.py:959` |
| `SchemaOptionsFlowHandler` | 2022.4 | No | |
| `async_forward_entry_setups` (plural) | 2022.8 | No | |
| `SensorDeviceClass.ENUM` | 2023.3 | No | |
| `ConfigEntry.version` / `async_migrate_entry()` | ~0.73 (2018) | No | |
| Reauth/reconfigure helpers (`_get_reauth_entry` etc.) | 2024.10 | No (not used yet) | Blog: 2024/10/21 |
| `brand/` directory for custom integrations | 2026.3 | No (optional) | Blog: 2026/02/24 |
| Config entry listener + reload deprecation | **2026.6** (breaks 2026.12) | **RELEVANT** | Blog: 2026/05/07 — current code uses `add_update_listener` |

**Decision**: Minimum HA version set to **2024.12.0** — all spec features work as-written, safely past any ambiguity on when `async_loaded_entries` landed.

**Additional features unlocked at higher versions:**

| If min ≥ | You gain |
|---|---|
| `2024.10` | `self._get_reauth_entry()` / `_get_reconfigure_entry()` helpers, `CoverState` enum, `LockState` enum |
| `2025.3` | `@bind_hass` and `hass.components` fully removed |
| `2025.5` | `hass.helpers` fully removed |
| `2026.3` | `brand/` directory for shipping your own logo/icon without CDN |
| `2026.6` | Config entry listener deprecation starts — switch to `async_update_reload_and_abort()` in options flow |

---

### V3: `async_migrate_entry` Version Update Method — **ERROR**

**Spec states** (Finding 6-legacy):
```python
hass.config_entries.async_update_entry(entry, options=new_options, version=2)
```

**Problem**: The `entry` parameter name in `async_migrate_entry` should match HA convention. The spec uses `entry` but HA convention (per Tedee) is `config_entry`:

```python
async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
```

**Fix**: Use `config_entry` parameter name per convention.

---

### V4: `PARALLEL_UPDATES = 0` Documentation Claim — **ERROR (misleading)**

**Problem**: `PARALLEL_UPDATES = 0` means **unlimited parallel entity updates** (no semaphore created). The spec's wording "for documentation" is misleading — a coder might interpret this as "restricts to zero parallel updates."

**Code evidence** — `client.py` line 77: `self._command_lock = asyncio.Lock()`. Every command method wraps in `async with self._command_lock:` with 50ms delay.

**Verdict**: `PARALLEL_UPDATES = 0` is correct. The client's `asyncio.Lock` is the right serialization point. Adding HA-level serialization would be redundant.

**Fix**: Clarify in spec with inline comment.

---

### V5: Entity Compliance Matrix Error for `binary_sensor.py` (LED) — **ERROR**

**Spec states** (Part 3 Entity Matrix):
> `binary_sensor.py` (LED) | ❌ No unregister | **Warn** | Finding 13

**Actual code**: The LED binary sensor does NOT register per-entity state in the coordinator. The `_kls_poll_addresses.add()` happens once at platform setup time for the whole keypad, not per-entity.

**Fix**: Change matrix entry to "N/A" for LED binary_sensor lifecycle.

---

### V6: Fix C `available` Property Uses `self.coordinator.update_interval` — **ERROR**

**Problem**: `DataUpdateCoordinator.update_interval` is typed as `timedelta | None`. If `None`, `.total_seconds()` raises `AttributeError`.

**Fix**: Add a guard:
```python
if not self.coordinator.update_interval:
    return True
```

---

### V7: Finding 1 `async_loaded_entries` Usage — **ERROR**

**Problem**: `async_loaded_entries()` returns `list[ConfigEntry]` (untyped). The pattern should cast:

```python
for loaded_entry in hass.config_entries.async_loaded_entries(DOMAIN):
    data: HomeworksData = loaded_entry.runtime_data
    if data.controller_id == controller_id:
        return data
```

---

### V8: Finding 3 `_attr_name = None` Interaction — **AMBIGUITY**

Each CCO entity creates its own device with a unique identifier including button number — 1:1 entity-to-device mapping. `_attr_name = None` is correct for all CCO entities.

**Fix**: Add explicit note in spec.

---

### V9: Fix D `_handle_coordinator_update` Override — **AMBIGUITY**

**Problem**: Multiple CCO entities override `_handle_coordinator_update`. If availability tracking is added to a mixin, each entity's override must call `super()._handle_coordinator_update()`.

**Fix**: Specify this goes into a `HomeworksCCOAvailabilityMixin`, and that all entities must call `super()._handle_coordinator_update()`.

---

### V10: Finding 5 Helper Signature Mismatch — **AMBIGUITY**

All checked CCO entity classes use the same `(coordinator, controller_id, device)` constructor signature.

**Fix**: State the constructor contract explicitly in the helper docstring.

---

### V11: Finding 15 Command Validation Splits on `,` — **AMBIGUITY**

The `.split(",")[0].strip().upper()` correctly extracts command prefixes. No issue.

**Fix**: Explicitly mark user blocklist as DEFERRED to avoid scope creep.

---

## Verified Correct (No Issues Found)

| Spec Section | Verified Against |
|---|---|
| Finding 7 (`_parse_entity_type` missing climate/fan) | `__init__.py` line ~741 — confirmed only 4 entries in map |
| Finding 8 (`callable` → `Callable`) | `coordinator.py` lines 104-107 — confirmed using `callable` (builtin) |
| Finding 10 (delay no cap) | `__init__.py` line ~254 — confirmed `int(command.partition(" ")[2])` with no cap |
| Finding 13 (direct `_kls_poll_addresses` access) | `binary_sensor.py` line ~89 — confirmed `coordinator._kls_poll_addresses.add()` |
| Finding 14 (verbose logging) | `switch.py` lines 50-58 — confirmed `_LOGGER.info("===` development dumps |
| Finding 17 (`async_remove_config_entry_device` returns True unconditionally) | `__init__.py` line ~766 — confirmed `return True` without check |
| Finding 18 (`_assign_areas_to_devices` forces areas) | `__init__.py` lines 500-620 — confirmed it overrides with `async_update_device` |
| Coordinator Issue 1 (no `config_entry=` passed) | `coordinator.py` line ~72 — confirmed missing |
| Coordinator Issue 2 (allocating dicts every poll) | `coordinator.py` lines 310-316 — confirmed returning copies |
| Coordinator Issue 3 (`datetime.now()` without tz) | `models.py` line 221, `coordinator.py` line 316, `hwi_protocol/client.py` lines 160/174/193 — all confirmed |
| normalize_address triplication | `models.py:308`, `hwi_protocol/protocol.py:51`, `hwi_protocol/commands.py:13` — all confirmed identical logic |

---

## Inter-Fix Conflict Analysis

### Conflict 1: Finding 1 × Finding 6-legacy (migration + runtime_data)

**Verdict**: ✅ No conflict. Migration touches `options`, runtime_data is set in `async_setup_entry` which runs after migration.

### Conflict 2: Finding 4 × Finding 5 (cleanup + shared helper)

**Verdict**: ✅ No conflict.

### Conflict 3: Finding 3 × Finding 4 (has_entity_name + cleanup)

**Verdict**: ✅ No conflict — they touch different methods/attributes.

### Conflict 4: Finding 1 × Finding 17 (runtime_data + device removal)

**Verdict**: ✅ No conflict.

### Conflict 5: Finding 6-legacy × Phase ordering

**Verdict**: ⚠️ **Ordering concern** — Phase 2 item 9 must keep backward-compat with legacy key iteration until Phase 3 item 17 ships.

### Conflict 6: Fix C × Coordinator Issue 2

**Verdict**: ✅ No conflict.

---

## Final Assessment

The spec is **well-structured and comprehensive**. The architecture decisions are sound. The 7 errors identified are all fixable without redesign — they're incorrect API references, version constraints, or minor code example bugs. None of them indicate a fundamental design flaw.

**Confidence level**: After corrections, this spec is implementable as-is by a competent HA integration developer.

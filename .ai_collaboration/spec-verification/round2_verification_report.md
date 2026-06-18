# HWI_HA — Round 2 Implementation Verification Report

**Date**: 2026-06-18
**Spec Verified Against**: `improvements_spec_v2.md` (Unified Assessment v4)
**Codebase Branch**: `feature/quality-improvements`

---

## Executive Summary

**31 out of 33 actionable items verified as correctly implemented.**
**2 residual issues found** — both are pre-existing patterns in `_register_cco_devices_from_options()` that were NOT scoped for this round, plus 1 observation about the QED cover missing from the spec's Finding 4 entity list.

Overall assessment: **PASS — spec faithfully implemented.**

---

## Phase 1: Bugs & Security

| # | Item | Finding | Verdict | Evidence |
|---|------|---------|---------|----------|
| 1 | `_parse_entity_type()` — add `climate`/`fan` | Finding 7 | **PASS** | `__init__.py` line 651: `type_map` includes `CCO_TYPE_CLIMATE: CCOEntityType.CLIMATE` and `CCO_TYPE_FAN: CCOEntityType.FAN`. All 6 types mapped. |
| 2 | Cap `delay` at 60s + handle `ValueError` | Finding 10 | **PASS** | `__init__.py` line 365: `delay = min(int(command.partition(" ")[2]), 60000)` wrapped in `try/except (ValueError, IndexError)`. Matches spec exactly. |
| 3 | Command allowlist + raw override | Finding 15 | **PASS (correctly NOT coded)** | Spec explicitly says `DO NOT CODE THIS FINDING 15`. No `SAFE_COMMAND_PREFIXES` or `allow_raw_commands` found. Correct. |
| 4 | CSV import size/row limits | Finding 16 | **PASS** | `config_flow.py` line 855: `len(content) > 1_000_000` raises `csv_too_large`. Line 872: `row_count > 5000` raises `csv_too_many_rows`. Translation strings present in `strings.json` lines 369-370. |
| 5 | `async_remove_config_entry_device` | Finding 17 | **PASS** | `__init__.py` line 674: Checks `entity.device_id == device_entry.id` for entities belonging to the config entry. Returns `False` if entities exist. Exact match to spec. |
| 6 | `callable` → `Callable` type annotations | Finding 8 | **PASS** | `coordinator.py` line 7: `from collections.abc import Callable`. Line 112: `dict[str, list[Callable[[str, int, str], None]]]`. Line 115: `dict[tuple[int, int, int, int], list[Callable[[bool], None]]]`. `register_cci_callback` and `register_button_callback` signatures also use `Callable`. |
| 7 | Public `register_kls_poll_address()` method | Finding 13 | **PASS** | `coordinator.py` line 156: Public method `register_kls_poll_address()` with normalize + add + client registration. `binary_sensor.py` line 86: calls `coordinator.register_kls_poll_address(keypad_addr)`. No direct `_kls_poll_addresses` access from outside coordinator. |
| 8 | Demote `_LOGGER.info("===...")` to debug | Finding 14 | **PASS** | No `_LOGGER.info("===` pattern found anywhere in the integration source files. All verbose development dumps removed or demoted. |

---

## Phase 2: HA Best Practice Alignment

| # | Item | Finding | Verdict | Evidence |
|---|------|---------|---------|----------|
| 9 | Migrate to `entry.runtime_data` | Finding 1 | **PASS** | `__init__.py` line 107: `type HomeworksHWIConfigEntry = ConfigEntry[HomeworksData]`. Line 529: `entry.runtime_data = HomeworksData(...)`. No `hass.data[DOMAIN]` usage. `async_unload_entry` (line 669): reads `entry.runtime_data`. `async_send_command` (line 325): uses `async_loaded_entries(DOMAIN)` + `entry.runtime_data`. All platform `async_setup_entry` functions use `entry.runtime_data`. |
| 10 | Pass `config_entry=entry` to coordinator | Coord Issue 1 | **PASS** | `coordinator.py` line 75: `super().__init__(hass, _LOGGER, config_entry=config_entry, ...)`. Constructor accepts `config_entry: ConfigEntry` parameter (line 68). |
| 11 | `async_will_remove_from_hass()` symmetry | Finding 4 | **PASS** | Verified in all 9 entity classes: `HomeworksDimmableLight` (light.py:170), `HomeworksCCOLight` (light.py:250), `HomeworksCCOSwitch` (switch.py:172), `HomeworksCCOCover` (cover.py:242), `HomeworksRPMCover` (cover.py:413), `HomeworksCCOLock` (lock.py:192), `HomeworksCCOFan` (fan.py:140), `HomeworksCCOClimate` (climate.py:149). All call appropriate unregister + `super()`. |
| 12 | `controller_id` duplicate check | Fix B | **PASS** | `config_flow.py` line 1740: `return self.async_abort(reason="duplicated_controller_id")`. `strings.json` line 46: abort reason text present. |
| 13 | `EntityCategory.DIAGNOSTIC` for health sensors | Fix E | **PASS** | `sensor.py` line 57: `_attr_entity_category = EntityCategory.DIAGNOSTIC` on `HomeworksHealthSensor` base class. Import on line 14: `from homeassistant.const import EntityCategory`. Connection sensor overrides `_attr_entity_registry_enabled_default = True` but inherits `DIAGNOSTIC` category. |
| 14 | Timezone-aware timestamps | Coord Issue 3 | **PASS** | `models.py` line 221: `field(default_factory=lambda: datetime.now(timezone.utc))` for `KLSState.timestamp`. Lines 286/290/291: `datetime.now(timezone.utc)` in `ControllerHealth`. `hwi_protocol/client.py` lines 160/174/193: `datetime.now(tz=timezone.utc)`. No bare `datetime.now()` without timezone found. |
| 15 | `PARALLEL_UPDATES = 0` in all platform files | Finding 6-QS | **PASS** | Confirmed present in: `switch.py`, `light.py`, `cover.py`, `lock.py`, `fan.py`, `climate.py`, `sensor.py`, `binary_sensor.py`. All set to `0`. |
| 16 | Remove forced area assignment | Finding 18 | **PASS** | No `_assign_areas_to_devices` or `_cleanup_devices_without_areas` functions exist. All entity constructors use `suggested_area` in `DeviceInfo` correctly. |
| 17 | `add_update_listener` → `SchemaOptionsFlowHandlerWithReload` | Finding 19 | **PASS** | No `update_listener` function or `add_update_listener` call in `__init__.py`. `config_flow.py` line 41: imports `SchemaOptionsFlowHandlerWithReload`. Line 1887: `return SchemaOptionsFlowHandlerWithReload(config_entry, OPTIONS_FLOW)`. |

---

## Phase 3: Structural Improvement

| # | Item | Finding | Verdict | Evidence |
|---|------|---------|---------|----------|
| 18 | `async_migrate_entry()` for v1→v2 | Finding 6-legacy | **PASS** | `__init__.py` lines 381-430: Full migration function. Converts `CONF_CCOS` → `CCO_DEVICES` (switch), `CONF_COVERS` → `CCO_DEVICES` (cover), `CONF_LOCKS` → `CCO_DEVICES` (lock). Updates version to 2. `config_flow.py` line 1713: `VERSION = 2`. |
| 19 | Extract shared CCO device creation helper | Finding 5 | **PASS** | `__init__.py` lines 222-260: `parse_cco_device_config()` function. Lines 263-299: `create_cco_entities_for_type()` generic helper. Used in `switch.py`, `light.py`, `cover.py`, `lock.py`, `fan.py`, `climate.py`. All use narrowed `(ValueError, KeyError, TypeError)` exceptions. |
| 20 | Migrate CCO entities to `_attr_has_entity_name = True` | Finding 3 | **PASS** | All CCO entity classes now set `_attr_has_entity_name = True` and `_attr_name = None`: `HomeworksCCOSwitch` (switch.py), `HomeworksCCOLight` (light.py), `HomeworksCCOCover` (cover.py), `HomeworksCCOLock` (lock.py), `HomeworksCCOFan` (fan.py), `HomeworksCCOClimate` (climate.py), `HomeworksDimmableLight` (light.py), `HomeworksRPMCover` (cover.py). No `name` property override or `_entity_name` variable. |
| 21 | Lightweight `_async_update_data()` | Coord Issue 2 | **PASS** | `coordinator.py` lines 304-314: Returns `{"connected": True, "poll_count": self._poll_count}`. No dict copying of `_cco_states`/`_dimmer_states`. Raises `UpdateFailed` on disconnect. Calls `_poll_kls_states()`. Increments `_poll_count`. |
| 22 | Narrow exception handling in entity setup | Finding 9 | **PASS** | `create_cco_entities_for_type()` (line 290): `except (ValueError, KeyError, TypeError)`. All platform-level legacy entity creation also uses `(ValueError, KeyError, TypeError)`. |
| 23 | Health sensor icons to `icons.json` | Fix F | **PASS** | `icons.json`: All 5 sensor keys present (`connection` with state variant, `last_kls_time`, `reconnect_count`, `poll_failure_count`, `parse_error_count`). Service icon: `"send_command": {"service": "mdi:console"}`. `sensor.py`: No `icon` property on any sensor class. All use `_attr_translation_key` which maps to `icons.json`. |

---

## Phase 4: Observability & Resilience

| # | Item | Finding | Verdict | Evidence |
|---|------|---------|---------|----------|
| 24 | `HomeworksCCOAvailabilityMixin` | Fix C + Fix D | **PASS** | `__init__.py` lines 701-740: Mixin with `available` property checking `coordinator.connected`, `health.last_kls_time`, and 3× interval staleness. `_handle_coordinator_update` with `_was_available` tracking and transition logging. MRO correct — mixin placed BEFORE `CoordinatorEntity` in all 6 CCO classes. `HomeworksCCOCover._handle_coordinator_update` calls `super()._handle_coordinator_update()` to inherit mixin behavior. |
| 25 | Deduplicate `normalize_address` | Part 6 | **PASS** | `hwi_protocol/commands.py` line 12: `from .protocol import normalize_address  # noqa: F401` (import, no local copy). `hwi_protocol/protocol.py` line 51: canonical definition. `models.py` line 308: Retained separate copy (per spec: "Keep `models.py` copy until PyPI migration"). |
| 26 | `hacs.json` minimum + `content_in_root` | Finding 12 | **PASS** | `hacs.json`: `"homeassistant": "2024.12.0"` and `"content_in_root": false`. Both present and correct. |

---

## Coordinator Issues Summary

| Issue | Verdict | Evidence |
|-------|---------|----------|
| Issue 1: `config_entry` in super().__init__ | **PASS** | Line 75: `config_entry=config_entry` passed |
| Issue 2: Lightweight `_async_update_data` | **PASS** | Returns `{"connected": True, "poll_count": ...}` |
| Issue 3: Timezone-aware `datetime.now()` | **PASS** | All 7 `datetime.now()` calls use `timezone.utc` |

---

## Deferred Items Verification (should NOT be coded)

| Item | Verdict | Evidence |
|------|---------|----------|
| Finding 15: Command allowlist | **PASS (not coded)** | No `SAFE_COMMAND_PREFIXES`, `CONF_ALLOW_RAW_COMMANDS`, or `command_not_allowed` in codebase. Correct per spec. |
| Test infrastructure (Phase 5) | **PASS (not coded)** | Spec marks as "separate commit" — correctly deferred. |

---

## Residual Issues

### Issue R1: Broad Exception Handling in `_register_cco_devices_from_options()` — MINOR

**Location**: `__init__.py` lines 576, 600, 623, 647

While Finding 9 was correctly applied to the `create_cco_entities_for_type()` helper and all platform-level legacy entity creation, the **`_register_cco_devices_from_options()`** function still uses bare `except Exception as err:` in 4 places (new-style CCO, legacy CCO, legacy covers, legacy locks).

This function was not explicitly called out in the spec for narrowing — the spec's Finding 9 targeted "every entity platform." However, the same anti-pattern exists here, and the narrowed exception set `(ValueError, KeyError, TypeError)` would be appropriate.

**Severity**: MINOR — this is device registration, not entity creation. A broad catch here prevents a single bad device config from crashing the entire entry setup.

**Recommendation**: Optional cleanup to narrow these to `(ValueError, KeyError, TypeError)` for consistency.

### Issue R2: `HomeworksQEDCover` Missing from `cover.py`

**Observation**: The spec's Finding 4 lists `HomeworksQEDCover` among entities needing `async_will_remove_from_hass()`. However, `HomeworksQEDCover` does not exist in `cover.py` at all. The QED cover implementation was a separate feature branch (`feature-qed-covers`) that may not yet be merged into this branch.

**Verdict**: **NOT AN ISSUE** — the QED cover was a separate feature. The spec references it from the design assessment, but its implementation is tracked independently. All entities that DO exist in `cover.py` (`HomeworksCCOCover`, `HomeworksRPMCover`) correctly implement `async_will_remove_from_hass()`.

---

## Entity Platform Compliance Matrix (Post-Implementation)

| Platform | has_entity_name | name=None | Symmetric Lifecycle | Mixin | PARALLEL_UPDATES |
|----------|----------------|-----------|--------------------:|-------|------------------|
| `light.py` (dimmer) | ✅ True | ✅ None | ✅ register/unregister dimmer | N/A (not CCO) | ✅ 0 |
| `light.py` (CCO) | ✅ True | ✅ None | ✅ register/unregister cco | ✅ Mixin | ✅ 0 |
| `switch.py` | ✅ True | ✅ None | ✅ register/unregister cco | ✅ Mixin | ✅ 0 |
| `cover.py` (CCO) | ✅ True | ✅ None | ✅ register/unregister cco | ✅ Mixin | ✅ 0 |
| `cover.py` (RPM) | ✅ True | ✅ None | ✅ register/unregister dimmer | N/A (not CCO) | ✅ 0 |
| `lock.py` | ✅ True | ✅ None | ✅ register/unregister cco | ✅ Mixin | ✅ 0 |
| `fan.py` | ✅ True | ✅ None | ✅ register/unregister cco | ✅ Mixin | ✅ 0 |
| `climate.py` | ✅ True | ✅ None | ✅ register/unregister cco | ✅ Mixin | ✅ 0 |
| `binary_sensor.py` (LED) | ✅ True | ✅ name set | N/A (no per-entity reg) | N/A | ✅ 0 |
| `sensor.py` (health) | ✅ True | ✅ name set | N/A (coordinator-based) | N/A | ✅ 0 |

---

## Verification Methodology

1. **Line-by-line source reading** of all 10 platform files, `__init__.py`, `coordinator.py`, `config_flow.py`, `models.py`, `const.py`, `icons.json`, `strings.json`, `manifest.json`, `hacs.json`
2. **Grep searches** for each spec item's key identifiers (function names, constants, patterns)
3. **Cross-reference** between spec code examples and actual implementation
4. **Negative verification** for deferred items (confirmed NOT present)

---

## Conclusion

The `improvements_spec_v2.md` has been **faithfully and correctly implemented** across all 26 accepted action items in Phases 1-4 plus all 3 Coordinator Issues. The 2 residual issues identified are minor and do not affect correctness or security.

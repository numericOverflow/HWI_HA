# PR: HA Quality Scale Alignment

**Branch**: `feature/ha-quality-scale`  
**Base**: `fix/bugs-security-hardening`  
**Type**: Refactor / Feature

## Summary

Aligns the integration with Home Assistant Integration Quality Scale requirements (Bronze through Gold). Modernizes entity patterns, coordinator usage, and config flow handling to match current HA Core best practices.

## Changes

### Commit 1: refactor: migrate to entry.runtime_data with typed ConfigEntry (Finding 1)

- Define `HomeworksHWIConfigEntry = ConfigEntry[HomeworksData]` type alias
- Replace `hass.data[DOMAIN][entry.entry_id]` → `entry.runtime_data`
- Update `async_send_command` to use `hass.config_entries.async_loaded_entries()`
- Remove unused `ConfigEntry` imports from all platform files

**Files**: All platform files, `__init__.py`, `diagnostics.py`

### Commit 2: refactor: coordinator improvements (Coordinator Issues 1 & 2)

- Pass `config_entry=entry` to `DataUpdateCoordinator.__init__()`
- Simplify `_async_update_data()` to return lightweight metadata only

**Files**: `coordinator.py`, `__init__.py`

### Commit 3: feat: entity lifecycle symmetry and PARALLEL_UPDATES (Findings 4, 6-QS)

- Add `async_will_remove_from_hass()` to all 9 entity classes
- Set `PARALLEL_UPDATES = 0` on all 9 platform files

**Files**: All platform files

### Commit 4: refactor: HA quality scale compliance (Findings 18, 19, Fix B, Fix E)

- Add `EntityCategory.DIAGNOSTIC` to health sensors
- Remove `_assign_areas_to_devices()` and `_cleanup_devices_without_areas()`
- Migrate to `SchemaOptionsFlowHandlerWithReload` (removes deprecated `add_update_listener`)
- Add `controller_id` duplicate check in config flow

**Files**: `__init__.py`, `config_flow.py`, `sensor.py`

### Commit 5: refactor: migrate all entities to has_entity_name = True (Finding 3)

- All entity classes: `_attr_has_entity_name = True`, `_attr_name = None`
- Remove `name` property overrides and `_entity_name` instance variables
- 1:1 entity-to-device mapping: entity inherits device name

**Files**: `light.py`, `switch.py`, `cover.py`, `lock.py`, `fan.py`, `climate.py`

### Commit 6: refactor: icons.json, normalize_address dedup, HACS manifest (Findings 12, 25, Fix F)

- Move sensor icons to `icons.json` with state-dependent icon support
- Deduplicate `normalize_address` (commands.py imports from protocol.py)
- Bump HACS manifest minimum to `2024.12.0`, add `content_in_root: false`

**Files**: `icons.json`, `sensor.py`, `hwi_protocol/commands.py`, `hacs.json`

## Migration Impact

### Breaking Changes

- **Entity names**: Entities using `has_entity_name=True` with `name=None` will adopt their device name. For existing installations, HA preserves the entity registry name — no user-visible change unless entities are re-created.
- **Area assignment**: Areas are no longer force-applied on reload. Existing area assignments are preserved. New devices get `suggested_area` on first creation only.

### Non-Breaking

- `runtime_data` is transparent to users
- `PARALLEL_UPDATES = 0` matches existing behavior (client lock handles serialization)
- `SchemaOptionsFlowHandlerWithReload` provides identical reload behavior
- HACS manifest bump only affects minimum HA version for new installs

## Quality Scale Coverage

| Rule | Status |
|------|--------|
| `runtime-data` | ✅ Done |
| `has-entity-name` | ✅ Done (all entities) |
| `entity-category` | ✅ Done (DIAGNOSTIC for health sensors) |
| `icon-translations` | ✅ Done (icons.json) |
| `parallel-updates` | ✅ Done (= 0 on all platforms) |
| `config-entry-unloading` | ✅ Already done + lifecycle symmetry added |

## Checklist

- [x] No data loss on upgrade
- [x] Entity unique IDs unchanged
- [x] Device identifiers unchanged
- [x] Backward-compatible with existing config entries (VERSION stays at 1)
- [x] HACS minimum version bumped
- [ ] Unit tests (deferred to testing commit)

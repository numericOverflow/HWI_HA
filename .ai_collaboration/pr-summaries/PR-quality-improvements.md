# PR: Quality Improvements & HA Best Practice Alignment

**Branch:** `feature/quality-improvements`  
**Base:** `main`  
**Commits:** 4

---

## Summary

Comprehensive quality, security, and HA API compliance pass across the entire integration. Addresses all ACCEPTED findings from the unified assessment (improvements_spec_v2.md), excluding Finding 15 (raw command allowlist — explicitly deferred) and Phase 5 testing items.

---

## Commit Breakdown

### 1. `fix: bugs and security hardening (Phase 1)`

| Finding | Change |
|---------|--------|
| 7 | Fix `_parse_entity_type()` — add missing `climate`/`fan` mappings |
| 10 | Cap `send_command` delay at 60s, handle `ValueError`/`IndexError` |
| 16 | CSV import: 1MB size limit + 5000 row limit |
| 17 | `async_remove_config_entry_device` — refuse removal if device has entities |
| 8 | Fix `callable` → `Callable` type annotations in coordinator |
| 13 | Public `register_kls_poll_address()` API (removes private attr access) |
| 14 | Demote verbose `_LOGGER.info("=== ...")` to `_LOGGER.debug()` |

### 2. `refactor: HA best practice alignment (Phase 2)`

| Finding | Change |
|---------|--------|
| 1 | Migrate to `entry.runtime_data` with typed `HomeworksHWIConfigEntry` |
| Coord-1 | Pass `config_entry=` to `DataUpdateCoordinator.__init__()` |
| 4 | Add `async_will_remove_from_hass()` symmetric cleanup to all entities |
| Fix B | Add `controller_id` duplicate check in config flow |
| Fix E | `EntityCategory.DIAGNOSTIC` on health sensors |
| Coord-3 | Fix timezone-aware timestamps (`KLSState`, coordinator) |
| 6-QS | Set `PARALLEL_UPDATES = 0` in all platform files |
| 18 | Remove forced area assignment; rely on `suggested_area` only |
| 19 | `SchemaOptionsFlowHandlerWithReload` (removes deprecated listener) |
| Coord-2 | Lightweight `_async_update_data()` (no dict copying) |
| 12 | Bump `hacs.json` minimum to `2024.12.0`, add `content_in_root` |

### 3. `refactor: structural improvements (Phase 3)`

| Finding | Change |
|---------|--------|
| 6-legacy | `async_migrate_entry()` — v1→v2 conversion (CCOS/COVERS/LOCKS → CCO_DEVICES) |
| — | Bump config flow `VERSION = 2` |
| 3 | Migrate all CCO entities to `_attr_has_entity_name = True` / `_attr_name = None` |
| 9 | Narrow exception handling to `(ValueError, KeyError, TypeError)` |
| Fix F | Health sensor icons → `icons.json` with `_attr_translation_key` |
| 25 | Deduplicate `normalize_address` in `hwi_protocol/commands.py` |

### 4. `feat: add CCO availability mixin with stale-KLS detection (Phase 4)`

| Finding | Change |
|---------|--------|
| Fix C | `HomeworksCCOAvailabilityMixin` — marks entities unavailable if KLS data > 3× poll interval |
| Fix D | Availability transition logging (warning on unavailable, info on recovery) |
| — | Applied to all CCO entity classes via MRO-correct mixin position |

---

## Breaking Changes

- **Config entry version bumped to 2.** Existing v1 entries auto-migrate via `async_migrate_entry()`. No user action required.
- **Entity naming.** All CCO entities now use `_attr_has_entity_name = True` with `_attr_name = None`. Entity IDs may change if HA re-registers them (unique_id is unchanged, so state history is preserved).
- **Area assignment.** Forced area overrides removed. Areas now only set on first device creation via `suggested_area`. Users who manually moved devices to different areas will no longer have them overridden on reload.

## Not Included (Deferred)

- Finding 15: Command allowlist + raw command toggle (per user instruction: DO NOT CODE)
- Phase 5: Config flow tests, coordinator lifecycle tests, CI pipeline
- Finding 5: Shared CCO entity creation helper (deferred to reduce PR size)

## Testing Checklist

- [ ] Verify fresh install creates entities correctly
- [ ] Verify existing v1 config migrates to v2 (check legacy CCOS/COVERS/LOCKS)
- [ ] Verify CCO switches, lights, covers, locks, fans, climate all respond
- [ ] Verify stale-KLS detection marks entities unavailable after 30s (3×10s)
- [ ] Verify entity removal triggers proper coordinator unregistration
- [ ] Verify CSV import rejects >1MB and >5000 rows
- [ ] Verify device removal is blocked when entities exist
- [ ] Verify options flow triggers reload without deprecated listener warning

# PR: Bug Fixes & Security Hardening

**Branch**: `fix/bugs-security-hardening`  
**Base**: `feature-qed-covers`  
**Type**: Bug fix / Security

## Summary

Targeted fixes for bugs, security vulnerabilities, type safety issues, and code quality problems identified in the quality assessment. All changes are independent and low-risk.

## Changes

### Commit 1: fix: type mapping bug, type annotations, and exception handling

| Finding | Issue | Fix |
|---------|-------|-----|
| 7 | `_parse_entity_type()` missing climate/fan mappings | Add `CCO_TYPE_CLIMATE` and `CCO_TYPE_FAN` to type map |
| 8 | `callable` (builtin function) used as type hint | Replace with `collections.abc.Callable` |
| 9 | `except Exception` catches unrelated bugs silently | Narrow to `except (ValueError, KeyError, TypeError)` |

**Files**: `__init__.py`, `coordinator.py`, `switch.py`, `light.py`, `cover.py`, `lock.py`, `fan.py`, `climate.py`, `binary_sensor.py`

### Commit 2: fix: security hardening for send_command delay, CSV import, and device removal

| Finding | Severity | Issue | Fix |
|---------|----------|-------|-----|
| 10 | HIGH (CVSS 6.5) | `delay 2147483647` blocks event loop ~24 days | Cap at 60s, handle ValueError |
| 16 | MEDIUM (CVSS 4.3) | No CSV upload size limits (DoS vector) | 1MB size + 5000 row limits |
| 17 | MEDIUM (CVSS 3.5) | Device removal unconditionally allowed | Check for active entities first |

**Files**: `__init__.py`, `const.py`, `config_flow.py`, `strings.json`

### Commit 3: fix: code quality - public KLS registration, logging, timezone-aware datetime

| Finding | Issue | Fix |
|---------|-------|-----|
| 13 | Direct access to `coordinator._kls_poll_addresses` | Add `register_kls_poll_address()` public method |
| 14 | `_LOGGER.info("=== ...")` development dumps in production | Demote to `_LOGGER.debug()` |
| Coord-3 | `datetime.now()` without timezone | Use `datetime.now(tz=timezone.utc)` everywhere |

**Files**: `coordinator.py`, `binary_sensor.py`, `switch.py`, `config_flow.py`, `models.py`, `hwi_protocol/client.py`, `hwi_protocol/protocol.py`, `hwi_protocol/messages.py`

## Testing Notes

- All changes are backward-compatible
- No config entry migration required
- No breaking changes to entity unique IDs or device identifiers
- CSV limits: SchemaFlowError displayed to user in options flow
- Delay cap: silently applied (existing behavior preserved for valid delays)

## Checklist

- [x] No breaking changes
- [x] Translation strings added for new error messages
- [x] Security fixes verified against OWASP guidelines
- [ ] Unit tests (deferred to testing commit)

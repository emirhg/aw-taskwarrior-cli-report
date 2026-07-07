# Project Filter Resolution (Task ID / UUID)

**Status:** ✅ Complete  
**Tests:** 18 new tests, all passing  
**Feature:** `--project` now accepts task IDs and UUIDs  

## Overview

The `--project` flag now accepts three types of values:

1. **Plain patterns** (existing) — substring match against project names
   ```bash
   tw-report --project "Climb" :month --timesheet
   ```

2. **Integer task IDs** (new) — resolves task ID to its project, then filters
   ```bash
   tw-report --project 48 :month --timesheet
   ```

3. **UUID strings** (new) — resolves task UUID to its project, then filters
   ```bash
   tw-report --project 4afdb198-adc5-4350-bb62-83cbe18be304 :month --timesheet
   ```

## Key Difference: `--project ID` vs `--task-id ID`

| Aspect | `--task-id 48` | `--project 48` |
|--------|---|---|
| **Resolves to** | Task 48's UUID | Task 48's project name |
| **Filters by** | UUID (one specific task) | Project name (all tasks in that project) |
| **Activity shown** | Only task 48's events | All events for the project |
| **Use case** | Detailed view of one task | Overview of a project |

**Example:**
```bash
# Show ONLY task 48's activity (likely smaller time total)
tw-report --task-id 48 :month --timesheet

# Show activity for task 48's entire PROJECT (larger time total, includes all other tasks)
tw-report --project 48 :month --timesheet
```

## Detection Rules (in order)

Value is classified by this sequence:

1. **All digits?** → Treat as TaskWarrior integer ID
   - Example: `48`, `123`, `999`
   - Resolves via `task <id> export`

2. **Valid UUID format?** → Treat as TaskWarrior UUID
   - Example: `4afdb198-adc5-4350-bb62-83cbe18be304`
   - Must be full 36-char UUID (case-insensitive)
   - Partial UUIDs like `4afdb198` are NOT auto-detected
   - Resolves via `task <uuid> export`

3. **Otherwise** → Treat as plain substring pattern
   - Example: `Climb`, `Anarc`, `Invest`
   - Matched case-insensitively against event project fields
   - Unchanged from historical behavior

## Implementation Details

### Resolution Point
Early in `main.py` (lines 89-101), **before** `EventFilter` construction:
- Every element of `args.project` is checked independently
- Identifier-shaped values → resolved to project name
- Pattern-shaped values → left unchanged
- Single resolution point ensures all downstream code sees resolved names

### New Functions

**`core/task_uuid_filtering.py`**
- `_export_task(identifier)` — Shared subprocess wrapper for `task export`
  - Works with both int IDs and UUID strings
  - Returns full task dict or None
  - Used by both `get_task_uuid()` and `get_task_project()`

- `get_task_project(identifier)` — Extract project field from a task
  - Returns project name or None (if not found or no project)
  - Gracefully handles all error cases

**`core/project_filtering.py`**
- `_is_uuid_like(value)` — Detect if a string is a valid UUID
  - Uses `uuid.UUID()` parser (stdlib)
  - Case-insensitive
  - Returns True only for full 36-char UUIDs

- `resolve_project_filter_value(value)` — Main resolution entry point
  - Returns `(resolved_value, error_message)` tuple
  - Handles: ID resolution, UUID resolution, plain patterns
  - Error cases:
    - Task not found → `(None, "Task {id} has no project assigned")`
    - No project field → `(None, "Task {id} has no project assigned")`

### Error Handling

When resolution fails, `main.py` exits with code 1:

```bash
$ tw-report --project 999999 :month
Error: Task 999999 has no project assigned
```

Same pattern as `--task-id`:
```bash
$ tw-report --task-id 999999 :month
Error: Task 999999 not found
```

## Advantages

1. **Convenience** — Type `--project 48` instead of looking up the project name
2. **Consistency** — Mirrors `--task-id` pattern
3. **Backward compatible** — Plain patterns work exactly as before
4. **Performance** — Still benefits from project-filter window bucket skipping
5. **Flexible** — Mix IDs, UUIDs, and patterns in one command:
   ```bash
   tw-report --project 48 --project "Climb" --project 550e8400... :month --timesheet
   ```

## Testing

**18 new tests** covering:

1. **`TestGetTaskProject`** (5 tests)
   - Valid ID/UUID resolution
   - Invalid ID handling
   - Empty/missing project fields

2. **`TestIsUuidLike`** (6 tests)
   - Valid/invalid UUID format detection
   - Case insensitivity
   - Partial UUID rejection
   - Numeric string rejection

3. **`TestResolveProjectFilterValue`** (7 tests)
   - Integer ID → project resolution
   - UUID → project resolution
   - Plain pattern pass-through
   - Error conditions

**All existing tests still passing:** 47/47 ✅

## CLI Help Text

```
--project PATTERN
  Filter: show only entries whose project matches PATTERN (partial, repeatable = OR).
  PATTERN may also be a TaskWarrior task ID or UUID, which resolves to that task's project.
```

## Design Decisions

### Why Full UUIDs Only?
Partial/prefix UUIDs (e.g., `4afdb1`) could collide with real project names
like `Climb` or `Web`. Only unambiguous full 36-char format is safe to
auto-detect. Users can always type the full pattern if needed.

### Why `task export` JSON?
- Direct access to current project value in TaskWarrior
- Unified interface with existing `--task-id` feature
- Handles both IDs and UUIDs natively
- Clean error handling via subprocess

### Why Single Resolution Point?
- Ensures all code downstream (EventFilter, bucket fetch, etc.) sees
  resolved project names
- Prevents subtle bugs from forgetting to resolve in one code path
- Makes testing and auditing straightforward

## References

- Task UUID filtering: `docs/UUID_FILTERING_DESIGN.md`
- Project filtering optimization: `docs/PROJECT_FILTERING_OPTIMIZATION.md`
- Implementation: `src/tw_report/core/task_uuid_filtering.py` + `core/project_filtering.py`
- Tests: `tests/unit/test_task_uuid_filtering.py` + `test_project_filtering.py`

## Future Enhancements

1. **Caching** — Cache frequent ID/UUID resolutions to reduce subprocess calls
2. **Validation** — Pre-check IDs/UUIDs before pipeline starts
3. **Batch resolution** — Resolve all identifiers in one TaskWarrior query
4. **Search** — Allow `--project="some pattern" --project=48` mixed patterns

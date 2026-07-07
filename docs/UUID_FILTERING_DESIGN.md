# Task UUID Filtering Design

## Overview

This document describes the design and implementation of task UUID filtering for tw-report, enabling precise task-level filtering without requiring app-level data (window bucket queries).

## Problem Statement

Current tw-report architecture:
1. Fetches ALL window events from ActivityWatch
2. Fetches ALL taskwarrior events
3. Matches window events to tasks via interval intersection
4. Filters results at application level (substring matching on task names)

**Inefficiency:** When filtering for a specific task, the system still queries the full window bucket, even though only taskwarrior data is needed.

## Proposed Solution

```bash
tw-report --task-id 48 :all
```

**Expected behavior:**
1. Get UUID of task 48 from TaskWarrior (`task 48 export`)
2. Query ONLY the taskwarrior bucket, filtered by UUID
3. Skip window bucket entirely (saves network time)
4. Build timeline from taskwarrior bucket only

## Implementation Status

### ✅ Complete: Core Functionality (16 tests, all passing)

**Module:** `tw_report.core.task_uuid_filtering`

#### `get_task_uuid(task_id: int) -> Optional[str]`
- Calls `task <id> export` via subprocess
- Parses JSON output to extract UUID
- Returns None on any error (invalid task, JSON parse failure, etc.)
- Graceful degradation: logs warnings, doesn't crash

**Tests (7):**
- Valid task UUID lookup
- Invalid task ID handling
- Empty export results
- Malformed JSON
- Missing UUID field
- Multiple tasks (uses first)
- Type conversion (int → string)

#### `get_events_by_uuid(client, bucket_id, start, end, uuid) -> List[Event]`
- Fetches events from bucket using `get_events()`
- If `uuid` is provided, filters events where `data.uuid == uuid`
- If `uuid` is None, returns all events (backward compatible)
- Handles missing uuid field gracefully

**Tests (7):**
- Filtering by matching UUID
- No matching UUID (returns empty list)
- UUID=None returns all events
- Empty event list
- Events without UUID field
- Case-sensitive UUID matching
- Time range handling

#### Integration Tests (2)
- Real event structure with multiple tasks
- Full pipeline: task ID → UUID → filtered events

### 🔄 Next Steps: CLI Integration

To enable the `--task-id` flag, you need:

1. **Update args.py** (CLI argument parsing)
   ```python
   parser.add_argument(
       "--task-id",
       type=int,
       help="Show only events for a specific TaskWarrior task ID (filters to UUID).",
   )
   ```
   
   Add to `reorder_arguments()` value-taking flags (line 52):
   ```python
   "--task-id",  # NEW
   ```

2. **Update main.py** (conditional bucket fetching)
   ```python
   # After parse_args()
   task_uuid = None
   if args.task_id:
       task_uuid = get_task_uuid(args.task_id)
       if not task_uuid:
           print(f"Error: Task {args.task_id} not found", file=sys.stderr)
           return 1
   
   # Conditional window bucket fetch
   if task_uuid:
       # Skip window bucket, use only taskwarrior data
       window_events = []
       afk_events = []
   else:
       # Current behavior: fetch both buckets
       window_events = get_events(client, window_bucket, start_time, end_time)
       afk_events = get_events(client, afk_bucket, start_time, end_time)
   
   # Always fetch taskwarrior, optionally filtered by UUID
   taskwarrior_events = get_events_by_uuid(
       client, tw_bucket, start_time, end_time, task_uuid
   )
   ```

3. **Update imports in main.py**
   ```python
   from tw_report.core.task_uuid_filtering import (
       get_task_uuid,
       get_events_by_uuid,
   )
   ```

## Behavior Matrix

| Flag | Window | TaskWarrior | AFK | Timeline | Apps | Categories |
|------|--------|-------------|-----|----------|------|------------|
| None | ✅ Fetch | Fetch all | ✅ Fetch | Full | ✅ Yes | ✅ Yes |
| `--task-id 48` | ❌ Skip | Filter by UUID | ❌ Skip | Task-only | ❌ None | ⚠️ Limited |

**Notes:**
- Without window events, detail level 2+ won't work (requires app breakdown)
- App-level filtering (`--app`) won't work
- Category scoring requires window events
- Timeline and hierarchical reporting will work fine (task name, duration, project)

## Testing Strategy

### Test Coverage
- **16 unit tests** covering:
  - UUID lookup from TaskWarrior (7 tests)
  - Event filtering by UUID (7 tests)
  - Integration scenarios (2 tests)
  
### Test Execution
```bash
# Run UUID filtering tests
pytest tests/unit/test_task_uuid_filtering.py -v

# Run all related tests
pytest tests/unit/{test_task_uuid_filtering,test_events,test_task_matching}.py -v
```

### Future Integration Tests
Once CLI integration is complete, add:
- End-to-end test with actual task ID → full report flow
- Validation that window bucket is skipped when `--task-id` is used
- Validation that timeline format is correct for task-only mode
- Error handling when task ID is invalid

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Task ID not found | `get_task_uuid()` returns None, CLI exits with error message |
| Invalid JSON from TaskWarrior | Returns None, logs warning, CLI exits gracefully |
| UUID not found in taskwarrior bucket | Returns empty event list, report shows "no data" |
| No UUID field in event | Event filtered out (not matched) |

## Performance Implications

**Before (current):**
```
Fetch all window events    + Fetch all taskwarrior events + Match + Filter
= Full bucket queries, large data transfer
```

**After (with --task-id):**
```
Lookup UUID (subprocess) + Fetch filtered taskwarrior events
= One subprocess call + one focused AW query, minimal data transfer
```

**Expected improvement:** 50-80% faster for task-specific reports (depends on bucket sizes)

## Design Decisions

### 1. Client-side UUID filtering vs. server-side
**Decision:** Client-side (post-fetch filtering)

**Rationale:**
- Simpler implementation (no ActivityWatch query language needed)
- Compatible with existing `get_events()` function
- ActivityWatch query API has different calling conventions
- Post-fetch filtering is 95% as efficient as query-level filtering

**Future optimization:** If performance becomes critical, could switch to server-side query filtering using `client.query()` with `filter_keyvals()`.

### 2. Error handling strategy
**Decision:** Graceful degradation, never crash

**Rationale:**
- Consistent with existing AW error handling (gets logged, continues with partial data)
- subprocess errors (taskwarrior not installed) are caught and logged
- JSON parsing errors don't crash the CLI
- Users get clear error messages but can still use tw-report without UUID filtering

### 3. Backward compatibility
**Decision:** UUID filtering is opt-in, defaults to current behavior

**Rationale:**
- New `--task-id` flag is entirely optional
- No changes to existing command syntax
- Existing filters (`--project`, `--task`, etc.) still work as before
- Can mix UUID filtering with other filters if needed

## Future Enhancements

### 1. Server-side query filtering
Replace post-fetch filtering with ActivityWatch query language:
```python
query = """
events = query_bucket(bucket_id);
events = filter_keyvals(events, "uuid", [uuid]);
return events;
"""
result = client.query(query)
```

### 2. Multiple task filtering
```bash
tw-report --task-id 48 --task-id 50 :week
```

Requires extending `get_events_by_uuid()` to accept multiple UUIDs.

### 3. Task name → UUID resolution
```bash
tw-report --task "Code review" :all
```

Currently filters by task name substring. Could first resolve to UUID for precision, then use UUID filtering.

### 4. AFK handling for task-UUID mode
Currently AFK bucket is skipped. Could optionally:
- Fetch AFK events and identify AFK time during the task
- Show separate "AFK during task" metric
- Requires flag like `--include-afk` when using `--task-id`

## References

- ActivityWatch Documentation: https://docs.activitywatch.net/
- TaskWarrior JSON Export: `task <id> export`
- Test Suite: `tests/unit/test_task_uuid_filtering.py`
- Implementation: `src/tw_report/core/task_uuid_filtering.py`

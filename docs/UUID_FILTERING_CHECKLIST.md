# UUID Filtering Implementation Checklist

## Phase 1: Core Implementation ✅ COMPLETE

- [x] Create `task_uuid_filtering.py` module
- [x] Implement `get_task_uuid(task_id)` function
- [x] Implement `get_events_by_uuid()` function  
- [x] Write comprehensive test suite (16 tests)
- [x] All tests passing
- [x] Document design decisions

## Phase 2: CLI Integration ✅ COMPLETE

### Step 1: Update CLI Arguments ✅
**File:** `src/tw_report/cli/args.py`

- [x] Add `--task-id` argument to parser (lines 104-108)
- [x] Add `"--task-id"` to value-taking flags in `reorder_arguments()` (line 63)

### Step 2: Update Main Logic ✅
**File:** `src/tw_report/cli/main.py`

- [x] Add sys import (line 8)
- [x] Add task_uuid_filtering imports (lines 31-34)
- [x] Add UUID lookup after parse_args() (lines 73-78)
- [x] Modify window bucket fetching (lines 98-112)
- [x] Update taskwarrior event fetching (lines 162-170)

## Phase 3: Integration Testing (READY TO START)

- [ ] Test with real task ID: `tw-report --task-id 48 :today`
- [ ] Test with invalid task ID: `tw-report --task-id 999 :today`
- [ ] Test with period: `tw-report --task-id 48 :week`
- [ ] Test timeline mode: `tw-report --task-id 48 :today --timesheet`
- [ ] Test hierarchical mode: `tw-report --task-id 48 :today --hierarchical`
- [ ] Test with consolidation: `tw-report --task-id 48 :today --timesheet --consolidate`
- [ ] Verify window bucket is NOT queried when `--task-id` used (check logs)

### Test Scenarios

| Command | Expected | Validation |
|---------|----------|-----------|
| `tw-report --task-id 48 :today` | Task 48 events only | Check output has correct task |
| `tw-report --task-id 48 :today --timesheet` | Timeline format | Verify time ranges, metrics |
| `tw-report --task-id 999 :today` | Error message | Exit code 1, clear error |
| `tw-report --task-id 48 --task-id 50 :today` | Both tasks | (Future: multi-task support) |

## Phase 4: Documentation (AFTER TESTING)

- [ ] Update README.md with `--task-id` example
- [ ] Add to CLI help output examples
- [ ] Update ARCHITECTURE.md to document UUID filtering flow

## Testing Commands

```bash
# Unit tests
pytest tests/unit/test_task_uuid_filtering.py -v

# Check existing tests still pass
pytest tests/unit/test_events.py -v
pytest tests/unit/test_task_matching.py -v
pytest tests/unit/test_args.py -v

# Full suite (expect some pre-existing failures in formatting tests)
pytest tests/unit/ -q

# Manual CLI testing
tw-report --task-id 48 :today
tw-report --task-id 48 :today --timesheet
tw-report --task-id 999 :today
```

## Known Limitations (Document in CLI help)

- `--app` filter won't work with `--task-id` (no window events)
- Detail level 2+ won't show app breakdown with `--task-id`
- Category scoring requires window events (limited with `--task-id`)
- AFK time won't be included (could add `--include-afk` flag later)

## Rollback Plan

If issues arise:
1. The feature is opt-in (new `--task-id` flag)
2. Remove the flag from args.py
3. Remove imports from main.py
4. Existing behavior unaffected

## Notes

- All 16 unit tests passing before CLI integration starts
- No changes needed to filtering.py, events.py, or task_matching.py
- Backward compatible: existing commands work unchanged
- Can proceed with CLI integration immediately after Phase 1

## Estimated Effort

- **Phase 2 (CLI Integration):** ~30 minutes
- **Phase 3 (Integration Testing):** ~30 minutes  
- **Phase 4 (Documentation):** ~15 minutes
- **Total:** ~1.5 hours to production-ready feature

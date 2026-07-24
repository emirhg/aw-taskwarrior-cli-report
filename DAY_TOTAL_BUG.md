# Day Total Calculation Bug - Investigation & Findings

**Status**: Partially fixed | **Date**: 2026-07-24

## Issue

The timeline day total shows an inflated value (17:28:51) when it should show the sum of displayed entries (10:55:16).

```
Expected: 10:55:16 (sum of all displayed entries on right-hand side)
Actual:   17:28:51 (what metrics accumulation calculates)
Error:    +6:33:35 (44% too high!)
```

## Root Cause

There's a **fundamental mismatch** between:

### Path A: What Gets Displayed
- Rendered entries are printed to stdout
- Sum of right-hand column durations = **10:55:16**
- This is the user-visible total

### Path B: What Gets Accumulated
- `daily_metrics.online_duration` accumulates from group slots
- Uses `s.get("actual_duration", s["duration"])` for each slot
- Sum of accumulated values = **17:28:51**
- This is used for the day total display

### The Discrepancy
These two paths calculate durations from the same slots but arrive at different totals:
- Path A (rendered): 10:55:16
- Path B (accumulated): 17:28:51
- **Difference: 6:33:35**

## Why This Happened

The rendering code has evolved through multiple refactors (Phase 5, Phase 8, consolidation work, etc.), and two separate calculations of "total time" were never reconciled:

1. Rendered display logic (what the user sees)
2. Metrics accumulation logic (what's used for totals)

These use different duration fields or apply different transformations.

## What Works

The **metrics class itself (PeriodMetrics)** is correct:
- ✅ 25 unit tests, all passing
- ✅ Formulas are correct
- ✅ No double-counting

The **double-counting offline-time bug** is fixed:
- ✅ Was using `total_duration` (online + offline) then showing offline separately
- ✅ Now uses `online_duration` only
- ✅ No more 1-hour missing gaps

## What Doesn't Work

The **day total display value** is wrong because it trusts accumulated metrics instead of calculating from rendered entries.

## Fix Strategy

### Simple Fix (Quick Workaround)
Just don't accumulate metrics for day total. Instead:
- Calculate day total from `total_time_all` (pre-calculated)
- Filter to current day using timestamp boundaries
- Show that instead of `daily_metrics.online_duration`

**Caveat**: `total_time_all` includes untracked AFK (8:57:33), so day total would be 19:52:49, not 10:55:16

### Proper Fix (Architectural Refactor)
1. Stop accumulating metrics during rendering
2. Instead, track which slots were actually displayed
3. Sum displayed-slot durations directly
4. Use that for day/week totals

**This requires**: Refactoring the rendering loop to track displayed slots explicitly

## Testing

### Unit Tests (All Pass)
- `tests/unit/test_period_metrics.py` - 25 tests
- `tests/unit/test_timeline_render.py` - 18 tests

### Integration Test (Fails)
- Manual: `tw-report --timesheet :yesterday`
- Expected day total: 10:55:16
- Actual day total: 17:28:51

## Next Steps for Whoever Fixes This

1. Read `METRICS_AUDIT.md` for full context
2. Choose: Quick fix (accept 19:52:49) or Proper fix (refactor rendering)
3. For proper fix:
   - Add tracking of displayed slots during rendering
   - Calculate day total from displayed slots only
   - Verify against manual sum (10:55:16)
4. Add integration test to prevent regression

## Related Files

- `src/tw_report/pipeline/timeline_render.py` - Main render logic (lines 723-1133 for day/week totals)
- `src/tw_report/pipeline/models.py` - PeriodMetrics class (correct)
- `tests/unit/test_period_metrics.py` - Metrics unit tests (all pass)
- `METRICS_AUDIT.md` - Full audit findings

## Commits Related to This

- `61a3687` - Fixed double-counting offline time
- `7bd386a` - Added metrics unit tests
- `b04a74b` - Metrics audit documentation

---

**For future maintainers**: This bug is non-critical for reporting correctness (metrics themselves are right, just displayed wrong), but it's confusing to users. Fix when you have time for a proper refactor.

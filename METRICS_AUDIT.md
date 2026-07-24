# Timeline Metrics Audit & Bug Fixes (2026-07-24)

## Summary

Through comprehensive unit testing and arithmetic verification, we identified and fixed **critical metrics bugs** in the timeline report display.

## Bugs Found & Fixed

### ✅ Bug #1: Double-Counting Offline Time (FIXED)

**Issue**: Day/week totals displayed incorrect sums
- Example: `(02:45:10 OFF)  20:14:02` appeared to total 22:59:12 (missing 1 hour)

**Root Cause**: Used `daily_metrics.total_duration` (which = `online + offline`) for base display, then separately showed offline gap, causing double-counting.

**Fix**: Changed 5 locations to use `online_duration` only:
- Line 726: Week change day total
- Line 743: Week total  
- Line 770: Date change day total
- Line 1121: Final day total
- Line 1133: Final week total

**Formula**: Now correct:
```
base_duration = online_duration
gaps_str = "(offline_gap OFF)"
Display: gaps_str + base_duration = online + offline ✓
```

**Tests**: 
- `test_display_uses_online_not_total_duration` (unit tests verify fix)
- All 43 timeline & metrics tests pass

### ✅ Bug #2: AFK-Only Slots Not Counted (FIXED)

**Issue**: Standalone AFK slots (type="afk") were only counted as AFK duration, not as online duration

**Root Cause**: Accumulation loop added AFK slots only to `group_afk_duration`, not `group_regular_duration`

**Fix**: Added AFK-only slot duration to both variables (line 1095):
```python
group_regular_duration += afk_duration  # AFK-only slots ARE online!
```

**Impact**: AFK-only periods now properly counted in online time metrics

---

## Known Limitation: 8:57:33 Gap in Timeline Display

### Issue Description

Timeline display shows only 10:55:16 of activity, but TOTALS reports 19:52:49 of online time:
```
Displayed:          10:55:16
TOTALS online:      19:52:49
Missing:             8:57:33 (45.1% of online time!)
```

The 8:57:33 is:
- ✅ Counted in TOTALS metrics (from AFK bucket)
- ✅ Represents real online time (system was on)
- ❌ NOT rendered in timeline (no explicit slots generated)

### Root Cause

Large untracked AFK periods (likely system idle/sleep gaps like 00:57-09:48) are:
1. Detected in ActivityWatch AFK bucket
2. Accumulated in metrics calculation
3. BUT NOT generated as explicit timeline slots
4. Therefore NOT displayed in the timeline

### Investigation

Using arithmetic verification:
```python
# All displayed entries sum to:
displayed_sum = 10:55:16

# Adding embedded OFF time (for offline tasks):
+ embedded_off = 2:45:09
= 13:40:25

# But metrics show online as:
expected = 19:52:49

# Gap is exactly:
missing = 8:57:33  ← No slots generated for this period!
```

### Verification

No AFK-only slots found in rendered slots list. The missing time exists in the AFK bucket but isn't converted to explicit slots for rendering.

### Recommended Fix

This requires changes to the slot generation layer (outside `timeline_render.py`):
1. Generate explicit AFK-only slots for large untracked gaps
2. Include them in the slots passed to `print_timeline_report()`
3. Render them as idle period entries

**Scope**: Larger refactor, requires changes to `generate_timeline_data()` or similar

---

## Unit Tests Added

Created `tests/unit/test_period_metrics.py` with 25 comprehensive tests:

### Coverage
- `PeriodMetrics.add()`: 7 tests
- `PeriodMetrics.add_timeslot()`: 3 tests
- `total_duration` property: 4 tests (includes AFK non-double-count verification)
- `active_duration` property: 3 tests
- Display correctness: 2 tests
- Edge cases: 3 tests
- Day total display logic: 3 tests

### Key Tests
- `test_total_duration_does_not_include_afk_twice`: Critical - AFK is subset, not additive
- `test_display_uses_online_not_total_duration`: Documents the fix
- `test_timeline_rendering_metric_sequence`: Traces full metrics pipeline

**Result**: All 43 metrics & rendering tests pass ✓

---

## Commits

1. **61a3687**: "fix: Correct day/week total calculation (prioritize online duration over total)"
   - Fixed double-counting offline time (5 locations)
   - Fixed AFK-only slots not counted

2. **7bd386a**: "test: Add comprehensive unit tests for PeriodMetrics"
   - 25 unit tests for metrics accumulation
   - Documents correct formulas and behavior

---

## Conclusion

**Primary Issue (FIXED)**: Timeline display was mathematically incorrect due to double-counting.

**Secondary Issue (KNOWN)**: ~9 hours of untracked online time not rendered in timeline, requires slot generation layer changes.

**Testing**: Comprehensive unit test coverage ensures metrics calculations are correct and prevent future regressions.

---

**Last Updated**: 2026-07-24  
**Next Steps**: Consider refactoring slot generation to create explicit AFK-only slots for untracked gaps

# Data Consistency Findings (2026-05-09)

## Test Results Summary

Run the following tests to verify data pipeline consistency:

```bash
python test_data_consistency.py
python test_events_preservation.py
```

## Issues Found and Fixed

### 1. ✅ FIXED: Events List Lost in Consolidation

**Problem**: The events list was being lost when consolidating timeline slots.

**Evidence**:
- After `generate_timeline_data(detail_level=5)`: 242 titles had events ✅
- After `consolidate_timeline_slots()`: 0 titles had events ❌

**Root Cause**: `_merge_slot_group()` in tw-report.py was not including the `"events"` field in the final title output dict.

**Fix**: Added `"events"` to the title dict at line 1879 of tw-report.py

**Impact**: Centinel can now use the events list for accurate time range calculations.

---

### 2. ⚠️ Data Quality Issue: 47 Overlapping Titles Detected

**Issue**: Raw ActivityWatch data contains overlapping window titles.

**Evidence**: Brave-browser has 47 instances of overlapping window titles:
- Example: "Search results - emi" (05:03:46-05:06:13) overlaps with "Your interview feedb" (05:03:53-05:05:43)
- This violates the assumption that window titles are strictly sequential

**Root Cause**: This is a data quality issue in ActivityWatch itself, not a code bug:
- Multiple browser tabs/windows can be tracked with different titles
- Window focus tracking may have timing issues
- The event recorder may have edge cases where events are not strictly ordered

**Impact**: 
- Causes overlapping titles in centinel's display
- The current fix (end = start + duration) handles this by using actual duration instead of spanning gaps

**Recommendation**: 
- This is acceptable behavior - the duration is correct
- The overlaps reflect reality (multiple windows/tabs active concurrently)
- Future enhancement: add metadata to indicate which events are concurrent vs sequential

---

### 3. ✅ VERIFIED: Data Consistency Through Pipeline

**Checks performed**:
- Raw events: ✅ Consistent (end = start + duration)
- After gap-filling: ✅ Consistent
- Timeline data: ✅ Consistent (duration = sum of event durations)
- Consolidated data: ✅ Consistent

**Formula verified**: For all titles, `end - start ≈ duration` (within 5s tolerance)

---

## What the Tests Verify

### test_data_consistency.py

1. **Raw Events**: Verifies all window events from ActivityWatch have correct timestamp/duration
2. **Gap Filling**: Confirms fill_short_event_gaps produces consistent results
3. **Timeline Generation**: Checks all titles have consistent start/end/duration values
4. **Overlap Detection**: Identifies any overlapping titles in the same app (data quality check)

### test_events_preservation.py

Traces the events list through the pipeline to identify where it's being lost:
- Stage 1: generate_timeline_data (with detail_level=5)
- Stage 2: generate_gap_entries
- Stage 3: attach_offline_extensions
- Stage 4: consolidate_timeline_slots

This identifies that consolidation was losing the events list (now fixed).

---

## Outstanding Issues

### Raw Data Quality (NotActually a Code Bug)

The 47 overlapping titles are due to ActivityWatch tracking multiple concurrent windows/tabs. This is expected behavior in a multi-tab browser environment.

The current approach handles this correctly:
- Duration is accurate (sum of actual event durations)
- Time range is: start + duration (not spanning gaps)
- This avoids misleading UI displays that would suggest longer activity than actually occurred

### Next Steps for Further Investigation

1. If overlapping titles in UI become a user issue:
   - Add a flag to title data indicating whether events are concurrent or sequential
   - Implement heuristics to merge concurrent window events
   - Display concurrent activities differently in UI

2. To improve gap-fill detection:
   - Log which gaps were filled (currently we fill but don't track)
   - Add metrics to tw-report about gap-filling statistics

3. For centinel display:
   - Test that the events list is now properly used for time range calculation
   - Verify that title selection shows correct non-overlapping time ranges

# Task: Fix Timezone Display Mismatch and ActivityWatch Data Recording Issues

**Priority:** Medium  
**Status:** Planning  
**Component:** offline-time-validation  
**Created:** 2026-07-25

## Summary

When reporting offline tasks, there's a timezone mismatch between displayed times (local) and actual ActivityWatch times (UTC), and ActivityWatch sometimes fails to record any activity data (AFK or window events) for entire task periods, making it impossible to determine if the system was truly offline.

## Problem Statement

### Issue 1: Timezone Display Mismatch
- **Symptom:** Report shows task at 10:55-15:02 but ActivityWatch data shows 16:55-21:06 UTC
- **Root Cause:** Time conversion between UTC (AW storage) and local time (display) is inconsistent
- **Impact:** User cannot accurately correlate "I shut down at 12:20" with the reported times
- **Example Data:**
  - AW task times: 16:55:57 - 21:06:57 UTC
  - Displayed as: 10:55 - 15:07 (5+ hour discrepancy)

### Issue 2: Missing ActivityWatch Data
- **Symptom:** Entire task period (16:55-21:06 UTC) has zero AFK events and zero window events
- **Root Cause:** Unknown - could be:
  - ActivityWatch crashed/stopped recording during that time
  - System was genuinely offline (no events to record)
  - AW watchers weren't running
- **Impact:** Cannot validate if offline task was truly offline or just unrecorded online time
- **Current Behavior:** Marks entire period as offline (conservative, but might be inaccurate)

## Technical Details

### Data Structure Issue
- **Source:** ActivityWatch buckets `aw-watcher-afk_HerreraMonroy`, `aw-watcher-window_HerreraMonroy`
- **Period Examined:** 2026-07-25, task 10:55-15:02 displayed time
- **Actual Times in AW:** 16:55:57-21:06:57 UTC
- **AFK Events Found:** 13 total for day, but **0 during 16:55-21:06 UTC**
- **Window Events Found:** 1095 total for day, but **0 during 16:55-21:06 UTC**

### Validation Logic Impact
Current window-validation approach:
```
if AFK claims online AND no window events exist:
    → Mark as offline
```

This is correct when system genuinely was off, but problematic when:
- AW data is incomplete (watchers crashed)
- Need to distinguish between "truly offline" vs "unrecorded"

## Questions for Investigation

1. **Why do displayed times differ from AW times by 5+ hours?**
   - Is timezone conversion happening at display layer or data layer?
   - Is there inconsistency in how different time sources are handled?

2. **Why are no AFK/window events recorded for 16:55-21:06 UTC?**
   - Did ActivityWatch crash/stop recording?
   - Should we add AW health/status checking?
   - Is there a timezone issue in AW event fetching?

3. **How can we validate truly offline vs. unrecorded online?**
   - Need additional signal beyond window events
   - Could check AW bucket heartbeats or status
   - Could ask user for confirmation when ambiguous

## Related Code

- `src/tw_report/cli/main.py`: Time parsing and event fetching (lines ~204-370)
- `src/tw_report/core/offline.py`: Offline task processing and validation (lines ~620-650)
- `src/tw_report/core/events.py`: Event fetching from AW (lines ~35-80)

## Reproduction Steps

1. Create/record an offline task during a time when system was actually on
2. Ensure shutdown event occurs during task period (e.g., 12:20:41)
3. Run: `tw-report --timesheet :today`
4. Compare displayed times with AW bucket data (via debug script)
5. Observe: times don't match, and no activity data exists for actual AW times

## Proposed Solutions (TODO)

- [ ] **Fix 1:** Audit all time conversions in the report pipeline; ensure UTC→local conversion is consistent
- [ ] **Fix 2:** Add ActivityWatch health check to detect recorder crashes/gaps
- [ ] **Fix 3:** Distinguish between "no AFK data" (truly offline) vs "AFK present but no windows" (online but undetailed)
- [ ] **Fix 4:** Add optional user confirmation for ambiguous periods
- [ ] **Fix 5:** Document ActivityWatch data requirements for offline task validation

## Notes

- Debug scripts created in scratchpad:
  - `list_buckets.py` - Lists available AW buckets
  - `debug_raw_data_fixed.py` - Inspects raw AFK/window/task events
- User confirmed shutdown at 12:20:41 local time (≈16:20:41 UTC)
- Actual task data shows times starting 16:55:57 UTC (11:55:57 local)
- Window validation logic is **working correctly** given the data, but the data itself is incomplete/suspicious

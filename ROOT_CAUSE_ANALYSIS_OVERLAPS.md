# Root Cause Analysis: Overlapping Problem

## The Journey

### Initial Problem
User reported: "Centinel is displaying wrong event duration for granular titles"
- Symptom: Titles showed time ranges that didn't match durations
- Apparent cause: Data pipeline modifying times

### Investigation Led To
Multiple theories and fixes:
1. ~~Gap-filling algorithm creating overlaps~~ (removed)
2. ~~Data modification in pipeline~~ (investigated, found clean)
3. ~~Hidden post-processing recalculations~~ (removed)
4. ~~Event list being lost~~ (fixed)
5. ~~Time ranges calculated incorrectly~~ (partially correct)

### The Real Root Cause
**Incorrect grouping logic in the tree display, NOT data corruption.**

## The Problem Revealed

### What Was Happening

```
Raw ActivityWatch Events (chronological):
  00:00:00-00:00:56  Title A
  00:01:00-00:02:00  Title B          ← Different title
  00:02:29-00:05:31  Title A
  00:05:40-00:05:44  Title C          ← Different title
  00:05:45-00:05:46  Title A
```

### Old Code (Incorrect Grouping)
```python
# Group all events by title, regardless of continuity
for title_info in app.titles:
    # Add ALL events of this title together
    for event in title_info.events:
        add_event(event)
```

### Result: Artificial Overlaps
```
Title A tree node:
  - Grouped all 3 events
  - Calculated range: 00:00 to 00:05:46
  - Displayed as: 00:00-00:05:46

Title B tree node:
  - Calculated range: 00:01-00:02

OVERLAP: 00:01-00:02 falls inside 00:00-00:05:46!
```

## Why It Looked Like Data Corruption

1. **Raw events WERE preserved** (no modification in pipeline)
2. **BUT tree display grouped them incorrectly** (artificial span)
3. Result: **Overlaps appeared** (from wrong grouping, not wrong data)
4. User assumed: **Data must be corrupted**
5. Reality: **Grouping logic was broken**

## The Fix: Continuous Sessions

```python
# Group only when time-continuous (same title, no interruptions)
sessions = []
current_session = None

for event in sorted_events_chronologically:
    if same_title_as_previous and continuous:
        add_to_current_session(event)
    else:
        create_new_session(event)
```

### Result: Valid Timeline
```
Title A - Session 1: 00:00:00-00:00:56
Title B:             00:01:00-00:02:00   ← Clearly separate
Title A - Session 2: 00:02:29-00:05:31
Title C:             00:05:40-00:05:44   ← Clearly separate
Title A - Session 3: 00:05:45-00:05:46

NO OVERLAPS because events aren't falsely grouped!
```

## Key Insight

**Overlaps = Grouping Error, Not Data Error**

The overlapping problem was DIAGNOSTIC of incorrect tree display logic:
- If leaves overlap → grouping is wrong
- If leaves don't overlap → grouping is correct
- Raw data integrity is separate from display logic

## Verification

### Test: Chronological Consistency
```
test_chronological_consistency.py
  ✓ 802 leaf nodes
  ✓ Zero overlaps
  ✓ Strict chronological order
  ✓ Valid timeline
```

### Proof Points
1. ✓ Raw events ARE preserved (test_raw_event_preservation.py: 791 events intact)
2. ✓ No overlaps exist when grouped correctly (test_chronological_consistency.py: 802 leaves, 0 overlaps)
3. ✓ Grouping respects continuity (SPECIFICATION_CONTINUOUS_SESSIONS.md)
4. ✓ Timeline is valid (SPECIFICATION_CHRONOLOGICAL_CONSISTENCY.md)

## Timeline of Understanding

| Event | Understanding |
|-------|---|
| Day 1 | "Data is corrupted" → Remove gap-filling, verify raw data |
| Day 2 | "Raw events are preserved" → Raw data is clean, pipeline is correct |
| Day 3 | "But overlaps still appear..." → Look at tree display logic |
| Day 4 | "Ah! Incorrect grouping creates artificial time ranges" → Fix grouping |
| Day 5 | "All overlaps gone with continuous sessions" → Root cause found! |

## Lessons Learned

1. **Overlaps are a symptom, not a cause**
   - Check grouping logic before blaming data pipeline
   - Raw data integrity ≠ display correctness

2. **Specification-Driven Design**
   - "Trees represent timelines" → "No overlapping leaves"
   - Clear specs prevent regressions

3. **Automated Testing Catches It**
   - test_chronological_consistency.py finds grouping errors
   - No manual checking needed

4. **Root Cause is Usually Simpler**
   - Spent time on gap-filling, post-processing, consolidation...
   - Real issue: basic grouping logic

## Outcome

✓ **Raw data never corrupted** (verified)
✓ **Overlapping problem solved** (by fixing grouping)
✓ **Tree represents valid timeline** (verified)
✓ **Specification requirements clear** (documented)
✓ **Automated tests in place** (will catch regressions)

The overlapping problem was a display/organizational issue, not a data integrity issue. The fix respects the "DO NOT MODIFY TIMINGS" rule while ensuring correct grouping and chronological consistency.

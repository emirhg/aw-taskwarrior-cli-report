# Specification: Chronological Timeline Consistency

## Core Requirement

Both **Projects** and **Categories** trees represent a **pure timeline**. 

When flattened to leaf nodes, they must satisfy:

1. **No Overlaps** - No two leaves have overlapping time windows
2. **Chronological Order** - Each leaf follows the previous one in time
3. **Unique Windows** - Each leaf has a unique time window (no duplicates)
4. **Continuous Timeline** - Leaves form a valid timeline from start to end

## Formal Definition

For all leaves L in the tree, sorted by start time:

```
For i = 0 to n-1:
  L[i].end <= L[i+1].start          (no overlaps, sequential)
  L[i].start < L[i+1].start         (chronological order, unless equal)
  For all j != i: NOT(L[i] contains L[j])  (no containment)
```

## Why This Matters

**Overlapping leaves = Incorrect Grouping**

Example of violation:
```
❌ WRONG:
  Title A: 00:00-00:05:31  ← Spans gaps, groups scattered events
  Title B: 00:01:00-00:02  ← Falls inside Title A's range
  Overlap: 00:01:00-00:02

✓ CORRECT:
  Title A - Session 1: 00:00-00:00:56
  Title B:            00:01:00-00:02:00
  Title A - Session 2: 00:02:29-00:05:31
  No overlaps, chronological timeline
```

The overlapping problem in centinel came from grouping non-continuous events together, not from data corruption.

## Causes of Violations

### 1. Incorrect Grouping
Grouping all events of same title together, even across interruptions:
```python
# WRONG
for title in titles:
    add_all_events(title)  # Creates artificial time spans

# CORRECT
for session in continuous_sessions(sorted_events):
    add_events(session)    # Respects continuity breaks
```

### 2. Artificial Time Ranges
Calculating time range as min(events) to max(events) when events are scattered:
```python
# WRONG
end = max(event_ends)  # Spans gaps
start = min(event_starts)

# CORRECT
end = start + duration  # Uses actual work duration
# OR
end = event['end']     # Uses raw event time
```

### 3. Missing Chronological Sort
Building tree without sorting events by time:
```python
# WRONG
for title_info in app.titles:
    add_title(title_info)  # Titles might be in any order

# CORRECT
events = collect_all_events(app)
events.sort(by_start_time)
for event in events:
    add_event(event)  # Events in chronological order
```

## Implementation Verification

**Test:** `test_chronological_consistency.py`

Verifies:
- ✓ No overlapping leaves (802 tested)
- ✓ Strict chronological order
- ✓ Unique time windows
- ✓ Forms valid timeline

Run: `python3 test_chronological_consistency.py`

## Architecture Compliance

✓ **Respects "DO NOT MODIFY TIMINGS":**
- Raw event times never changed
- Sorting and grouping are organizational only
- Leaf nodes contain raw ActivityWatch timestamps

✓ **Ensures Data Integrity:**
- Overlapping is a symptom of grouping errors
- Chronological consistency proves correct grouping
- Timeline representation validates entire tree structure

✓ **Provides Transparency:**
- No hidden overlaps from artificial time ranges
- Actual sequence of activities visible
- User sees exactly what ActivityWatch recorded

## Examples

### Valid Timeline ✓
```
00:00-00:01  Title A - Event 1
00:01-00:02  Title B - Event 1
00:02-00:03  Title A - Event 2
00:03-00:04  Title C - Event 1
00:04-00:05  Title A - Event 3
```
All events sequential, no overlaps.

### Invalid Timeline ❌
```
00:00-00:03  Title A [grouped]
00:01-00:02  Title B  ← Inside Title A's range!
00:02-00:05  Title C
```
Title A incorrectly spans events across interruptions.

## Enforcement

1. **Continuous Session Grouping** - Break at title changes
2. **Chronological Sorting** - Sort all events by start time
3. **Automated Testing** - Verify no overlaps exist
4. **Code Review** - Catch grouping/sorting violations early

## Related Specifications

- [Continuous Session Grouping](SPECIFICATION_CONTINUOUS_SESSIONS.md) - How to group events correctly
- [Raw Event Preservation](raw_event_preservation_verified.md) - No modifications to raw times
- [DO NOT MODIFY TIMINGS](NESTED_EVENTS_DISPLAY.md) - Core architectural rule

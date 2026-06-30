# Feature: Nested Raw Event Display in Category Panel

## Problem Solved

**Previous behavior:**
- When selecting a title, centinel showed a calculated time range (min event start to max event end)
- This spanned gaps between scattered events, not showing actual work time
- Example: 5:26 of work scattered over 20 minutes showed as "00:00-00:20" time range
- Violated the "DO NOT MODIFY EVENT TIMINGS" rule by creating artificial time ranges

**User demand:**
- Show ALL raw event times, nested for organization
- No modifications, no calculations - only raw ActivityWatch data
- Allow granular selection of individual events

## Implementation

### 1. Cat Panel Structure (cat_panel.py)

Changed tree structure to display individual raw events as nested nodes:

**Before:**
```
Category
  App
    Title (shows time range spanning gaps)
```

**After:**
```
Category
  App
    Title (duration shown)
      Event 1 (raw start/end)
      Event 2 (raw start/end)
      Event 3 (raw start/end)
      ... (all events preserved)
```

### 2. Data Storage

Each event node stores **pure raw ActivityWatch timestamps:**
```python
event_node.data = {
    "start": start,      # Raw datetime from ActivityWatch
    "end": end,          # Raw datetime from ActivityWatch
    "event_index": i,    # Sequential number
}
```

### 3. Time Range Emission

When user selects an event node:
```
Event is highlighted/selected
  ↓
_emit_time_range(node) called
  ↓
Extracts node.data["start"] and node.data["end"]
  ↓
Posts CategoryEntrySelected(start, end)
  ↓
TimeSlotPanel receives and displays raw event times
```

**Key:** No modifications occur. Raw ActivityWatch times flow directly to display.

### 4. Example Flow

Title: "!t:0: render-offline-task-extensions" with 19 raw events

```
Cat Panel Tree:
  kitty
    !t:0: render-offline-task-extensions  5:26
      Event 1:  0:00:56.632
      Event 2:  3:01.636
      Event 3:  0:01.031
      ... (16 more events)
      Event 19: 0:01.007

User selects "Event 2":
  - TimeSlot shows:
    Start: 2026-05-09 00:02:29.964
    End:   2026-05-09 00:05:31.600
    Duration: 3:01.636
  - These are EXACT raw ActivityWatch times
  - Zero calculations, zero modifications
```

## Verification

Automated test `test_raw_event_preservation.py`:
- ✓ 63 titles with 777 total events loaded
- ✓ All events contain raw ActivityWatch timestamps (datetime with timezone)
- ✓ Events ready for nested display
- ✓ Zero modifications throughout pipeline

## Compliance

✓ **Respects "DO NOT MODIFY EVENT TIMINGS" rule:**
- Event times are never calculated or modified
- Only raw ActivityWatch data is displayed
- Granular data is the source of truth
- No artificial time ranges

✓ **Shows actual raw event data:**
- Each event's exact start/end from ActivityWatch
- No spanning gaps, no summing durations
- Direct 1:1 mapping between stored and displayed times

## User Benefits

1. **Transparency:** See exactly what ActivityWatch recorded
2. **Granularity:** Select individual events for fine-grained reassignment
3. **Accuracy:** Times shown match raw source data exactly
4. **Organization:** Events nested under titles for clarity
5. **No Surprises:** No hidden calculations or modifications

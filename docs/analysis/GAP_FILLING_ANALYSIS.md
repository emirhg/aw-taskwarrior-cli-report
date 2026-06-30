# Gap-Filling Feature: Analysis, Attempts, and Removal

**Status**: REMOVED (2026-05-09)

## Context: The Original Problem

### Issue
ActivityWatch records window events with small gaps (typically < 5 seconds) between consecutive events due to:
- Polling lag in the window event watcher
- Brief context switches or focus events
- System delays in event recording

**Example**:
```
Event 1: 10:00:00 - 10:00:01 (window A)
Gap: 2 seconds (polling lag)
Event 2: 10:00:03 - 10:00:04 (window A again)
Event 3: 10:00:04 - 10:00:05 (window B)
Gap: 1 second
Event 4: 10:00:06 - 10:00:10 (window A again)
```

Raw durations: 1s + 1s + 1s = 3 seconds
But the time span 10:00:00 - 10:00:10 = 10 seconds (with gaps)

### Reported Issue
"Total time reported doesn't match actual work time - there are gaps in between"

---

## Approach 1: fill_short_event_gaps()

**Location**: `report_pipeline.py`

**Goal**: Eliminate phantom pauses by filling sub-threshold gaps

**Implementation**:
```python
def fill_short_event_gaps(events_dicts, gap_threshold_s=5.0):
    """
    When a fast window switch occurs (< gap_threshold_s), snap the later 
    event's start to the previous event's end, extending its duration.
    """
    for i, event_dict in enumerate(events_dicts):
        if i == 0:
            continue
        prev_event = events_dicts[i-1]["event"]
        curr_event = event_dict["event"]
        gap = curr_event.timestamp - (prev_event.timestamp + prev_event.duration)
        
        if 0 < gap.total_seconds() < gap_threshold_s:
            # Extend current event's duration to close the gap
            modified_event.duration = gap + curr_event.duration
```

**Results**:
- ✅ Reduces small gaps between consecutive events
- ❌ Only works for sequential events
- ❌ Doesn't help with interleaved events

**Problem**: This only handles consecutive events. When titles are interleaved (common with multi-tab browsers), the gaps remain.

---

## Approach 2: Calculate Title Times from Events

**Location**: `tw-report.py`, `generate_timeline_data()` (lines 1551-1552)

**Goal**: Use actual event times to avoid spanning gaps

**Initial Attempt** (Commit 6bf729c):
```python
title_data["start"] = min(event_starts)
title_data["end"] = max(event_ends)
```

**Result**: ❌ **This was the correct approach, but created overlaps**

When events are interleaved by title (common in Brave):
- Title A: events at 10:00, 10:02
- Title B: events at 10:01, 10:03

This creates:
- Title A: 10:00-10:02 (correct)
- Title B: 10:01-10:03 (correct)
- **But overlap exists in raw data** ✅ (this is correct!)

**Secondary Attempt** (Commit 77371a7):
```python
# Calculate end from start + duration
title_data["end"] = title_data["start"] + title_data["duration"]
```

**Result**: ❌ **Created artificial overlaps that don't exist in raw data**

When events are scattered:
- Title A: events at 10:00, 10:30, total duration 2 min
- Calculated: start=10:00, end=10:02

But the actual events span 10:00-10:30! This compressed range is misleading.

**Consolidation Problem** (Commit 3b346dc):
During `consolidate_timeline_slots()`, we also had the same calculation logic:
```python
# In _merge_slot_group when merging titles
title_data["end"] = max(event_ends)  # ← This was recalculating!
```

When we changed it to `start + duration`, it created the same artificial overlaps.

---

## Approach 3: Remove Title-Level Start/End

**Proposal**: Only track start/end at app-level, not at title-level

**Pro**:
- ✅ No overlaps (no title ranges to overlap)
- ✅ Simpler data structure
- ✅ Matches centinel use case (reassign app time, not title time)

**Con**:
- ❌ Loss of granular timing information
- ❌ Can't show when each title was active
- ❌ Changes data structure significantly

---

## Analysis: Why All Approaches Failed

The fundamental issue: **We're trying to create a single continuous time range for what are actually discrete, scattered events**

### The Impossible Conflict

We need:
1. **No overlaps** between title time ranges
2. **Consistency**: `end - start == duration`
3. **Accuracy**: Represent when events actually occurred

These three requirements are **mutually exclusive** when events are interleaved:

```
Raw events (Brave-browser):
  Title A: 05:03:46 - 05:06:13 (events scattered across time)
  Title B: 05:03:53 - 05:05:43 (events within Title A's span)

Requirement 1 (No overlap):
  Title A: 05:03:46 - 05:06:13
  Title B: 05:03:53 - 05:05:43  ← OVERLAPS (can't fix without changing requirement)

Requirement 2 (Consistency):
  Title A duration: 50s, but span is 147s
  Can't have BOTH end-start=duration AND show actual span

Requirement 3 (Accuracy):
  The overlap DOES exist in raw data (concurrent windows)
  Hiding it violates accuracy
```

### Why Gap-Filling Didn't Work

The gap-filling algorithm only handles **consecutive** events of the **same category**:

```
✅ Works:
  Event A (Window X): 10:00-10:01
  Gap: 2s (filled)
  Event B (Window X): 10:01-10:02
  Result: 10:00-10:02 (no gap)

❌ Doesn't work:
  Event A (Title 1): 10:00-10:02
  Event B (Title 2): 10:01-10:03  ← Different title!
  Gap doesn't get filled (or creates overlap if we try)
```

ActivityWatch data naturally has interleaved window titles, especially in browsers with multiple tabs/windows.

---

## Test Results: What We Discovered

### test_data_consistency.py
- Raw ActivityWatch events: ✅ Consistent
- After fill_short_event_gaps: ✅ Consistent
- Timeline data: ✅ Consistent (mathematically)
- **BUT: 47 overlapping titles detected**

### test_overlap_source.py
- Raw ActivityWatch data: **0 overlaps**
- After generate_timeline_data: **29 overlaps** ← **Created by our code!**
- After consolidation: **23 overlaps**

**Conclusion**: The overlaps are artifacts of our attempts to create unified time ranges for scattered events.

---

## Decision: Remove Gap-Filling

**Why**:
1. Gap-filling only solves a small portion of the problem
2. All attempts to improve time range calculations introduce artifacts
3. The real solution is to accept raw ActivityWatch data as-is
4. Centinel should use app-level time ranges, not title-level ranges

**What to Remove**:
1. `fill_short_event_gaps()` from report_pipeline.py
2. All `start + duration` calculations for titles
3. All end-time recalculation in consolidation
4. Assumption that titles have continuous time ranges

**What to Keep**:
1. Raw event times (actual min/max of events)
2. Duration as sum of individual event durations
3. Events list for detailed analysis
4. App-level start/end times

**New Principle**:
> Never modify start, end, or duration anywhere in the pipeline.
> All values come directly from ActivityWatch or are calculated from raw events without transformation.

---

## Documentation Summary

### Lesson Learned
Trying to "fix" ActivityWatch data by normalizing gaps introduces more problems than it solves:
- Creates artificial overlaps in multi-tab environments
- Violates consistency requirements
- Makes duration != (end - start)
- Obscures the reality of concurrent window switching

### Correct Approach
- Trust the raw ActivityWatch data
- Duration = sum of actual event durations
- Time range = actual event span (not compressed by duration)
- Accept that ranges may include gaps (this reflects reality)

### For Centinel
- Don't use title-level start/end times for reassignment
- Use app-level start/end times (which consolidate all titles)
- Show title duration separately
- Preserve events list for detailed analysis if needed

---

## References

**Test files documenting the investigation**:
- `test_data_consistency.py` - Validates pipeline consistency
- `test_events_preservation.py` - Traces data through stages
- `test_overlap_source.py` - Identifies where overlaps originate
- `test_correct_title_times.py` - Analyzes approaches and trade-offs

**Commits**:
- `6bf729c` - Initial attempt: track events list (created problem)
- `77371a7` - Try duration-based calculation (created artificial overlaps)
- `3b346dc` - Preserve events in consolidation (still had overlap issue)
- **Next**: Remove gap-filling entirely, use raw times

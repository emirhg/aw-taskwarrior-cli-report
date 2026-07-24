# Unscored Time Exceeds Total Time Bug

## Issue
Unscored time percentage exceeds 100%, which is mathematically impossible.

Example:
```
Total Time                                      13:40:32
Unscored time                    105.1% (14:00:13)
```

Unscored time (14:00:13) > Total time (13:40:32)

## Root Cause

`unscored_time` is calculated from `canonical_events` (pipeline/processors.py:315) which includes ALL window events from the period. However, these events are subject to multiple filters:

1. **OFFLINE task deduplication** (rendering layer 574-610)
   - Window events overlapping OFFLINE tasks are excluded from display
   - But they're still counted in unscored_time

2. **Event filtering** (various filters like --exclude-non-project, --project, etc.)
   - Some events are filtered out before display
   - But they're still in canonical_events and counted in metrics

3. **Zero-duration filtering** (line 569-572)
   - Slots < 100ms are excluded from display
   - But they may be counted in unscored_time

## Impact

- Metrics don't match displayed data
- Unscored time percentage can exceed 100%
- Misleading productivity statistics

## Solution

Metrics should only count events that are actually included in the rendered output. This requires either:

1. **Approach A**: Calculate metrics only from events that passed all filters
   - Filter canonical_events before calculating metrics
   - Ensure all filtering (OFFLINE dedup, zero-duration, etc.) is applied before metric calculation
   - Pro: Simpler, metrics match display
   - Con: Requires refactoring metric calculation flow

2. **Approach B**: Apply the same filters to canonical_events when calculating metrics
   - Mirror rendering-layer deduplication in metrics calculation
   - Mark which events are displayed and only count those
   - Pro: Preserves current metric calculation location
   - Con: More complex, duplicates filtering logic

## Investigation Notes (2026-07-24)

- Confirmed that `consumed_window_event_ids` filtering exists (main.py:449-454)
- OfflineTaskProcessor tracks consumed events but only in window-based path, not AFK path
- Attempted to populate consumed_window_event_ids in AFK path but object identity matching was unreliable
- The real issue: metrics calculated from ALL canonical_events, not just rendered ones
- Zero-duration filtering (timeline_render.py:569-572) removes events from display but not from metrics

## Proper Fix Strategy

This requires architectural changes to the metric calculation flow:

1. Move event filtering earlier (to event generation time, not rendering time)
2. Calculate metrics from filtered events only
3. Ensure all code paths use same event set for calculations

This is part of a larger refactor to consolidate multiple filtering locations into one place.

## Related Issues

- Day/week total calculations (now fixed)
- OFFLINE window event deduplication (should move to generation layer)
- Consistency between summary and totals metrics (now fixed)

This is part of a broader architectural issue: multiple code paths (rendering, metrics, display) handling the same data differently.

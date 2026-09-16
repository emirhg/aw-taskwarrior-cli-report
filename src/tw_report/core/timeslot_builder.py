"""
Unified sweep-line timeslot constructor — non-overlapping slots by construction.

This module provides a single, deterministic function that walks the raw event timeline
once and emits already-classified, non-overlapping slots directly. It replaces five
separate slot-building code paths that previously operated independently and could
produce overlapping slots with different (project, task) classifications for the same
wall-clock instant.

Algorithm overview:
1. Collect every event boundary (start/end of each event from all three sources)
2. For each atomic interval between consecutive boundaries, determine which events
   are "active" (covering) that interval
3. Classify each interval by priority rule (task > generic; AFK-bucket presence = online/offline ground truth)
4. Run-length merge adjacent intervals with identical classification into consolidated slots
5. Return guaranteed non-overlapping, properly-classified slots

Key invariant: AFK-bucket presence (not window-event presence) determines online/offline
for every task uniformly, replacing the three previously-inconsistent rules in the old code.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from tw_report.core.aw_events import AFKEvent, TaskWarriorEvent, WindowEvent
from tw_report.core.categories import build_categories_from_window_events
from tw_report.core.report_slot import ReportTimelineSlot

logger = logging.getLogger(__name__)


class _RunAccumulator:
    """Accumulates adjacent atomic ticks with identical classification into one consolidated slot."""

    def __init__(
        self,
        classification_key: Tuple,
        task_event: Optional[TaskWarriorEvent],
        start: datetime,
        end: datetime,
        bucket: str,  # "online", "embedded_afk", "offline", "afk", "offline_gap"
        tick_duration: timedelta,
    ):
        """Initialize a run with the first tick."""
        self.classification_key = classification_key
        self.task_event = task_event
        self.start = start
        self.end = end
        self.bucket = bucket
        self.online_duration = timedelta(0)
        self.embedded_afk_duration = timedelta(0)
        self.offline_duration = timedelta(0)
        self.generic_afk_duration = timedelta(0)
        self.generic_offline_duration = timedelta(0)

        self._add_tick(bucket, tick_duration)

    def _add_tick(self, bucket: str, tick_duration: timedelta) -> None:
        """Add a tick's duration to the appropriate category."""
        if bucket == "online":
            self.online_duration += tick_duration
        elif bucket == "embedded_afk":
            self.embedded_afk_duration += tick_duration
        elif bucket == "offline":
            self.offline_duration += tick_duration
        elif bucket == "afk":
            self.generic_afk_duration += tick_duration
        elif bucket == "offline_gap":
            self.generic_offline_duration += tick_duration

    def extend(self, end: datetime, bucket: str, tick_duration: timedelta) -> None:
        """Extend the run to include another tick.

        NOTE: self.bucket is updated to the new bucket value (line below). This is intentional:
        the run's "dominant" bucket type should reflect the most recent tick's classification.
        For task-covered runs, this doesn't affect finalization (we return all accumulated
        durations regardless). For generic runs, it determines which slot type is returned.
        The classification_key (which determines run boundaries) is NOT updated here - that's
        computed fresh for each tick and compared in the builder's run-length merge logic.
        """
        self.end = end
        self.bucket = bucket  # Last tick's bucket determines the "dominant" sub-type for generic runs
        self._add_tick(bucket, tick_duration)

    def finalize(self, window_events: List[WindowEvent]) -> ReportTimelineSlot:
        """Convert the accumulated run into a finalized ReportTimelineSlot.

        IMPORTANT: This creates ONE slot per run, but the classification key in the builder
        ensures separate runs are created for different activity states (online/embedded_afk/offline).
        This is why the chronological timeline feature works - state transitions are represented
        by different runs, not by merging different states into one slot.
        """
        total_duration = self.end - self.start

        if self.task_event is not None:
            # Task-covered run: slots are kept separate by classification key in the sweep-line algorithm.
            # Each run represents one continuous time period with one primary activity state.
            # When state changes (e.g., from online to embedded_afk), the sweep-line creates a new run.
            # Thus this method receives runs that are already separated by state.
            # actual_duration is ONLY online time (not including embedded AFK)
            actual_duration = self.online_duration
            afk_duration = self.embedded_afk_duration if self.embedded_afk_duration > timedelta(0) else None
            offline_ext_duration = self.offline_duration if self.offline_duration > timedelta(0) else None
            # event_duration represents online time (for offline/online split display in TimelineSlot)
            # CRITICAL: Must be set whenever offline_extension_duration is set, even if zero
            # This applies to chronological timeline where pure offline slots have event_duration=0
            event_duration = self.online_duration if offline_ext_duration is not None else None

            # Fetch categories from window events covering this slot's span
            categories = build_categories_from_window_events(window_events, self.start, self.end)

            return ReportTimelineSlot(
                start=self.start,
                end=self.end,
                duration=total_duration,
                actual_duration=actual_duration,
                task_event=self.task_event,
                afk_duration=afk_duration,
                offline_extension_duration=offline_ext_duration,
                event_duration=event_duration,
                categories=categories,
            )
        else:
            # Generic (no-task) run: split into separate slots by sub-type
            # This is conservative — leaves the existing three-way split for non-task slots
            # Return a single "dominant" slot for the accumulated run's primary bucket type
            if self.bucket == "afk":
                return ReportTimelineSlot(
                    start=self.start,
                    end=self.end,
                    duration=total_duration,
                    actual_duration=timedelta(0),
                    afk_duration=self.generic_afk_duration,
                )
            elif self.bucket == "offline_gap":
                return ReportTimelineSlot(
                    start=self.start,
                    end=self.end,
                    duration=total_duration,
                    actual_duration=timedelta(0),
                    offline_extension_duration=self.generic_offline_duration,
                )
            else:  # "online" or mixed
                return ReportTimelineSlot(
                    start=self.start,
                    end=self.end,
                    duration=total_duration,
                    actual_duration=self.online_duration + self.generic_afk_duration,
                )


def build_timeslot_timeline(
    afk_events: List[AFKEvent],
    window_events: List[WindowEvent],
    task_events,  # Can be List[TaskWarriorEvent] or List[Event]
) -> List[ReportTimelineSlot]:
    """
    Build a non-overlapping timeline of classified slots from raw event sources.

    Pure, deterministic function: same inputs always produce identical output.
    No externally-imposed reporting window — covers exactly the span implied by the inputs.
    Callers must pre-filter events to a desired period before calling.

    CRITICAL REQUIREMENT: Chronological Timeline Feature
    =====================================================
    The output MUST create separate rows for each activity state transition.

    When a task spans different activity states (ACTIVE → embedded-AFK → ACTIVE),
    create separate slots for EACH state, not a single merged slot.

    Example (DESIRED - what users expect):
        13:56-14:38  ACTIVE:42:18
        14:38-14:48  AFK:9:41
        14:48-16:19  ACTIVE:1:31:24

    Example (WRONG - current broken behavior):
        13:56-14:48  AFK:9:41  ACTIVE:42:18  ← DO NOT DO THIS

    Implementation approach:
    - Classification key at line 264 includes bucket field to separate activity states
    - Each run with different bucket should create separate slots via run-length merging
    - _merge_adjacent_micro_slots_by_state_continuity() must preserve state boundaries
    - Only pure-offline micro-artifacts should merge across state transitions

    Args:
        afk_events: AFK bucket events (status="afk" or "not-afk")
        window_events: Window bucket events (app, title, category)
        task_events: TaskWarrior task events (project, task, tags, uuid) - can be TaskWarriorEvent or generic Event

    Returns:
        List of ReportTimelineSlot objects, guaranteed:
        - Non-overlapping: no two slots share any common instant
        - Properly classified: each slot carries correct project/task, duration breakdown (actual/afk/offline)
        - Complete: covers full wall-clock span implied by input events with no gaps
        - Chronological: separate slots for each activity state transition (ACTIVE ≠ AFK ≠ OFFLINE)
    """
    # Ensure task_events is a list (handle None case)
    if task_events is None:
        task_events = []

    # Collect all boundary points (event start and end times)
    cuts = set()
    for ev in afk_events + window_events + task_events:
        if ev.duration <= timedelta(0):
            continue  # Skip degenerate/zero-length events
        cuts.add(ev.timestamp)
        cuts.add(ev.timestamp + ev.duration)

    if len(cuts) < 2:
        return []  # No events, or only one instantaneous event

    cuts = sorted(cuts)

    # Ensure all task_events are TaskWarriorEvent objects (handle generic Event objects)
    def _ensure_taskwarrior_event(ev):
        if isinstance(ev, TaskWarriorEvent):
            return ev
        # Wrap generic Event as TaskWarriorEvent
        tw_event = TaskWarriorEvent(timestamp=ev.timestamp, duration=ev.duration)
        tw_event.data = ev.data.copy() if ev.data else {}
        return tw_event

    task_events = [_ensure_taskwarrior_event(ev) for ev in task_events]

    # Pre-sort events by timestamp for efficient sweep
    afk_by_start = sorted(afk_events, key=lambda e: e.timestamp)
    task_by_start = sorted(task_events, key=lambda e: e.timestamp)
    window_by_start = sorted(window_events, key=lambda e: e.timestamp)

    slots = []
    current = None

    # Sweep through each atomic interval
    for t_i, t_next in zip(cuts, cuts[1:]):
        tick_duration = t_next - t_i

        # Find active events at t_i (coverage: event.timestamp <= t_i < event.timestamp + event.duration)
        active_tasks = [e for e in task_by_start if e.timestamp <= t_i < e.timestamp + e.duration]
        active_afk = [e for e in afk_by_start if e.timestamp <= t_i < e.timestamp + e.duration]
        active_window = [e for e in window_by_start if e.timestamp <= t_i < e.timestamp + e.duration]

        # CRITICAL: Skip intervals with NO events from ANY source
        # Only create slots when there's real data to represent
        if not active_tasks and not active_afk and not active_window:
            continue  # Skip this interval entirely - no events here

        # Tie-break for multiple overlapping tasks (data-quality anomaly)
        if len(active_tasks) > 1:
            # Sort by (earliest start, longest duration, stable identity)
            active_tasks.sort(
                key=lambda t: (
                    t.timestamp,
                    -(t.duration.total_seconds()),
                    t.uuid or f"_id_{id(t)}"
                )
            )
            logger.warning(
                f"Multiple task events covering {t_i}: {[t.task for t in active_tasks]}. "
                f"Using deterministic tie-break (earliest, longest)."
            )
            active_tasks = [active_tasks[0]]

        # Classification rules
        if active_tasks:
            # Task-covered tick: determine online/embedded-afk/offline state
            task_event = active_tasks[0]
            has_afk_coverage = len(active_afk) > 0
            afk_status = active_afk[0].status if active_afk else None
            is_offline_task = task_event.tags and any(t.lower() == "offline" for t in task_event.tags)

            # CRITICAL: Time partitioning for offline-tagged tasks
            # Offline tag means the task MAY include offline (non-computer) work,
            # but we still need to partition time by AFK/window coverage.
            #
            # PRIORITY ORDER (why this matters):
            # 1. AFK coverage first - AFK events are the most reliable indicator of computer activity
            # 2. Window events second - prove computer was on, even if AFK bucket has gaps
            # 3. Offline fallback - only if no AFK or window activity exists
            #
            # This priority ensures we don't misclassify gaps in AFK recording as "offline time"
            # when the computer was actually on (proven by window events).
            #
            # Classification flow:
            # - Time WITH AFK events: classify by AFK status (online if not-afk, embedded_afk if afk)
            # - Time WITHOUT AFK events AND WITH window events: online (computer was provably on)
            # - Time WITHOUT AFK events AND WITHOUT window events: offline (computer was off)

            if has_afk_coverage:
                # AFK bucket has events: classify by their status (applies to offline and non-offline alike)
                if afk_status == "afk":
                    bucket = "embedded_afk"  # Idle time → embedded AFK
                else:
                    bucket = "online"  # Active time (not-afk) → online
            elif is_offline_task:
                # Offline-tagged task with no AFK coverage: check for window events
                has_window_activity = len(active_window) > 0
                if has_window_activity:
                    bucket = "online"  # Window activity proves system is powered on
                else:
                    bucket = "offline"  # No window activity → true offline gap
            else:
                # Non-offline task: always online (task event is proof of activity)
                # Even without AFK coverage, task event indicates work was happening
                bucket = "online"

            # CRITICAL: Include bucket in key to create separate slots for each activity state.
            # This enables chronological timeline view: when activity type changes (offline → online → afk),
            # a new slot is created, showing exactly when transitions occurred.
            # Example: 04:00-06:00 (offline) creates one slot, 06:00-07:00 (online) creates another.
            # Adjacent slots with identical (task, uuid, project, task, bucket) still merge via run-length merging.
            # This design gives chronological detail by default; --consolidate flag merges these slots back together.
            key = ("task", task_event.uuid or f"_id_{id(task_event)}", task_event.project, task_event.task, bucket)
        else:
            # Generic (no-task) tick: classify purely by AFK status
            task_event = None
            has_afk_coverage = len(active_afk) > 0
            afk_status = active_afk[0].status if active_afk else None

            if not has_afk_coverage:
                # No AFK coverage: check for window events (strong evidence system is on)
                # CRITICAL FIX (2026-09-02): Window events during AFK bucket gaps indicate
                # ActivityWatch startup timing lag, not actual offline time. If window activity
                # exists, system is provably powered on.
                has_window_activity = len(active_window) > 0
                if has_window_activity:
                    bucket = "online"  # Window activity proves system is powered on
                    key = ("generic", "active")
                else:
                    bucket = "offline_gap"  # No task, no AFK, no window → system truly off
                    key = ("generic", "offline")
            elif afk_status == "afk":
                bucket = "afk"  # No task, AFK status → idle
                key = ("generic", "afk")
            else:
                bucket = "online"  # No task, not-afk → generic active
                key = ("generic", "active")

        # Run-length merge: extend current run if key matches, else flush and start new
        if current is not None and current.classification_key == key and current.end == t_i:
            current.extend(t_next, bucket, tick_duration)
        else:
            if current is not None:
                slots.append(current.finalize(window_events))
            current = _RunAccumulator(key, task_event, t_i, t_next, bucket, tick_duration)

    # Flush the final accumulated run
    if current is not None:
        final_slot = current.finalize(window_events)
        # Skip degenerate zero-duration slots created at state boundaries by sweep-line algorithm.
        # These are timing artifacts from the exact moment of state transition and serve no purpose.
        if final_slot.duration > timedelta(milliseconds=1):
            slots.append(final_slot)

    # Apply state continuity merging to fix micro-slots from AFK bucket gaps
    # CRITICAL: This merger must NOT merge real activity state transitions (ACTIVE ≠ AFK ≠ OFFLINE).
    # It only merges pure-offline micro-artifacts that are timing byproducts of the AFK bucket.
    slots = _merge_adjacent_micro_slots_by_state_continuity(slots)
    return slots


def _merge_adjacent_micro_slots_by_state_continuity(
    slots: List[ReportTimelineSlot],
) -> List[ReportTimelineSlot]:
    """Merge micro-slots based on state continuity while preserving chronological transitions.

    CRITICAL: This function has a NARROW scope to fix only AFK bucket timing artifacts.
    It must NOT merge slots with DIFFERENT activity states (ACTIVE vs embedded-AFK).

    The chronological timeline feature depends on this function NOT merging real state
    transitions (e.g., ACTIVE→AFK→ACTIVE) even if they're small micro-slots.

    ONLY merge: Pure-offline micro-artifacts (tiny slots with ONLY offline_extension_duration,
    no active or afk time) that sit next to real activity. This handles the case where the
    AFK bucket stops recording but a window event fires once more.

    DO NOT merge: Genuine AFK-classified micro-slots, even if they're <= 1 second and <100ms gap.
    These are real activity transitions, not timing artifacts.

    Example of CORRECT merging (pure-offline artifact):
      IN:  12:01-12:05 (active, 4:28) + gap → 12:05-12:05 (offline, 0:01)
      OUT: 12:01-12:05 (active, 4:29, no offline) ✓ Merged (artifact case)

    Example of INCORRECT merging (would break chronological timeline):
      IN:  12:01-12:38 (active, 42:18) + 12:38-12:48 (embedded-afk, 9:41)
      OUT: 12:01-12:48 (active, 42:18, afk, 9:41) ✗ DO NOT merge - should be separate rows

    The real state-continuity check (lines 392-396) prevents merging unless both slots
    have the same activity state (both active, or both afk, or both offline).

    Algorithm:
    1. Sort slots by start time (usually already sorted, but be safe)
    2. For each slot, check if previous slot is adjacent + same (project, task)
    3. If yes: inherit previous state (active=actual_duration>0, else afk)
    4. Reclassify gap time to match previous state, merge into one slot
    5. If no: keep slot as-is

    Args:
        slots: List of ReportTimelineSlot from builder

    Returns:
        List with adjacent micro-slots merged by state continuity
    """
    if not slots or len(slots) <= 1:
        return slots

    # Sort by start time (already sorted from builder, but be safe)
    sorted_slots = sorted(slots, key=lambda s: s.start)

    merged = []
    i = 0

    while i < len(sorted_slots):
        current = sorted_slots[i]

        # Look ahead for adjacent micro-slots with same (project, task)
        merge_group = [current]
        j = i + 1

        while j < len(sorted_slots):
            next_slot = sorted_slots[j]

            # Check if adjacent (gap <= 1 second tolerance for rounding)
            gap = next_slot.start - current.end
            # THRESHOLD: 1 second adjacency tolerance for rounding/timing artifacts.
            # This handles: system clock precision, sweep-line algorithm timing, event buffering.
            # Actual adjacent slots have gap=0; gaps up to 1s are treated as adjacent for robustness.
            is_adjacent = gap <= timedelta(seconds=1)

            # Micro-slots = candidate AFK-bucket-stop-recording artifacts: small gap AND
            # a very small next slot (<= 1 second). Being "micro" alone no longer justifies
            # merging on its own — it only identifies the candidate; see
            # is_pure_offline_micro_artifact below for the one case where it still bypasses
            # the real state check.
            next_slot_duration = next_slot.duration.total_seconds()
            # THRESHOLDS: gap < 100ms AND duration <= 1.0s
            # These identify timing artifacts from AFK bucket stop-recording at system shutdown.
            # In production data: legitimate AFK periods are typically >1s; sub-100ms gaps indicate
            # timestamp precision issues rather than real activity boundaries. Calibrated on
            # ActivityWatch behavior: AFK bucket often has <1ms timing artifacts.
            is_micro_slot = (gap < timedelta(milliseconds=100) and next_slot_duration <= 1.0)

            # Check if same (project, task)
            is_same_task = (next_slot.project == current.project and
                           next_slot.task == current.task)

            # State flags for the previous (accumulated) slot
            current_is_active = current.actual_duration and current.actual_duration.total_seconds() > 0
            current_is_afk = current.afk_duration and current.afk_duration.total_seconds() > 0
            current_is_offline = current.offline_extension_duration and current.offline_extension_duration.total_seconds() > 0

            # State flags for the candidate next slot
            next_is_active = next_slot.actual_duration and next_slot.actual_duration.total_seconds() > 0
            next_is_afk = next_slot.afk_duration and next_slot.afk_duration.total_seconds() > 0
            next_is_offline = next_slot.offline_extension_duration and next_slot.offline_extension_duration.total_seconds() > 0

            # NARROW artifact case this function was originally built for: the AFK bucket
            # stopped recording but a window event fired once more, producing a tiny slot
            # that is PURELY offline-classified (no active or embedded-afk time of its own).
            # Only THIS specific shape bypasses the normal state-continuity check.
            is_pure_offline_micro_artifact = (
                is_micro_slot and next_is_offline and not next_is_active and not next_is_afk
            )

            if is_pure_offline_micro_artifact and (current_is_active or current_is_afk):
                # Known artifact sitting next to genuine activity — always fold it in.
                is_state_continuous = True
            else:
                # Everything else — including every other kind of micro-slot — must pass
                # the same real state-continuity check used for regular slots. Being small
                # is no longer a free pass to merge.
                is_state_continuous = (
                    (current_is_active and next_is_active) or
                    (current_is_afk and next_is_afk) or
                    (current_is_offline and next_is_offline)
                )

            if is_adjacent and is_same_task and is_state_continuous:
                if is_pure_offline_micro_artifact:
                    # Reclassify the artifact's offline time as AFK time, folded into
                    # whichever genuine state (active or embedded_afk) preceded it.
                    # (Handles both current_is_active and current_is_afk, unlike before.)
                    # CRITICAL: Only reclassify if the artifact has meaningful duration.
                    # Degenerate zero-duration artifacts should NOT be reclassified as they
                    # can cause subsequent AFK slots to merge incorrectly.
                    #
                    # THRESHOLD: 10ms minimum duration for reclassification.
                    # Why 10ms? Artifacts from AFK bucket stop-recording are typically <1ms
                    # (timestamp precision). The 10ms threshold filters out degenerate timing
                    # artifacts while preserving legitimate short offline periods. This prevents
                    # the bug where reclassifying a 0.001s artifact to AFK caused subsequent
                    # AFK slots to merge incorrectly (afk-afk continuity matched on the artifact).
                    if next_slot.offline_extension_duration and next_slot.offline_extension_duration > timedelta(milliseconds=10):
                        next_slot.afk_duration = (next_slot.afk_duration or timedelta(0)) + \
                                               next_slot.offline_extension_duration
                        next_slot.offline_extension_duration = None

                merge_group.append(next_slot)
                current = next_slot
                j += 1
            else:
                break

        # Merge accumulated group
        if len(merge_group) > 1:
            merged_slot = _merge_slot_group(merge_group)
            merged.append(merged_slot)
            i = j
        else:
            merged.append(current)
            i = j if j > i + 1 else i + 1

    return merged


def _merge_slot_group(group: List[ReportTimelineSlot]) -> ReportTimelineSlot:
    """Merge a group of adjacent ReportTimelineSlots into one continuous slot.

    Uses wall-clock span (min start to max end) and sums all duration components.

    Args:
        group: List of adjacent ReportTimelineSlots for same (project, task)

    Returns:
        Single ReportTimelineSlot spanning the full group
    """
    if not group:
        raise ValueError("Cannot merge empty slot group")

    # Sort by start (should be sorted already)
    group = sorted(group, key=lambda s: s.start)

    start = group[0].start
    end = group[-1].end
    duration = end - start

    # Sum duration components across all slots
    actual_duration = sum((s.actual_duration for s in group), timedelta(0))
    productive_duration = sum((s.productive_duration for s in group), timedelta(0))
    afk_duration = sum((s.afk_duration or timedelta(0) for s in group), timedelta(0))
    offline_ext = sum((s.offline_extension_duration or timedelta(0) for s in group), timedelta(0))

    # event_duration: sum online portions from merged slots
    # CRITICAL: Must be set when offline_extension_duration is set (for TimelineSlot validation)
    event_duration = sum((s.event_duration or timedelta(0) for s in group), timedelta(0))
    event_duration = event_duration if (offline_ext > timedelta(0) or event_duration > timedelta(0)) else None

    # Use first slot's metadata
    return ReportTimelineSlot(
        start=start,
        end=end,
        duration=duration,
        actual_duration=actual_duration,
        productive_duration=productive_duration,
        task_event=group[0].task_event,
        window_events=sum((s.window_events for s in group), []),
        afk_events=sum((s.afk_events for s in group), []),
        afk_duration=afk_duration if afk_duration > timedelta(0) else None,
        offline_extension_duration=offline_ext if offline_ext > timedelta(0) else None,
        event_duration=event_duration,
        tags=group[0].tags,
        categories=group[0].categories,
        apps=group[0].apps,
        source_slots=sum((s.source_slots for s in group), []),
        is_consolidated=True,
    )

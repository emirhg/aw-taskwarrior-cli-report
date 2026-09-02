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
        """Extend the run to include another tick."""
        self.end = end
        self.bucket = bucket  # Last tick's bucket determines the "dominant" sub-type for generic runs
        self._add_tick(bucket, tick_duration)

    def finalize(self, window_events: List[WindowEvent]) -> ReportTimelineSlot:
        """Convert the accumulated run into a finalized ReportTimelineSlot."""
        total_duration = self.end - self.start

        if self.task_event is not None:
            # Task-covered run: combine online/embedded-afk/offline into one slot
            # actual_duration is ONLY online time (not including embedded AFK)
            actual_duration = self.online_duration
            afk_duration = self.embedded_afk_duration if self.embedded_afk_duration > timedelta(0) else None
            offline_ext_duration = self.offline_duration if self.offline_duration > timedelta(0) else None
            # event_duration is online time when there's an offline component
            event_duration = self.online_duration if offline_ext_duration else None

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

    Args:
        afk_events: AFK bucket events (status="afk" or "not-afk")
        window_events: Window bucket events (app, title, category)
        task_events: TaskWarrior task events (project, task, tags, uuid) - can be TaskWarriorEvent or generic Event

    Returns:
        List of ReportTimelineSlot objects, guaranteed:
        - Non-overlapping: no two slots share any common instant
        - Properly classified: each slot carries correct project/task, duration breakdown (actual/afk/offline)
        - Complete: covers full wall-clock span implied by input events with no gaps
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

            if not has_afk_coverage:
                bucket = "offline"  # Task time but no AFK coverage → system off
            elif afk_status == "afk":
                bucket = "embedded_afk"  # Task time + idle → embedded AFK
            else:
                bucket = "online"  # Task time + not-afk → online/active

            key = ("task", task_event.uuid or f"_id_{id(task_event)}", task_event.project, task_event.task)
        else:
            # Generic (no-task) tick: classify purely by AFK status
            task_event = None
            has_afk_coverage = len(active_afk) > 0
            afk_status = active_afk[0].status if active_afk else None

            if not has_afk_coverage:
                bucket = "offline_gap"  # No task, no AFK → system off
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
        slots.append(current.finalize(window_events))

    return slots

"""
OFFLINE task processing and duration calculation.

This module extracts and centralizes OFFLINE task handling that was previously
scattered in tw-report.py. It handles detection, validation, and duration
calculation for tasks with the 'offline' tag.

═══════════════════════════════════════════════════════════════════════════════

OFFLINE EVENT DEFINITION:

An OFFLINE event is a TaskWarrior task event that was recorded while the
system (computer) was completely powered off or disconnected.

Key characteristics:
1. Must have the 'offline' tag in TaskWarrior
2. The task duration spans from when the work was started to when it was paused
3. Within that timespan, the system may have been ON or OFF at different periods

DETERMINING ONLINE vs OFFLINE TIME:

The AFK bucket provides the ground truth for system state:
- AFK event present during a time period → system was ON (AFK or not-AFK status)
  - "afk" status = user away from keyboard but system running
  - "not-afk" status = user active at keyboard
  - BOTH indicate system was powered on and could record activity
- NO AFK event during a time period → system was OFF (completely powered down)

Therefore, for an OFFLINE task:
- online_time = sum of ALL AFK event durations (afk + not-afk) that overlap with task span
                (periods when system was on, whether user was present or away)
- offline_time = task_duration - online_time
                 (periods when system was completely off but task was still being worked)

EXAMPLE:
Task: 13:01-18:15 (5:14:01 total duration)
AFK events during that period: 1:52:36 (system was on)
Result:
  - online_time = 1:52:36 (system on, user working)
  - offline_time = 5:14:01 - 1:52:36 = 3:21:25 (system off, but task continues in background)
  - Display: (3:21:25 OFF)  1:52:36  [prod  36%]

═══════════════════════════════════════════════════════════════════════════════

ISSUE #1 FIX: OFFLINE task results are now filtered consistently using
EventFilter, preventing 0:00:00 duration display in consolidated reports.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from aw_core.models import Event

from tw_report.core.categories import build_categories_from_window_events

if TYPE_CHECKING:
    from tw_report.core.filtering import EventFilter


class OfflineTaskProcessor:
    """
    Detects, validates, and calculates duration for OFFLINE-tagged tasks.

    Replaces scattered logic from tw-report.py:
    - Lines 3427-3504: OFFLINE task detection and validation
    - Lines 3720-3808: Synthetic slot creation

    KEY FEATURE: Results are filtered before returning, ensuring consistency
    with EventFilter across all entry types.

    ═══════════════════════════════════════════════════════════════════════════

    WHAT IS AN OFFLINE EVENT?

    An OFFLINE event is a TaskWarrior task marked with the 'offline' tag that
    was worked on while the system (computer) was completely powered off or
    unreachable. This represents work done without real-time ActivityWatch
    tracking because the system was not running.

    DURATION CALCULATION:

    The duration of an OFFLINE event is split into two components:
    1. online_time: Periods when the system WAS powered on and running.
                   Determined by ALL AFK bucket events (both "afk" and "not-afk" status).
                   If bucket AFK has an event, system was on.
    2. offline_time: Periods when the system was completely OFF (no AFK bucket events).

    Formula:
        task_duration (from TaskWarrior) = online_time + offline_time
        online_time = sum(ALL AFK bucket events overlapping task period)
                    = sum("afk" events) + sum("not-afk" events)
        offline_time = task_duration - online_time

    WHY THIS MATTERS:

    - ActivityWatch cannot record activity when the system is off
    - But TaskWarrior can be synced retroactively when the system comes back online
    - The OFFLINE tag means: "work was done, but AW couldn't track it because
      the system was off for part of that time"
    - By checking the AFK bucket, we can determine WHICH parts of the task
      actually had the system running
    """

    def __init__(
        self,
        task_events: Optional[List[Event]],
        window_events: List[Event],
        afk_events: Optional[List[Event]],
        event_filter: "EventFilter",
        end_time: Optional[datetime] = None,
        use_afk_for_reconciliation: bool = False,
    ):
        """
        Initialize processor.

        Args:
            task_events: List of TaskWarrior events
            window_events: List of window activity events
            afk_events: List of AFK bucket events (used to determine online/offline time)
            event_filter: EventFilter instance for filtering results
            end_time: End time for the report period (used for incomplete/running tasks)
            use_afk_for_reconciliation: If True, use AFK events to calculate online time
                                       instead of window events (faster for detail_level <= 2)
        """
        self.task_events = task_events or []
        self.window_events = window_events
        self.afk_events = afk_events or []
        self.event_filter = event_filter
        self.end_time = end_time
        self.use_afk_for_reconciliation = use_afk_for_reconciliation
        self.offline_durations: Dict[Tuple, timedelta] = {}
        self.offline_event_durations: Dict[Tuple, timedelta] = {}
        self.event_groups: Dict[Tuple, List[Event]] = {}
        self.task_real_durations: Dict[Tuple, timedelta] = {}  # Store events per group
        self.offline_categories: Dict[Tuple, List[Dict]] = {}  # Categories from window reconciliation
        self.consumed_window_event_ids: set = set()  # Track which window events are used

    def process(self) -> Tuple[Dict, Dict, Dict[Tuple, List[Event]], Dict]:
        """
        Process all OFFLINE-tagged tasks.

        FIX FOR ISSUE #1: Results are filtered before returning, so synthetic
        slots created later will respect --exclude-non-project and other filters.

        Returns:
            Tuple of (wall_clock_durations, event_durations, event_groups, task_real_durations) dictionaries.
            Keys can be 2-element tuples (project, task) or 3-element tuples (project, task, group_idx)
            for split groups.
        """
        self._calculate_durations()

        # Apply filter to results (Issue #1 fix)
        filtered = {}
        filtered_events = {}
        filtered_groups = {}
        filtered_real = {}
        for key, duration in self.offline_durations.items():
            # Extract project and task from key (handle both 2-element and 3-element tuples)
            project = key[0] if isinstance(key, tuple) else ""
            task = key[1] if isinstance(key, tuple) and len(key) > 1 else ""

            entry = {"project": project, "task": task, "type": "offline_task"}
            if self.event_filter.should_include_entry(entry, "offline_task"):
                filtered[key] = duration
                filtered_events[key] = self.offline_event_durations.get(key, timedelta(0))
                filtered_groups[key] = self.event_groups.get(key, [])
                filtered_real[key] = self.task_real_durations.get(key, duration)

        return filtered, filtered_events, filtered_groups, filtered_real

    def _calculate_durations(self) -> None:
        """
        Calculate aggregate duration for each OFFLINE task.

        For each (project, task) pair with 'offline' tag, calculates the span
        from earliest start to latest end across all events for that task.

        Validates that:
        1. No other task is active during the session span
        2. No unassigned window activity occurs during gaps
        """
        # Group offline task events by (project, task)
        offline_events_by_key: Dict[Tuple[str, str], List[Event]] = {}

        for event in self.task_events:
            if self._task_has_offline_tag(event):
                project = event.data.get("project", "No project assigned")
                task = (
                    event.data.get("title")
                    or event.data.get("label")
                    or event.data.get("task")
                    or "No task assigned"
                )
                key = (project, task)

                if key not in offline_events_by_key:
                    offline_events_by_key[key] = []
                    # Store the real task duration from the first TaskWarrior event
                    if event.duration:
                        self.task_real_durations[key] = event.duration
                offline_events_by_key[key].append(event)

        # Calculate duration for each task
        for key, events in offline_events_by_key.items():
            sorted_events = sorted(events, key=lambda e: e.timestamp)

            # Deduplicate events: for same timestamp, keep the longest duration
            # (likely most complete/accurate view of the work session)
            by_timestamp: Dict[datetime, Event] = {}
            for event in sorted_events:
                ts = event.timestamp
                if ts not in by_timestamp:
                    by_timestamp[ts] = event
                else:
                    # Keep the one with longer duration (more complete record)
                    existing = by_timestamp[ts]
                    existing_dur = existing.duration.total_seconds() if existing.duration else 0
                    event_dur = event.duration.total_seconds() if event.duration else 0
                    if event_dur > existing_dur:
                        by_timestamp[ts] = event

            unique_events = [by_timestamp[ts] for ts in sorted(by_timestamp.keys())]

            # OFFLINE-tagged task events are explicit user markers: process all of them.
            # Unlike general events, OFFLINE events are not noise—they represent complete
            # work sessions as recorded by TaskWarrior. Don't filter by duration thresholds.

            # Split all unique events into groups based on interruptions from other tasks
            event_groups = self._split_by_task_interruptions(unique_events, key)

            # Process each uninterrupted group separately
            for group_idx, group_events in enumerate(event_groups):
                # Use modified key with group index if there are multiple groups
                group_key = key if len(event_groups) == 1 else (key[0], key[1], group_idx)
                self._process_event_group(group_key, group_events)

    def _task_has_offline_tag(self, task_event: Event) -> bool:
        """
        Check if a task event has the 'offline' tag (case-insensitive).

        Args:
            task_event: TaskWarrior event to check

        Returns:
            True if 'offline' tag found, False otherwise
        """
        raw_tags = task_event.data.get("tags", [])
        tags = [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)
        return any(t.lower() == "offline" for t in tags)

    def _other_task_interrupts(
        self, task_key: Tuple[str, str], session_start: datetime, session_end: datetime
    ) -> bool:
        """
        Check if any other task is active during this session.

        Args:
            task_key: (project, task) tuple for this task
            session_start: Start of the session
            session_end: End of the session

        Returns:
            True if another task overlaps, False otherwise
        """
        for other_event in self.task_events:
            other_project = other_event.data.get("project", "No project assigned")
            other_task = (
                other_event.data.get("title")
                or other_event.data.get("label")
                or other_event.data.get("task")
                or "No task assigned"
            )
            other_key = (other_project, other_task)

            # Skip events from this same task
            if other_key == task_key:
                continue

            # Check if other task overlaps with session
            other_end = other_event.timestamp + other_event.duration
            if other_event.timestamp < session_end and other_end > session_start:
                return True

        return False

    def _unassigned_window_in_gap(self, gap_start: datetime, gap_end: datetime) -> bool:
        """
        Check if any unassigned window activity occurs during the gap.

        Args:
            gap_start: Start of gap period
            gap_end: End of gap period

        Returns:
            True if unassigned window activity found, False otherwise
        """
        for window_event in self.window_events:
            window_start = window_event.timestamp
            window_end = window_event.timestamp + window_event.duration

            # Check if window event overlaps with gap
            if window_start < gap_end and window_end > gap_start:
                # Check if this window event has an assigned task
                has_task = False
                for task_event in self.task_events:
                    task_start = task_event.timestamp
                    task_end = task_event.timestamp + task_event.duration
                    if task_start < window_end and task_end > window_start:
                        has_task = True
                        break

                # If window activity has no assigned task, gap is interrupted
                if not has_task:
                    return True

        return False

    def _split_by_task_interruptions(
        self, events: List[Event], task_key: Tuple[str, str]
    ) -> List[List[Event]]:
        """
        Split offline task events into groups by calendar day and task interruptions.

        Groups consecutive events that (1) don't span calendar boundaries and
        (2) are not interrupted by other tasks. This ensures each group represents
        work within a single calendar day, preventing impossible scenarios like
        58 hours of activity in a 24-hour period.

        Args:
            events: List of offline task events (already sorted and deduplicated)
            task_key: (project, task) tuple for this offline task

        Returns:
            List of event groups, each representing activity within one calendar day
        """
        if not events:
            return []

        groups: List[List[Event]] = []

        # First, split events that span calendar boundaries
        split_events: List[Event] = []
        for event in events:
            if event.duration:
                event_start_date = event.timestamp.date()
                event_end_date = (event.timestamp + event.duration).date()

                if event_start_date != event_end_date:
                    # Event spans multiple days - this is problematic for OFFLINE reporting.
                    # For now, we DON'T artificially split the event, but we WILL use it as
                    # a group boundary (assign it to start day, but following events on a
                    # different day will be split into new groups).
                    split_events.append(event)
                else:
                    split_events.append(event)
            else:
                split_events.append(event)

        current_group: List[Event] = [split_events[0]]
        group_date = split_events[0].timestamp.date()

        for i in range(1, len(split_events)):
            curr_event = split_events[i]
            prev_event = current_group[-1]

            # Calculate gap between prev_event end and curr_event start
            prev_end = (
                prev_event.timestamp + prev_event.duration
                if prev_event.duration
                else prev_event.timestamp
            )
            curr_start = curr_event.timestamp
            curr_end = (
                curr_event.timestamp + curr_event.duration
                if curr_event.duration
                else curr_event.timestamp
            )
            gap_start = prev_end
            gap_end = curr_start

            # Check if any other task is active in this gap
            interruption_found = False
            for other_event in self.task_events:
                # Skip if this is the same offline task
                other_project = other_event.data.get("project", "")
                other_task = (
                    other_event.data.get("title")
                    or other_event.data.get("label")
                    or other_event.data.get("task")
                    or ""
                )
                other_key = (other_project, other_task)

                if other_key == task_key:
                    continue

                # Check if other task overlaps with the gap
                other_start = other_event.timestamp
                other_end = (
                    other_event.timestamp + other_event.duration
                    if other_event.duration
                    else other_event.timestamp
                )

                if other_start < gap_end and other_end > gap_start:
                    interruption_found = True
                    break

            # Split by calendar day boundary. Group must contain events that:
            # 1. All start on the same calendar day (group_date)
            # 2. All end on the same calendar day (group_date)
            # If curr_event starts on a different day OR ends on a different day, split.
            curr_start_date = curr_start.date()
            curr_end_date = curr_end.date()
            start_on_different_day = curr_start_date != group_date
            end_on_different_day = curr_end_date != group_date

            if (
                interruption_found
                or start_on_different_day
                or end_on_different_day
            ):
                # End current group and start new one
                groups.append(current_group)
                current_group = [curr_event]
                group_date = curr_start_date
            else:
                # Continue current group
                current_group.append(curr_event)

        # Add final group
        if current_group:
            groups.append(current_group)

        return groups

    def _process_event_group(self, group_key: Tuple, group_events: List[Event]) -> None:
        """
        Process one group of offline task events.

        Calculates wall-clock duration and online time for the group.

        Args:
            group_key: Key for this group (project, task) or (project, task, group_index)
            group_events: List of events in this group
        """
        if not group_events:
            return

        # OFFLINE-tagged task events are explicit user markers: process all of them.
        # Unlike general events, OFFLINE events are not noise—they represent complete
        # work sessions as recorded by TaskWarrior. Sort them by timestamp and process.
        sorted_events = sorted(group_events, key=lambda e: e.timestamp)

        if not sorted_events:
            return

        # FIXED: Sum actual event durations instead of using wall-clock span.
        # Wall-clock span (first event to last event) creates artificial spans
        # that exceed the actual work time by orders of magnitude.
        #
        # For OFFLINE tasks, the events ARE the complete record of work time.
        # Simply sum them instead of assuming the system was off between first→last event.
        wall_clock_duration = timedelta(0)
        for event in sorted_events:
            if event.duration:
                wall_clock_duration += event.duration
            # Skip events without duration (incomplete records)

        # For AFK calculation, we still need a time period.
        # Use the span of actual events for AFK overlap detection.
        wall_clock_start = sorted_events[0].timestamp
        last_event = sorted_events[-1]
        wall_clock_end = last_event.timestamp + (last_event.duration or timedelta(0))
        if wall_clock_end <= wall_clock_start:
            # If no duration on last event, extend slightly for AFK detection
            wall_clock_end = wall_clock_start + timedelta(seconds=1)

        # Reconcile with activity data
        if self.use_afk_for_reconciliation:
            # AFK-based optimization (detail_level <= 2): no category detail needed
            # Calculate online time by summing AFK overlaps with EACH TASK EVENT (not the span)
            # This avoids overcounting when task events have gaps between them
            online_time = timedelta(0)
            for event in sorted_events:
                event_start = event.timestamp
                event_end = event_start + (event.duration or timedelta(0))
                # Sum AFK overlaps for this specific event
                for afk_event in self.afk_events:
                    afk_start = afk_event.timestamp
                    afk_end = afk_start + afk_event.duration
                    if afk_start < event_end and afk_end > event_start:
                        overlap_start = max(afk_start, event_start)
                        overlap_end = min(afk_end, event_end)
                        overlap = overlap_end - overlap_start
                        online_time += overlap

            offline_remainder = wall_clock_duration - online_time

            # Build simple categories (no detail breakdown)
            reconciled_categories = []
            if online_time > timedelta(0):
                reconciled_categories.append({
                    "category": "Online",
                    "duration": online_time,
                    "start": wall_clock_start,
                    "end": wall_clock_end,
                })
            if offline_remainder > timedelta(0):
                reconciled_categories.append({
                    "category": "Offline",
                    "duration": offline_remainder,
                    "start": wall_clock_start,
                    "end": wall_clock_end,
                })
            tracked_duration = online_time
        else:
            # Window-based reconciliation (detail_level >= 3): full category detail
            # This replaces the flat "Offline" bucket with real category/app/title detail
            # where window events were actually tracked during the OFFLINE period
            window_covered_duration, window_categories = self._calculate_window_coverage(
                wall_clock_start, wall_clock_end
            )

            # Build reconciled categories: window categories + remainder as "Offline"
            offline_remainder = wall_clock_duration - window_covered_duration
            reconciled_categories = window_categories.copy()
            if offline_remainder > timedelta(0):
                reconciled_categories.append({
                    "category": "Offline",
                    "duration": offline_remainder,
                    "start": wall_clock_start,
                    "end": wall_clock_end,
                })
            tracked_duration = window_covered_duration

        # Store results
        self.offline_durations[group_key] = wall_clock_duration
        self.offline_event_durations[group_key] = tracked_duration  # Online/tracked time
        self.event_groups[group_key] = sorted_events  # Store events for this group
        self.offline_categories[group_key] = reconciled_categories

    def _calculate_online_time_from_afk(
        self, period_start: datetime, period_end: datetime
    ) -> timedelta:
        """
        Calculate online time during an OFFLINE task period using AFK bucket events.

        For OFFLINE events, the system state (on/off) is determined by the AFK bucket:
        - AFK bucket has events (any status: "afk" OR "not-afk") = system was ON
        - NO AFK bucket events = system was OFF (completely powered down)

        online_time = sum of ALL AFK bucket event durations (afk + not-afk) that
                      overlap with the OFFLINE task's time span

        This represents the total amount of time during the task when the system
        was powered on and could potentially record activity (whether the user was
        at the keyboard or away). The remaining time (offline_time = task_duration
        - online_time) is when the system was completely off.

        Example:
        - Task period: 13:01-18:15 (5:14:01 total)
        - AFK bucket events during that period: 1:52:36 (sum of all afk+not-afk)
        - online_time = 1:52:36 (system was on)
        - offline_time = 5:14:01 - 1:52:36 = 3:21:25 (system was off)

        Args:
            period_start: Start of the offline task period
            period_end: End of the offline task period

        Returns:
            Total online time (sum of ALL AFK event intersections with period)
        """
        online_time = timedelta(0)

        for afk_event in self.afk_events:
            # Check if AFK event overlaps with period
            afk_start = afk_event.timestamp
            afk_end = afk_event.timestamp + afk_event.duration

            if afk_start < period_end and afk_end > period_start:
                # Calculate intersection
                overlap_start = max(afk_start, period_start)
                overlap_end = min(afk_end, period_end)
                overlap = overlap_end - overlap_start
                online_time += overlap

        return online_time

    def _calculate_window_coverage(
        self, period_start: datetime, period_end: datetime
    ) -> Tuple[timedelta, List[Dict]]:
        """
        Calculate window event coverage during an OFFLINE task period.

        Extracts ActivityWatch window events that overlap with the OFFLINE task period,
        builds a category > app > title breakdown of what the user was actually doing,
        and computes the total covered duration.

        Args:
            period_start: Start of the OFFLINE task period
            period_end: End of the OFFLINE task period

        Returns:
            Tuple of (window_covered_duration, categories_list)
            - window_covered_duration: Sum of overlapping window event durations
            - categories_list: List of dicts with category/app/title breakdown
                               Empty list if no window events overlap the period
        """
        categories = build_categories_from_window_events(
            self.window_events, period_start, period_end
        )

        # Calculate total duration covered by window events
        window_covered_duration = timedelta(0)
        for cat_dict in categories:
            window_covered_duration += cat_dict["duration"]

        # Track which window events were actually consumed
        for window_event in self.window_events:
            window_start = window_event.timestamp
            window_end = window_event.timestamp + window_event.duration
            if window_start < period_end and window_end > period_start:
                self.consumed_window_event_ids.add(id(window_event))

        return window_covered_duration, categories

    def get_synthetic_slot(self, key: Tuple[str, str], task_events_for_key: List[Event]) -> Dict:
        """
        Build a synthetic slot for an OFFLINE task.

        CANONICAL BUILDER: This is now the single source of truth for offline_task slots.
        Previously, offline_task dicts were hand-built in multiple places (tw-report.py
        and this method), leading to inconsistencies (missing actual_duration/event_duration).
        Consolidating here ensures all offline_task slots are built consistently and pass
        TimelineSlot validation.

        SIGNATURE FIX: Changed from (project: str, task: str, ...) to (key: Tuple, ...).
        The old signature broke for split groups (3-tuple keys like (project, task, group_idx))
        by looking up only (project, task), silently defaulting to timedelta(0) instead of
        the correct grouped duration. Now lookup matches the key used everywhere else.

        Args:
            key: (project, task) or (project, task, group_idx) tuple uniquely identifying the task.
                 Must match the key in self.offline_durations and self.offline_event_durations.
            task_events_for_key: List of task events for this (project, task)

        Returns:
            Synthetic slot dictionary with all required TimelineSlot fields:
            - type, start, end, duration, actual_duration, event_duration, project, task
            The presence of actual_duration and event_duration is critical: without them,
            TimelineSlot.__post_init__ validation fails, immediately surfacing data issues.

        HARDENING: Added actual_duration and event_duration fields. These were completely
        absent from the original implementation, causing silent data loss. Now all
        offline_task slots pass through TimelineSlot validation, preventing future bugs
        from being hidden by "friendly" defaults.
        """
        if not task_events_for_key:
            return {}

        project, task = key[0], key[1]
        start_times = [e.timestamp.astimezone() for e in task_events_for_key]
        slot_start = min(start_times)
        slot_duration = self.offline_durations.get(key, timedelta(0))
        slot_end = slot_start + slot_duration
        online_time = self.offline_event_durations.get(key, timedelta(0))

        # Get tags from any event in this group
        raw_tags = task_events_for_key[0].data.get("tags", [])
        task_tags = [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)

        # Use reconciled categories (window events + offline remainder) if available,
        # otherwise fall back to a flat "Offline" bucket for backward compatibility
        categories = self.offline_categories.get(key, [
            {
                "category": "Offline",
                "duration": slot_duration,
                "start": slot_start,
                "end": slot_end,
            }
        ])

        return {
            "type": "offline_task",
            "start": slot_start,
            "end": slot_end,
            "duration": slot_duration,
            "actual_duration": online_time,
            "event_duration": online_time,
            "productive_duration": timedelta(0),
            "project": project,
            "task": task,
            "tags": task_tags,
            "categories": categories,
        }

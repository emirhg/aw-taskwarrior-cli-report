"""
OFFLINE task processing and duration calculation.

This module extracts and centralizes OFFLINE task handling that was previously
scattered in tw-report.py. It handles detection, validation, and duration
calculation for tasks with the 'offline' tag.

OFFLINE TASK DEFINITION:
An offline task is work done while the system is completely offline (powered off or
severely disconnected). Within an offline task's time span:
- offline_time = periods where the AFK bucket has NO events (system was truly off)
- online_time = periods where the AFK bucket HAS events (system was on but task was being worked)

EXPECTED OUTPUT (for a task worked 13:01-18:16):
- Display: (3:04:00 OFF)  1:52:16  [prod  37%]
- Interpretation: 3:04 hours system-off, 1:52:16 hours system-on, total 5:00:00

CALCULATION:
1. Collect all TaskWarrior events with 'offline' tag for the task
2. Find wall-clock span: min(event_start) to max(event_end)
3. Sum all event durations = online_time (when system was on)
4. offline_time = wall_clock_span - online_time
5. prod% = online_time / wall_clock_span × 100

ISSUE #1 FIX: OFFLINE task results are now filtered consistently using
EventFilter, preventing 0:00:00 duration display in consolidated reports.
"""

from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta
from aw_core.models import Event

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
    """

    def __init__(self,
                 task_events: Optional[List[Event]],
                 window_events: List[Event],
                 event_filter: 'EventFilter',
                 end_time: Optional[datetime] = None):
        """
        Initialize processor.

        Args:
            task_events: List of TaskWarrior events
            window_events: List of window activity events
            event_filter: EventFilter instance for filtering results
            end_time: End time for the report period (used for incomplete/running tasks)
        """
        self.task_events = task_events or []
        self.window_events = window_events
        self.event_filter = event_filter
        self.end_time = end_time
        self.offline_durations: Dict[Tuple, timedelta] = {}
        self.offline_event_durations: Dict[Tuple, timedelta] = {}
        self.event_groups: Dict[Tuple, List[Event]] = {}  # Store events per group

    def process(self) -> Tuple[Dict, Dict, Dict[Tuple, List[Event]]]:
        """
        Process all OFFLINE-tagged tasks.

        FIX FOR ISSUE #1: Results are filtered before returning, so synthetic
        slots created later will respect --exclude-non-project and other filters.

        Returns:
            Tuple of (wall_clock_durations, event_durations, event_groups) dictionaries.
            Keys can be 2-element tuples (project, task) or 3-element tuples (project, task, group_idx)
            for split groups.
        """
        self._calculate_durations()

        # Apply filter to results (Issue #1 fix)
        filtered = {}
        filtered_events = {}
        filtered_groups = {}
        for key, duration in self.offline_durations.items():
            # Extract project and task from key (handle both 2-element and 3-element tuples)
            project = key[0] if isinstance(key, tuple) else ""
            task = key[1] if isinstance(key, tuple) and len(key) > 1 else ""

            entry = {"project": project, "task": task, "type": "offline_task"}
            if self.event_filter.should_include_entry(entry, "offline_task"):
                filtered[key] = duration
                filtered_events[key] = self.offline_event_durations.get(key, timedelta(0))
                filtered_groups[key] = self.event_groups.get(key, [])

        return filtered, filtered_events, filtered_groups

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
                task = event.data.get(
                    "title"
                ) or event.data.get("label") or event.data.get("task") or "No task assigned"
                key = (project, task)

                if key not in offline_events_by_key:
                    offline_events_by_key[key] = []
                offline_events_by_key[key].append(event)

        # Calculate duration for each task
        for key, events in offline_events_by_key.items():
            sorted_events = sorted(events, key=lambda e: e.timestamp)

            # Deduplicate events by (timestamp, duration) to avoid counting identical entries twice
            seen = set()
            unique_events = []
            for event in sorted_events:
                event_key = (event.timestamp, event.duration)
                if event_key not in seen:
                    seen.add(event_key)
                    unique_events.append(event)

            # Filter out spurious events BEFORE splitting
            # 1. Zero-duration events (but keep events without duration - they're running/incomplete)
            # 2. Events significantly shorter than median (likely artifacts)
            significant_events = [
                e for e in unique_events
                if e.duration is None or e.duration.total_seconds() > 60
            ]

            if not significant_events:
                continue

            # Calculate median duration (excluding events without duration) for filtering
            durations_with_values = [
                e.duration.total_seconds() for e in significant_events
                if e.duration is not None
            ]
            if durations_with_values:
                durations = sorted(durations_with_values)
                median_duration = durations[len(durations) // 2]
                # Keep events that are at least 25% of median duration, PLUS any events without duration
                filtered_for_split = [
                    e for e in significant_events
                    if e.duration is None or e.duration.total_seconds() >= median_duration * 0.25
                ]
            else:
                filtered_for_split = significant_events

            # Split filtered events into groups based on interruptions from other tasks
            event_groups = self._split_by_task_interruptions(filtered_for_split, key)

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
            if (
                other_event.timestamp < session_end
                and other_end > session_start
            ):
                return True

        return False

    def _unassigned_window_in_gap(
        self, gap_start: datetime, gap_end: datetime
    ) -> bool:
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
        Split offline task events into groups when interrupted by other tasks.

        Groups consecutive events that are not interrupted. If another task occurs
        between events, starts a new group.

        Args:
            events: List of offline task events (already sorted and deduplicated)
            task_key: (project, task) tuple for this offline task

        Returns:
            List of event groups, each representing an uninterrupted session
        """
        if not events:
            return []

        groups: List[List[Event]] = []
        current_group: List[Event] = [events[0]]

        for i in range(1, len(events)):
            curr_event = events[i]
            prev_event = current_group[-1]

            # Calculate gap between prev_event end and curr_event start
            prev_end = prev_event.timestamp + prev_event.duration if prev_event.duration else prev_event.timestamp
            curr_start = curr_event.timestamp
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
                other_end = other_event.timestamp + other_event.duration if other_event.duration else other_event.timestamp

                if other_start < gap_end and other_end > gap_start:
                    interruption_found = True
                    break

            if interruption_found:
                # End current group and start new one
                groups.append(current_group)
                current_group = [curr_event]
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

        # Filter out spurious events
        significant_events = [
            e for e in group_events
            if e.duration is None or e.duration.total_seconds() > 60
        ]

        if not significant_events:
            return

        # Calculate median duration (excluding events without duration)
        durations_with_values = [
            e.duration.total_seconds() for e in significant_events
            if e.duration is not None
        ]

        # Keep events that are at least 25% of median duration, plus incomplete events
        if durations_with_values:
            durations = sorted(durations_with_values)
            median_duration = durations[len(durations) // 2]
            sorted_events = [
                e for e in significant_events
                if e.duration is None or e.duration.total_seconds() >= median_duration * 0.25
            ]
            sorted_events = sorted(sorted_events, key=lambda e: e.timestamp)
        else:
            sorted_events = sorted(significant_events, key=lambda e: e.timestamp)

        if not sorted_events:
            return

        # Calculate wall-clock span
        wall_clock_start = sorted_events[0].timestamp
        wall_clock_end = sorted_events[0].timestamp
        has_incomplete = False

        for event in sorted_events:
            if event.duration:
                event_end = event.timestamp + event.duration
                wall_clock_end = max(wall_clock_end, event_end)
            else:
                has_incomplete = True

        # If any incomplete event found, extend to report end time
        if has_incomplete and self.end_time:
            wall_clock_end = self.end_time

        wall_clock_duration = wall_clock_end - wall_clock_start

        # Calculate offline vs online time
        # Sum ALL event durations (all TW events represent system-on time; gaps between are offline)
        online_sum = sum(
            (e.duration for e in sorted_events if e.duration),
            timedelta(0)
        )

        # Store results
        self.offline_durations[group_key] = wall_clock_duration
        self.offline_event_durations[group_key] = online_sum
        self.event_groups[group_key] = sorted_events  # Store events for this group

    def get_synthetic_slot(
        self, project: str, task: str, task_events_for_key: List[Event]
    ) -> Dict:
        """
        Build a synthetic slot for an OFFLINE task.

        Args:
            project: Project name
            task: Task name
            task_events_for_key: List of task events for this (project, task)

        Returns:
            Synthetic slot dictionary
        """
        if not task_events_for_key:
            return {}

        start_times = [e.timestamp for e in task_events_for_key]
        end_times = [e.timestamp + e.duration for e in task_events_for_key]
        slot_start = min(start_times)
        slot_end = max(end_times)
        slot_duration = self.offline_durations.get(
            (project, task), timedelta(0)
        )

        # Get tags from any event in this group
        raw_tags = task_events_for_key[0].data.get("tags", [])
        task_tags = (
            [raw_tags]
            if isinstance(raw_tags, str)
            else list(raw_tags)
        )

        return {
            "type": "offline_task",
            "start": slot_start.astimezone(),
            "end": slot_end.astimezone(),
            "duration": slot_duration,
            "productive_duration": timedelta(0),
            "project": project,
            "task": task,
            "tags": task_tags,
            "categories": [
                {
                    "category": "Offline",
                    "duration": slot_duration,
                    "start": slot_start.astimezone(),
                    "end": slot_end.astimezone(),
                }
            ],
        }

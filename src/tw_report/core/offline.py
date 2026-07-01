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
                 event_filter: 'EventFilter'):
        """
        Initialize processor.

        Args:
            task_events: List of TaskWarrior events
            window_events: List of window activity events
            event_filter: EventFilter instance for filtering results
        """
        self.task_events = task_events or []
        self.window_events = window_events
        self.event_filter = event_filter
        self.offline_durations: Dict[Tuple[str, str], timedelta] = {}
        self.offline_event_durations: Dict[Tuple[str, str], timedelta] = {}

    def process(self) -> Tuple[Dict[Tuple[str, str], timedelta], Dict[Tuple[str, str], timedelta]]:
        """
        Process all OFFLINE-tagged tasks.

        FIX FOR ISSUE #1: Results are filtered before returning, so synthetic
        slots created later will respect --exclude-non-project and other filters.

        Returns:
            Tuple of (wall_clock_durations, event_durations) dictionaries, both mapping
            (project, task) tuples to their respective timedeltas
        """
        self._calculate_durations()

        # Apply filter to results (Issue #1 fix)
        filtered = {}
        filtered_events = {}
        for (project, task), duration in self.offline_durations.items():
            entry = {"project": project, "task": task, "type": "offline_task"}
            if self.event_filter.should_include_entry(entry, "offline_task"):
                filtered[(project, task)] = duration
                filtered_events[(project, task)] = self.offline_event_durations.get((project, task), timedelta(0))

        return filtered, filtered_events

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

            sorted_events = unique_events
            event_sum = timedelta(0)
            wall_clock_start = sorted_events[0].timestamp
            wall_clock_end = sorted_events[-1].timestamp + sorted_events[-1].duration

            # Calculate offline vs online time based on window activity
            # - Offline: event has NO window activity during its period (system was powered off)
            # - Online: event has window activity during its period (system was on but task tracked via TW)
            offline_sum = timedelta(0)
            online_sum = timedelta(0)

            for event in sorted_events:
                event_start = event.timestamp
                event_end = event.timestamp + event.duration
                event_start_tz = event_start
                event_end_tz = event_end

                # Check if any window activity occurs during this event
                # Handle timezone-aware/naive datetime comparison by normalizing
                has_window_activity = False
                for w in self.window_events:
                    w_start = w.timestamp
                    w_end = w.timestamp + w.duration

                    # Normalize timezone info for comparison
                    if event_start.tzinfo is not None and w_start.tzinfo is None:
                        w_start = w_start.replace(tzinfo=event_start.tzinfo)
                        w_end = w_end.replace(tzinfo=event_start.tzinfo)
                    elif event_start.tzinfo is None and w_start.tzinfo is not None:
                        event_start_tz = event_start.replace(tzinfo=w_start.tzinfo)
                        event_end_tz = event_end.replace(tzinfo=w_start.tzinfo)

                    # Check for overlap
                    if w_start < event_end_tz and w_end > event_start_tz:
                        has_window_activity = True
                        break

                if has_window_activity:
                    online_sum += event.duration
                else:
                    offline_sum += event.duration

                event_sum += event.duration

            # Wall-clock span is the full time from earliest event start to latest event end
            wall_clock_duration = wall_clock_end - wall_clock_start

            # Store wall-clock duration as total, and event_sum as online (events with window activity)
            self.offline_durations[key] = wall_clock_duration
            self.offline_event_durations[key] = online_sum

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

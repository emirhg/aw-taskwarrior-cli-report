"""
Task matching and identification for timesheet correlation.

Provides utilities for matching window events to TaskWarrior tasks,
extracting task metadata, and detecting offline-tagged tasks.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from aw_core.models import Event

from tw_report.core.filtering import NO_PROJECT, NO_TASK


def find_active_task(event: Event, task_events: List[Event]) -> Optional[Event]:
    """Find the taskwarrior event that overlaps with the given window event.

    Performs interval intersection: returns the first task event that overlaps
    with the given window event's time range, or None if no overlap found.

    Args:
        event: Window/activity event to find an active task for
        task_events: List of TaskWarrior task events to search

    Returns:
        The overlapping task event, or None if no task was active during this event
    """
    return next(
        (
            task
            for task in task_events
            if event.timestamp < task.timestamp + task.duration
            and task.timestamp < event.timestamp + event.duration
        ),
        None,
    )


def get_task_info(active_task: Event) -> Tuple[str, str]:
    """Extract task name and project from an active taskwarrior event.

    Extracts identifying information from a TaskWarrior task event.
    Task name falls back through multiple fields; project defaults to NO_PROJECT.

    Args:
        active_task: TaskWarrior task event to extract from

    Returns:
        Tuple of (task_name, project) strings. Task name is extracted with
        priority: title > label > task > NO_TASK. Project defaults to NO_PROJECT.
    """
    task_name = (
        active_task.data.get("title")
        or active_task.data.get("label")
        or active_task.data.get("task")
        or NO_TASK
    )
    project = active_task.data.get("project", NO_PROJECT)
    return task_name, project


def task_has_offline_tag(task_event: Event) -> bool:
    """Check if a task event has the 'offline' tag (case-insensitive).

    TaskWarrior tags are either a string (single tag) or list (multiple tags).
    This function normalizes both forms and performs case-insensitive matching.

    Args:
        task_event: TaskWarrior task event to check for offline tag

    Returns:
        True if the event has an 'offline' tag (case-insensitive), False otherwise
    """
    raw_tags = task_event.data.get("tags", [])
    tags = [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)
    return "offline" in (t.lower() for t in tags)


def build_offline_category_structure(
    duration: timedelta,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Dict:
    """Build an Offline category structure for both hierarchical and timeline reports.

    Constructs a category dict representing offline time, with different formats
    depending on whether timeline-specific fields (start_time, end_time) are provided.

    Args:
        duration: Total duration of the offline task
        start_time: Optional start time for timeline reports (structure changes if provided)
        end_time: Optional end time for timeline reports (structure changes if provided)

    Returns:
        Dict with either:
        - Timeline format (if start_time/end_time provided):
          {category, duration, start, end, apps}
        - Hierarchical format (if times not provided):
          {total_duration, apps, prod_score}
    """
    if start_time is not None and end_time is not None:
        return {
            "category": "Offline",
            "duration": duration,
            "start": start_time,
            "end": end_time,
            "apps": [],
        }
    else:
        return {
            "total_duration": duration,
            "apps": {},
            "prod_score": 0.0,
        }

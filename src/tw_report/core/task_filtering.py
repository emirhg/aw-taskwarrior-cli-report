"""
Task-based event filtering and auto-detection.

Provides efficient task filtering that can skip window bucket queries
when only task-level information is needed, and auto-detects task IDs/UUIDs
in --task filter values, resolving them to task descriptions.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from tw_report.core.aw_events import TaskWarriorEvent

logger = logging.getLogger(__name__)


def get_events_by_task(
    client,
    bucket_id: str,
    start: datetime,
    end: datetime,
    task: Optional[str] = None,
) -> List["TaskWarriorEvent"]:
    """Fetch taskwarrior events, optionally filtered by task name.

    Filters events where the task name matches the given pattern
    (substring matching, case-insensitive).

    Args:
        client: ActivityWatchClient instance
        bucket_id: Full bucket ID to fetch from (typically taskwarrior bucket)
        start: Start of time range (inclusive)
        end: End of time range (inclusive)
        task: Optional task name pattern to filter by (substring match)

    Returns:
        List of TaskWarriorEvent objects, optionally filtered by task name.
        Empty list if bucket unreachable or no matches found.

    Examples:
        >>> # Fetch all taskwarrior events
        >>> events = get_events_by_task(client, tw_bucket, start, end)
        >>> # Fetch only events for tasks matching "Documentar"
        >>> events = get_events_by_task(
        ...     client, tw_bucket, start, end, task="Documentar"
        ... )
    """
    from tw_report.core.aw_events import TaskWarriorEvent
    from tw_report.core.events import get_events
    from tw_report.core.task_matching import get_task_info

    # Fetch all taskwarrior events in range from the bucket, re-wrapped as TaskWarriorEvent
    all_events = get_events(client, bucket_id, start, end, event_cls=TaskWarriorEvent)

    # If no task filter, return all events
    if not task:
        return all_events

    # Filter to events matching the task name (case-insensitive substring match)
    filtered = []
    for e in all_events:
        task_name, _ = get_task_info(e)
        if task.lower() in task_name.lower():
            filtered.append(e)

    if filtered:
        logger.debug(f"Filtered to {len(filtered)} events for task: {task}")
    else:
        logger.debug(f"No events found matching task: {task}")

    return filtered


def resolve_task_filter_value(value: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a task filter value to a concrete task description.

    Supports three forms:
    1. Integer task ID (all digits) → resolve to task's description field
    2. UUID string → resolve to task's description field
    3. Literal string pattern → return unchanged (substring match behavior)

    Args:
        value: Filter value (pattern, ID, or UUID)

    Returns:
        Tuple of (resolved_value, error_message).
        - On success: (task_name, None)
        - On error: (None, error_message_string)
        - For patterns: (pattern_unchanged, None)

    Examples:
        >>> resolve_task_filter_value("48")
        ("Documentar una presentación sobre el Mecanismo de Antikythera", None)
        >>> resolve_task_filter_value("550e8400-e29b-41d4-a716-446655440000")
        ("Documentar una presentación sobre el Mecanismo de Antikythera", None)
        >>> resolve_task_filter_value("Documentar")
        ("Documentar", None)
        >>> resolve_task_filter_value("999")
        (None, "Task 999 has no description")
    """
    from tw_report.core.project_filtering import _is_uuid_like
    from tw_report.core.task_uuid_filtering import get_task_description

    # Detect if value is an ID or UUID that needs resolution
    if value.isdigit():
        identifier = int(value)
    elif _is_uuid_like(value):
        identifier = value
    else:
        # Plain pattern, return unchanged
        return value, None

    # Resolve to task description
    description = get_task_description(identifier)
    if not description:
        return None, f"Task {value} has no description"

    return description, None


def get_events_by_tasks(
    client,
    bucket_id: str,
    start: datetime,
    end: datetime,
    tasks: Optional[List[str]] = None,
) -> List["TaskWarriorEvent"]:
    """Fetch taskwarrior events filtered by multiple task name patterns (PHASE 14).

    More efficient than calling get_events_by_task() multiple times because
    it fetches all events once, then filters by all requested task patterns.

    Filters events where the task name matches ANY of the given patterns
    (substring matching, case-insensitive).

    Args:
        client: ActivityWatchClient instance
        bucket_id: Full bucket ID to fetch from (typically taskwarrior bucket)
        start: Start of time range (inclusive)
        end: End of time range (inclusive)
        tasks: List of task name patterns to filter by (substring match)
               Returns all events if None or empty list.

    Returns:
        List of TaskWarriorEvent objects, filtered by tasks.
        Empty list if bucket unreachable or no matches found.

    Examples:
        >>> # Fetch events matching ANY of multiple tasks
        >>> events = get_events_by_tasks(
        ...     client, tw_bucket, start, end,
        ...     tasks=["Documentar", "Code review"]
        ... )
    """
    from tw_report.core.aw_events import TaskWarriorEvent
    from tw_report.core.events import get_events
    from tw_report.core.task_matching import get_task_info

    # Fetch all taskwarrior events once
    all_events = get_events(client, bucket_id, start, end, event_cls=TaskWarriorEvent)

    # If no task filters, return all events
    if not tasks:
        return all_events

    # Filter to events matching ANY of the tasks (case-insensitive substring match)
    filtered = []
    for e in all_events:
        task_name, _ = get_task_info(e)
        if any(t.lower() in task_name.lower() for t in tasks):
            filtered.append(e)

    if filtered:
        logger.debug(f"Filtered to {len(filtered)} events for {len(tasks)} tasks: {tasks}")
    else:
        logger.debug(f"No events found matching tasks: {tasks}")

    return filtered

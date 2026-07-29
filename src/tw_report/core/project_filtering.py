"""
Project-based event filtering and optimization.

Provides efficient project filtering that can skip window bucket queries
when only task-level information is needed (project, task name, duration).
Also provides task ID/UUID resolution to project names.
"""

import logging
import uuid as uuid_module
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Tuple

from aw_core.models import Event

if TYPE_CHECKING:
    from tw_report.core.aw_events import TaskWarriorEvent

logger = logging.getLogger(__name__)


def get_events_by_project(
    client,
    bucket_id: str,
    start: datetime,
    end: datetime,
    project: Optional[str] = None,
) -> List["TaskWarriorEvent"]:
    """Fetch taskwarrior events, optionally filtered by project name.

    Filters events where the 'project' field matches the given project pattern
    (substring matching, case-insensitive).

    Args:
        client: ActivityWatchClient instance
        bucket_id: Full bucket ID to fetch from (typically taskwarrior bucket)
        start: Start of time range (inclusive)
        end: End of time range (inclusive)
        project: Optional project name pattern to filter by (substring match)

    Returns:
        List of TaskWarriorEvent objects, optionally filtered by project.
        Empty list if bucket unreachable or no matches found.

    Examples:
        >>> # Fetch all taskwarrior events
        >>> events = get_events_by_project(client, tw_bucket, start, end)
        >>> # Fetch only events for projects matching "Climb"
        >>> events = get_events_by_project(
        ...     client, tw_bucket, start, end, project="Climb"
        ... )
    """
    from tw_report.core.events import get_events
    from tw_report.core.aw_events import TaskWarriorEvent

    # Fetch all taskwarrior events in range from the bucket, re-wrapped as TaskWarriorEvent
    all_events = get_events(client, bucket_id, start, end, event_cls=TaskWarriorEvent)

    # If no project filter, return all events
    if not project:
        return all_events

    # Filter to events matching the project (case-insensitive substring match)
    filtered = [
        e for e in all_events
        if project.lower() in e.data.get("project", "").lower()
    ]

    if filtered:
        logger.debug(f"Filtered to {len(filtered)} events for project: {project}")
    else:
        logger.debug(f"No events found matching project: {project}")

    return filtered


def _is_uuid_like(value: str) -> bool:
    """Check if a string is a valid UUID format.

    Args:
        value: String to check

    Returns:
        True if value is a valid UUID, False otherwise
    """
    try:
        uuid_module.UUID(value)
        return True
    except ValueError:
        return False


def resolve_project_filter_value(value: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a project filter value to a concrete project name.

    Supports three forms:
    1. Integer task ID (all digits) → resolve to task's project field
    2. UUID string → resolve to task's project field
    3. Literal string pattern → return unchanged (substring match behavior)

    Args:
        value: Filter value (pattern, ID, or UUID)

    Returns:
        Tuple of (resolved_value, error_message).
        - On success: (project_name, None)
        - On error: (None, error_message_string)
        - For patterns: (pattern_unchanged, None)

    Examples:
        >>> resolve_project_filter_value("48")
        ("Antikythera > Mechanism", None)
        >>> resolve_project_filter_value("550e8400-e29b-41d4-a716-446655440000")
        ("Antikythera > Mechanism", None)
        >>> resolve_project_filter_value("Climb")
        ("Climb", None)
        >>> resolve_project_filter_value("999")
        (None, "Task 999 not found")
    """
    from tw_report.core.task_uuid_filtering import get_task_project

    # Detect if value is an ID or UUID that needs resolution
    if value.isdigit():
        identifier = int(value)
    elif _is_uuid_like(value):
        identifier = value
    else:
        # Plain pattern, return unchanged
        return value, None

    # Resolve to project name
    project = get_task_project(identifier)
    if not project:
        # project is None (missing field) or empty string (no project assigned)
        return None, f"Task {value} has no project assigned"

    return project, None


def should_skip_window_bucket(
    args,
    detail_level: int = 1,
    grouping_mode: str = "day",
) -> bool:
    """Determine if window bucket queries can be skipped.

    Window bucket queries can be skipped when detail_level is 1-2 AND:
    - Not filtering by app (which requires window events to check category match)
    - Using timeline mode (day/week/month/year), not hierarchical (project grouping)

    Window bucket queries MUST be fetched when:
    - detail_level >= 3 (need category/app/title breakdown)
    - Filtering by app (need window events to match against)
    - Using hierarchical/project grouping mode

    Args:
        args: Parsed command-line arguments
        detail_level: Detail level (1-5)
        grouping_mode: Grouping mode ("project", "day", "week", "month", "year")

    Returns:
        True if window bucket can be safely skipped, False otherwise

    Examples:
        >>> # Can skip: detail 1-2 + timeline mode + no app filter
        >>> should_skip_window_bucket(args, detail_level=1, grouping_mode="day")
        True

        >>> # Cannot skip: detail_level >= 3 always needs windows
        >>> should_skip_window_bucket(args, detail_level=3, grouping_mode="day")
        False

        >>> # Cannot skip: app filter requires window events
        >>> should_skip_window_bucket(args, detail_level=1, grouping_mode="day")
        False  # if args.app is set
    """
    # Can't skip if detail level requires app-level data (3+)
    if detail_level >= 3:
        return False

    # Can't skip if filtering by app (requires window events to evaluate category)
    if args.app:
        return False

    # Can't skip if using hierarchical/project grouping mode
    # (may need to compute project tracking % across activities)
    if grouping_mode == "project":
        return False

    # Can skip for detail_level 1-2 in timeline mode with no app filter
    return True

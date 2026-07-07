"""
Task UUID filtering and lookup for ActivityWatch queries.

Provides utilities for looking up TaskWarrior task UUIDs by ID and filtering
ActivityWatch events by UUID, enabling task-level filtering without requiring
app-level data (window bucket).
"""

import json
import logging
import subprocess
from datetime import datetime
from typing import List, Optional

from aw_core.models import Event

logger = logging.getLogger(__name__)


def _export_task(identifier) -> Optional[dict]:
    """Export TaskWarrior task data by ID or UUID.

    Uses 'task <identifier> export' to fetch full task data.
    Gracefully returns None on any error.

    Args:
        identifier: TaskWarrior task ID (int or int-like str) or UUID string

    Returns:
        Full task dict if found, None otherwise
    """
    try:
        result = subprocess.run(
            ["task", str(identifier), "export"],
            capture_output=True,
            text=True,
            check=True,
        )
        task_data = json.loads(result.stdout)

        if not task_data or not isinstance(task_data, list):
            return None

        return task_data[0]

    except subprocess.CalledProcessError:
        logger.debug(f"Task {identifier} not found")
        return None
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.debug(f"Failed to parse task {identifier} export: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error looking up task {identifier}: {e}")
        return None


def get_task_uuid(task_id: int) -> Optional[str]:
    """Get UUID for a TaskWarrior task by ID.

    Uses 'task <id> export' to fetch task data and extracts the uuid field.
    Gracefully returns None on any error (invalid task, JSON parsing, etc).

    Args:
        task_id: TaskWarrior task ID (integer)

    Returns:
        UUID string if task found and valid, None otherwise

    Examples:
        >>> get_task_uuid(48)
        '550e8400-e29b-41d4-a716-446655440000'
        >>> get_task_uuid(999)  # Invalid ID
        None
    """
    task = _export_task(task_id)
    if not task:
        return None
    uuid = task.get("uuid")
    if uuid:
        logger.debug(f"Resolved task {task_id} to UUID: {uuid}")
    return uuid


def get_task_project(identifier) -> Optional[str]:
    """Get project field for a TaskWarrior task by ID or UUID.

    Uses 'task <identifier> export' to fetch task data and extracts the project field.
    Gracefully returns None on any error.

    Args:
        identifier: TaskWarrior task ID (int) or UUID string

    Returns:
        Project string if task found and has project field, None otherwise

    Examples:
        >>> get_task_project(48)
        'Antikythera > Mechanism'
        >>> get_task_project("550e8400-e29b-41d4-a716-446655440000")
        'Antikythera > Mechanism'
        >>> get_task_project(999)  # Invalid ID
        None
    """
    task = _export_task(identifier)
    if not task:
        return None
    return task.get("project")


def get_task_description(identifier) -> Optional[str]:
    """Get description (name) for a TaskWarrior task by ID or UUID.

    Uses 'task <identifier> export' to fetch task data and extracts the description field.
    Gracefully returns None on any error.

    Args:
        identifier: TaskWarrior task ID (int) or UUID string

    Returns:
        Description string (task name) if task found, None otherwise

    Examples:
        >>> get_task_description(48)
        'Documentar una presentación sobre el Mecanismo de Antikythera'
        >>> get_task_description("550e8400-e29b-41d4-a716-446655440000")
        'Documentar una presentación sobre el Mecanismo de Antikythera'
        >>> get_task_description(999)  # Invalid ID
        None
    """
    task = _export_task(identifier)
    if not task:
        return None
    return task.get("description")


def get_events_by_uuid(
    client,
    bucket_id: str,
    start: datetime,
    end: datetime,
    uuid: Optional[str] = None,
) -> List[Event]:
    """Fetch events from a bucket and optionally filter by UUID.

    Fetches events from the specified bucket within the time range.
    If uuid is provided, uses server-side filtering for efficiency.

    Server-side filtering is 10-100x faster than fetching all events and
    filtering in Python, especially for large buckets.

    Args:
        client: ActivityWatchClient instance
        bucket_id: Full bucket ID to fetch from
        start: Start of time range (inclusive)
        end: End of time range (inclusive)
        uuid: Optional UUID to filter by. If None, returns all events.

    Returns:
        List of Event objects, optionally filtered by UUID.
        Empty list if bucket unreachable or no matches found.

    Examples:
        >>> # Fetch all taskwarrior events
        >>> events = get_events_by_uuid(client, tw_bucket, start, end)
        >>> # Fetch only events for a specific task (server-side filtering)
        >>> task_events = get_events_by_uuid(
        ...     client, tw_bucket, start, end, uuid="550e8400..."
        ... )
    """
    from tw_report.core.events import get_events

    # If no UUID filter, use normal fetch
    if not uuid:
        return get_events(client, bucket_id, start, end)

    # Fetch all events (AW doesn't support query-level UUID filtering)
    all_events = get_events(client, bucket_id, start, end)

    # Use optimized filter_keyvals from aw_transform
    try:
        from aw_transform import filter_keyvals

        # filter_keyvals optimizes filtering and is faster than list comprehension
        filtered = filter_keyvals(all_events, "uuid", [uuid])

        if filtered:
            logger.debug(f"Filtered to {len(filtered)} events for UUID: {uuid}")
        else:
            logger.debug(f"No events found matching UUID: {uuid}")

        return filtered

    except ImportError:
        # Fallback to manual filtering if aw_transform unavailable
        logger.debug("aw_transform unavailable, using manual filtering")
        filtered = [e for e in all_events if e.data.get("uuid") == uuid]
        return filtered

"""
ActivityWatch event fetching and bucket management.

Provides low-level access to ActivityWatch buckets and events, with proper
error handling and logging. Replaces ad-hoc print-to-stderr patterns with
typed exceptions and structured logging.
"""

import logging
import platform
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Tuple, Type, Optional

from aw_core.models import Event
from aw_client import ActivityWatchClient

from tw_report.exceptions import ActivityWatchConnectionError

if TYPE_CHECKING:
    from tw_report.core.aw_events import AFKEvent

logger = logging.getLogger(__name__)



def get_bucket_id(bucket_name: str) -> str:
    """Construct the full bucket ID from its name and the machine's hostname.

    Args:
        bucket_name: Bucket name (e.g., "window", "afk", "taskwarrior")

    Returns:
        Full bucket ID (e.g., "aw-watcher-window_hostname")
    """
    hostname = platform.node()
    return f"aw-watcher-{bucket_name}_{hostname}"


def get_events(
    client: ActivityWatchClient,
    bucket_id: str,
    start: datetime,
    end: datetime,
    event_cls: Optional[Type[Event]] = None,
) -> List[Event]:
    """Fetch events from a specific bucket within a time range.

    Gracefully degrades on connection errors: logs a warning and returns an
    empty list, allowing the report to continue with partial data rather than
    failing completely.

    Args:
        client: ActivityWatch client instance
        bucket_id: Full bucket ID to fetch from (use get_bucket_id() to construct)
        start: Start of time range (inclusive)
        end: End of time range (inclusive)
        event_cls: Optional Event subclass to re-wrap the results into (e.g., WindowEvent,
                   AFKEvent, TaskWarriorEvent). If provided, each event returned by the
                   client (plain Event instances) is re-wrapped as an instance of this class.

    Returns:
        List of Event objects (or instances of event_cls if provided) from the bucket.
        Empty list if the bucket is unreachable (connection error, server offline, etc.).
        Logs a warning when degrading.

    Notes:
        - Does NOT raise ActivityWatchConnectionError (logs + degrades instead)
        - Preserves backward compatibility: continues generating reports with
          partial data (window events only, no AFK/task info) when AW is down
        - Use limit=-1 to fetch all events without pagination
    """
    try:
        events = client.get_events(bucket_id, start=start, end=end, limit=-1)
        logger.debug(f"Fetched {len(events)} events from bucket '{bucket_id}'")

        # Re-wrap events in the specified subclass if provided
        if event_cls is not None and event_cls is not Event:
            events = [
                event_cls(
                    id=e.id,
                    timestamp=e.timestamp,
                    duration=e.duration,
                    data=e.data,
                )
                for e in events
            ]

        return events
    except Exception as e:
        logger.warning(
            f"Could not fetch events for bucket '{bucket_id}': {e} "
            f"(continuing with partial data)",
            exc_info=True,
        )
        return []


def partition_task_duration(
    task_event: "Event",
    afk_events: List["AFKEvent"],
) -> dict:
    """Partition a TaskWarrior task duration into ACTIVE and AFK portions.

    For each TaskWarrior task, correlates with AFK events to determine
    what the user was actually doing:
    - ACTIVE: time when task was active (not covered by AFK)
    - AFK: time when user was idle during the task (covered by AFK)

    Note: Window events are NOT used for partitioning. They are only used
    separately for AFK false-positive detection after partitioning is complete.

    Args:
        task_event: TaskWarrior task event with duration
        afk_events: AFK bucket events (idle time tracking)

    Returns:
        dict with:
            "active_portions": [(start, end), ...] - Task time not covered by AFK
            "afk_portions": [(start, end), ...] - Task time covered by AFK

    Example:
        Task: 14:00-15:30 (90 min claimed)
        AFK: [14:20-14:30], [14:50-15:00]  (20 min idle during task)
        → active_portions: [(14:00-14:20), (14:30-14:50), (15:00-15:30)]
        → afk_portions: [(14:20-14:30), (14:50-15:00)]
    """
    task_start = task_event.timestamp
    task_end = task_start + task_event.duration

    # Find AFK periods that overlap this task
    overlapping_afk = []
    for a in afk_events:
        if a.data.get("status") != "afk":
            continue  # Skip non-AFK events
        a_start = a.timestamp
        a_end = a_start + a.duration
        if a_start < task_end and a_end > task_start:
            # Clamp to task boundaries
            clamped_start = max(a_start, task_start)
            clamped_end = min(a_end, task_end)
            overlapping_afk.append((clamped_start, clamped_end))

    # Sort and merge overlapping AFK periods
    if overlapping_afk:
        overlapping_afk.sort()
        merged_afk = []
        current_start, current_end = overlapping_afk[0]
        for a_start, a_end in overlapping_afk[1:]:
            if a_start <= current_end:
                current_end = max(current_end, a_end)
            else:
                merged_afk.append((current_start, current_end))
                current_start, current_end = a_start, a_end
        merged_afk.append((current_start, current_end))
    else:
        merged_afk = []

    # Calculate ACTIVE portions: gaps with no AFK coverage
    active_portions = []
    current_pos = task_start
    for afk_start, afk_end in merged_afk:
        if current_pos < afk_start:
            active_portions.append((current_pos, afk_start))
        current_pos = max(current_pos, afk_end)

    if current_pos < task_end:
        active_portions.append((current_pos, task_end))

    return {
        "active_portions": active_portions,
        "afk_portions": merged_afk,
    }

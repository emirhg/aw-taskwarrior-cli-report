"""
ActivityWatch event fetching and bucket management.

Provides low-level access to ActivityWatch buckets and events, with proper
error handling and logging. Replaces ad-hoc print-to-stderr patterns with
typed exceptions and structured logging.
"""

import logging
import platform
from datetime import datetime
from typing import List, Optional, Type

from aw_client import ActivityWatchClient
from aw_core.models import Event

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

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
    from tw_report.core.aw_events import AFKEvent, WindowEvent

logger = logging.getLogger(__name__)

# Constants for AFK false-positive detection
AFK_FALSE_POSITIVE_THRESHOLD = timedelta(minutes=10)  # Minimum AFK duration to analyze for false-positives
AFK_FALSE_POSITIVE_COVERAGE_THRESHOLD = 5.0  # Coverage % below which AFK is classified as offline


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


def get_afk_window_coverage(
    afk_event: "AFKEvent",
    window_events: List["WindowEvent"]
) -> float:
    """Calculate percentage of AFK period covered by window events.

    Used to detect false-positive AFK: when system is powered off but
    AFK watcher continues reporting idle time, window coverage will be
    minimal (<5%). This indicates the system was actually offline.

    Args:
        afk_event: AFK bucket event to analyze
        window_events: List of window bucket events to check for overlap

    Returns:
        float: Coverage percentage (0.0 to 100.0)
            - 0.0: No window activity during AFK (system was offline)
            - <5%: Minimal coverage, likely false positive (system was offline)
            - ≥5%: Real online AFK time (user was idle but system was running)
            - 100.0: Window activity for entire AFK period (pure idle)
    """
    if afk_event.duration == timedelta(0):
        return 0.0

    afk_start = afk_event.timestamp
    afk_end = afk_event.timestamp + afk_event.duration

    covered_time = timedelta(0)
    for w in window_events:
        w_start = w.timestamp
        w_end = w_start + w.duration

        # Calculate overlap between window event and AFK period
        overlap_start = max(w_start, afk_start)
        overlap_end = min(w_end, afk_end)

        if overlap_start < overlap_end:
            covered_time += overlap_end - overlap_start

    return (covered_time.total_seconds() / afk_event.duration.total_seconds()) * 100


def classify_afk_slot(coverage_percent: float, threshold: float = None) -> str:  # type: ignore[assignment]
    """Classify AFK slot as ONLINE_AFK or OFFLINE based on window coverage.

    When a system comes online, window logger may record activity before
    AFK tracker recognizes the system is back. This creates false-positive
    AFK detection with low window coverage.

    Args:
        coverage_percent: Percentage of AFK period with window events (0-100)
        threshold: Coverage % below which AFK is classified as OFFLINE.
            Uses AFK_FALSE_POSITIVE_COVERAGE_THRESHOLD if not specified.

    Returns:
        "ONLINE_AFK": Real online idle time (coverage >= threshold)
        "OFFLINE": False positive, system was powered off (coverage < threshold)
    """
    if threshold is None:
        threshold = AFK_FALSE_POSITIVE_COVERAGE_THRESHOLD
    return "ONLINE_AFK" if coverage_percent >= threshold else "OFFLINE"


def split_afk_by_window_coverage(
    afk_event: "AFKEvent",
    window_events: List["WindowEvent"]
) -> Tuple[timedelta, timedelta]:
    """Split AFK slot into offline and online-AFK portions based on window activity.

    When system transitions from offline to online, window logger records
    activity before AFK tracker recognizes the system is back. This splits
    the AFK period at the first window event:

    - Portion before first window = OFFLINE (system was powered off)
    - Portion from first window onward = ONLINE_AFK (real idle time)

    Example:
    - AFK: 01:05:42 - 11:16:42 (10:11:00 total)
    - First window event: 11:16:25
    - Result: offline=10:10:43, online_afk=0:00:17

    Args:
        afk_event: AFK bucket event to split
        window_events: List of window bucket events

    Returns:
        Tuple of (offline_duration, online_afk_duration)
            - offline_duration: Time before any window activity (system was off)
            - online_afk_duration: Time from first window onward (real idle)
            - Sum always equals afk_event.duration
    """
    afk_start = afk_event.timestamp
    afk_end = afk_event.timestamp + afk_event.duration

    # Find earliest window event that overlaps or touches this AFK period
    earliest_window = None
    for w in window_events:
        w_start = w.timestamp
        if w_start < afk_end:  # Window overlaps or touches AFK
            if earliest_window is None or w_start < earliest_window.timestamp:
                earliest_window = w

    if earliest_window is None:
        # No windows during AFK = entire period is offline
        return (afk_event.duration, timedelta(0))

    # Split at first window event
    first_window_start = earliest_window.timestamp

    if first_window_start <= afk_start:
        # Window started before or at AFK start, no pure-offline portion
        return (timedelta(0), afk_event.duration)

    # Normal split: pure-offline portion + online-AFK remainder
    offline_duration = first_window_start - afk_start
    online_afk_duration = afk_end - first_window_start

    return (offline_duration, online_afk_duration)

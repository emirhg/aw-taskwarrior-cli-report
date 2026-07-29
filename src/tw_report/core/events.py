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
SYSTEM_OFF_MINIMUM_DURATION = timedelta(minutes=1)  # Minimum continuous gap to classify as SYSTEM OFF


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


def classify_afk_and_split_slots(
    afk_event: "AFKEvent",
    window_events: List["WindowEvent"],
    min_off_duration: Optional[timedelta] = None,
) -> dict:
    """Classify AFK event and split into OFFLINE and ONLINE_AFK slot specifications.

    Determines if an AFK event (status="afk") represents a real offline period or a false positive.
    A valid OFFLINE period must be a single continuous gap with no window coverage, lasting at least
    min_off_duration. If the gap is fragmented or too small, emits only ONLINE_AFK portions (where
    windows exist) and ignores the small gaps.

    Args:
        afk_event: AFK bucket event (should have status="afk")
        window_events: Window bucket events overlapping the AFK period
        min_off_duration: Minimum continuous gap to classify as SYSTEM OFF.
            Defaults to SYSTEM_OFF_MINIMUM_DURATION if not provided.

    Returns:
        dict with:
            "valid_offline": bool - whether a valid continuous OFFLINE period was found
            "offline_portion": (datetime_start, datetime_end) | None - SYSTEM OFF period (if valid)
            "online_afk_portions": [(datetime_start, datetime_end), ...] - SYSTEM ON portions with AFK
                For valid OFFLINE: portions between/around windows and the OFFLINE gap
                For invalid OFFLINE: all portions with window activity

    Example:
        AFK: 10:00-11:00 (60 min), Windows: [10:05-10:20], [10:30-10:40]
        → Gaps: [10:00-10:05], [10:20-10:30], [10:40-11:00] (fragmented)
        → valid_offline: False
        → online_afk_portions: [(10:05-10:20), (10:30-10:40)]  (only window-covered portions)

        AFK: 10:00-11:00 (60 min), Windows: [10:10-10:20]
        → Gaps: [10:00-10:10], [10:20-11:00] (two blocks, not continuous)
        → valid_offline: False
        → online_afk_portions: [(10:10-10:20)]

        AFK: 10:00-11:00 (60 min), No windows
        → Gaps: [10:00-11:00] (one continuous block, 60 min)
        → valid_offline: True (duration >= min_off_duration)
        → offline_portion: (10:00-11:00)
        → online_afk_portions: []
    """
    if min_off_duration is None:
        min_off_duration = SYSTEM_OFF_MINIMUM_DURATION

    afk_start = afk_event.timestamp
    afk_end = afk_event.timestamp + afk_event.duration

    # If no window events provided (e.g., AFK optimization mode), assume all AFK is real
    # This is a safe fallback: if we can't validate with windows, trust the AFK status
    if not window_events:
        return {
            "valid_offline": False,
            "offline_portion": None,
            "online_afk_portions": [(afk_start, afk_end)],  # Entire AFK period treated as ONLINE_AFK
        }

    # Filter windows that overlap this AFK period and sort by start time
    overlapping_windows = []
    for w in window_events:
        w_start = w.timestamp
        w_end = w_start + w.duration
        # Check if window overlaps AFK period
        if w_start < afk_end and w_end > afk_start:
            overlapping_windows.append(w)

    overlapping_windows.sort(key=lambda w: w.timestamp)

    # If no windows (shouldn't happen after the check above), entire AFK is offline
    if not overlapping_windows:
        return {
            "valid_offline": afk_event.duration >= min_off_duration,
            "offline_portion": (afk_start, afk_end),
            "online_afk_portions": [],
        }

    # Calculate complement: gaps where there are no windows
    # These are the potential SYSTEM OFF portions
    gaps = []

    # Gap before first window
    first_window_start = overlapping_windows[0].timestamp
    if first_window_start > afk_start:
        gaps.append((afk_start, first_window_start))

    # Gaps between consecutive windows
    for i in range(len(overlapping_windows) - 1):
        curr_window = overlapping_windows[i]
        next_window = overlapping_windows[i + 1]

        curr_end = curr_window.timestamp + curr_window.duration
        next_start = next_window.timestamp

        if next_start > curr_end:
            gaps.append((curr_end, next_start))

    # Gap after last window
    last_window = overlapping_windows[-1]
    last_window_end = last_window.timestamp + last_window.duration
    if last_window_end < afk_end:
        gaps.append((last_window_end, afk_end))

    # Check if complement is a single continuous block
    if len(gaps) != 1:
        # Fragmented gaps: not a valid OFFLINE period
        # System was on, user was idle - emit entire AFK period as ONLINE_AFK
        return {
            "valid_offline": False,
            "offline_portion": None,
            "online_afk_portions": [(afk_start, afk_end)],
        }

    # Single continuous gap: check if it meets minimum duration
    gap_start, gap_end = gaps[0]
    gap_duration = gap_end - gap_start

    if gap_duration < min_off_duration:
        # Gap too small: not a valid OFFLINE period
        # System was on, user was idle - emit entire AFK period as ONLINE_AFK
        return {
            "valid_offline": False,
            "offline_portion": None,
            "online_afk_portions": [(afk_start, afk_end)],
        }

    # Valid OFFLINE period found
    # Merge overlapping/adjacent windows into consolidated ONLINE_AFK periods
    # Sort windows by start time
    sorted_windows = sorted(overlapping_windows, key=lambda w: w.timestamp)

    merged_periods = []
    current_start = None
    current_end = None

    for w in sorted_windows:
        w_start = w.timestamp
        w_end = w_start + w.duration

        if current_start is None:
            # First window
            current_start = w_start
            current_end = w_end
        elif w_start <= current_end:
            # Overlapping or adjacent window - extend current period
            current_end = max(current_end, w_end)
        else:
            # Gap found - save current period and start new one
            merged_periods.append((current_start, current_end))
            current_start = w_start
            current_end = w_end

    # Don't forget the last period
    if current_start is not None:
        merged_periods.append((current_start, current_end))

    return {
        "valid_offline": True,
        "offline_portion": (gap_start, gap_end),
        "online_afk_portions": merged_periods,
    }

"""Session-merging consolidation logic for --consolidate flag.

The --consolidate flag merges consecutive sessions of the same task
(project + task) into single entries, even if there are gaps between them,
unless interrupted by a different task.

This is orthogonal to period-level consolidation (--consolidate-day/week/month/year)
which groups by time periods instead.

Example:
  Input:  Task A (1h) → Task A (gap 30m) → Task A (1h) → Task B (1h)
  Output: Task A (2.5h) → Task B (1h)  [gap is bridged]
"""

from datetime import timedelta
from typing import Any, Dict, List, Union


def consolidate_sessions(
    slots: List[Union[Dict[str, Any], "ReportTimelineSlot"]],
) -> List[Union[Dict[str, Any], "ReportTimelineSlot"]]:
    """Merge consecutive sessions of the same (project, task) into one slot.

    Sessions of the same task are merged even with gaps between them,
    unless interrupted by a different task. The merged slot spans from
    the start of the first session to the end of the last session.

    Args:
        slots: List of slot dicts or ReportTimelineSlot objects, chronologically ordered.

    Returns:
        List of consolidated slots with consecutive same-task sessions merged.

    Example:
        >>> slots = [
        ...     {"start": t1, "duration": 1h, "task": "A"},
        ...     {"start": t1+1.5h, "duration": 1h, "task": "A"},  # gap 30m
        ...     {"start": t1+3h, "duration": 1h, "task": "B"},
        ... ]
        >>> consolidated = consolidate_sessions(slots)
        >>> len(consolidated)
        2  # Two slots: A (merged 2.5h) and B (1h)
    """
    if not slots:
        return []

    # Convert to dicts for consistent handling
    slot_dicts = [_to_dict(slot) for slot in slots]

    # Group consecutive slots by (project, task)
    merged = []
    current_group = [slot_dicts[0]]

    for i in range(1, len(slot_dicts)):
        slot = slot_dicts[i]
        last_slot = current_group[-1]

        # Check if this slot belongs to the same group
        if _same_group(slot, last_slot):
            current_group.append(slot)
        else:
            # Different task/project - finalize and start new group
            merged.append(_merge_group(current_group))
            current_group = [slot]

        
    # Don't forget the last group
    merged.append(_merge_group(current_group))


    return merged


def _to_dict(slot: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
    """Convert slot to dict if it's an object."""
    if isinstance(slot, dict):
        return slot
    # Assume it's a ReportTimelineSlot or similar object
    return {
        "start": slot.start,
        "duration": slot.duration,
        "actual_duration": getattr(slot, "actual_duration", slot.duration),
        "project": slot.project,
        "task": slot.task,
        "tags": getattr(slot, "tags", []),
        "event_duration": getattr(slot, "event_duration", slot.duration),
        "is_offline_task": getattr(slot, "is_offline_task", False),
        "is_afk_only": getattr(slot, "is_afk_only", False),
        "afk_duration": getattr(slot, "afk_duration", None),
        "productive_duration": getattr(slot, "productive_duration", timedelta(0)),
    }


def _same_group(slot: Dict[str, Any], last_slot: Dict[str, Any]) -> bool:
    """Check if two slots belong to the same consolidation group."""
    same = (
        slot.get("project") == last_slot.get("project")
        and slot.get("task") == last_slot.get("task")
    )

    return same


def _merge_group(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a group of consecutive slots of the same task into one.

    The merged slot spans from the start of the first slot to the end of
    the last slot, bridging any gaps between them.

    Args:
        group: List of slot dicts, all with the same (project, task).

    Returns:
        Merged slot dict spanning the full time range of the group.
    """
    if len(group) == 1:
        return group[0]


    # Calculate total duration from first start to last end
    first_slot = group[0]
    last_slot = group[-1]

    start_time = first_slot["start"]

    # Use "end" field if available, otherwise calculate from start + duration
    if "end" in last_slot and last_slot["end"] is not None:
        end_time = last_slot["end"]
    else:
        end_time = last_slot["start"] + last_slot["duration"]

    merged_duration = end_time - start_time

    # Sum actual_duration values (active time, excluding AFK gaps within slots)
    total_actual_duration = sum(
        (slot.get("actual_duration", slot["duration"]) for slot in group),
        timedelta(0),
    )

    # Sum afk_duration values (idle time within slots)
    total_afk_duration = sum(
        (slot.get("afk_duration", timedelta(0)) for slot in group if slot.get("afk_duration")),
        timedelta(0),
    )

    # Sum event_duration values (actual time spent on task, without gaps)
    total_event_duration = sum(
        (slot.get("event_duration", slot["duration"]) for slot in group),
        timedelta(0),
    )

    # Sum offline_extension_duration if any slot has it (offline task tracking)
    total_offline_extension = sum(
        (slot.get("offline_extension_duration", timedelta(0)) for slot in group if slot.get("offline_extension_duration")),
        timedelta(0),
    )

    # Create merged slot by copying first and updating key fields
    merged = first_slot.copy()
    merged["start"] = start_time
    merged["end"] = end_time
    merged["duration"] = merged_duration  # Wall-clock duration (includes gaps between sessions)
    merged["actual_duration"] = total_actual_duration  # Sum of active time (excludes AFK within slots)
    merged["afk_duration"] = total_afk_duration if total_afk_duration > timedelta(0) else None  # Sum of AFK time
    merged["event_duration"] = total_event_duration  # Sum of event durations

    # Preserve offline_extension_duration if present (offline task tracking)
    if total_offline_extension > timedelta(0):
        merged["offline_extension_duration"] = total_offline_extension

    # Tags should be consistent (all same), but preserve from first slot
    if group and group[0].get("tags"):
        merged["tags"] = group[0]["tags"]

    return merged

"""
Timeline and TimelineSlot abstractions for granular timeslot management.

This module provides type-safe representations of timeline data without
aggregation. Consolidation and merging are separate operations.

TimelineSlot: Represents a single granular timeslot with all tracked metadata
Timeline: Manages a sorted collection of TimelineSlots
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


class TimelineSlotValidationError(ValueError):
    """Raised when a TimelineSlot is missing required data or has inconsistent fields.

    CONTEXT: This exception was added to prevent silent data quality issues.
    Prior to hardening, TimelineSlot.__post_init__ would silently default
    actual_duration = duration when not explicitly provided. This masked a bug where
    offline_task slots had their duration incorrectly sourced, resulting in negative
    offline times being displayed (e.g., -1:46:24 OFF instead of 0:00:05 OFF).

    By raising an error when required data is missing, we ensure bugs surface
    immediately at construction time, not hours later during analysis.
    """

    pass


@dataclass
class TimelineSlot:
    """
    Represents a single granular timeslot.

    This is the atomic unit of timeline data. No aggregation happens here.
    All fields represent raw, unaggregated tracking data.

    Attributes:
        type: Slot type. Valid values: 'regular', 'afk', 'offline', 'offline_extension', 'offline_task'
        start: Slot start time (timezone-aware)
        end: Slot end time (timezone-aware)
        project: Project name
        task: Task name
        duration: Wall-clock duration of the slot (from start to end)
        actual_duration: Time spent on actual activity (e.g., duration minus AFK time for regular slots).
                         Required field — must be explicitly set, never silently defaulted.
        productive_duration: Time spent on productive activities
        categories: List of category/app/title breakdown
        tags: Tags associated with the slot
        afk_duration: AFK time within this slot (if applicable)
        offline_extension_duration: OFFLINE gap time within this slot
        event_duration: Duration of tracked events (for offline tasks, represents online time)
        apps: App/title information (legacy format)
    """

    type: str
    start: datetime
    end: datetime
    project: str
    task: str
    duration: timedelta
    productive_duration: timedelta = field(default_factory=lambda: timedelta(0))
    categories: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    actual_duration: Optional[timedelta] = None
    afk_duration: Optional[timedelta] = None
    offline_extension_duration: Optional[timedelta] = None
    event_duration: Optional[timedelta] = None
    apps: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self):
        """Validate and normalize slot data.

        DESIGN: This method enforces invariants that prevent silent data quality issues.
        Unlike the prior behavior (silently defaulting actual_duration = duration),
        we now fail fast with detailed context. This catches bugs immediately rather
        than allowing them to propagate downstream.

        Checks:
        1. actual_duration is explicit (never inferred) — this is the core fix for
           the offline-time-negativity bug. Each slot type must explicitly set it
           (e.g., afk/offline use duration; offline_task uses online time).
        2. end is consistent with start+duration (within 1s tolerance for float drift).
           This prevents stale end values from day-splitting or other mutations.
        3. offline_task slots must have event_duration for the offline/online split display.
        """
        ctx = f"type={self.type!r} project={self.project!r} task={self.task!r} start={self.start!r}"

        # CRITICAL: actual_duration must be explicit. This was the root cause of
        # negative offline times: prior silent default masked incorrect duration sources.
        if self.actual_duration is None:
            raise TimelineSlotValidationError(
                f"TimelineSlot missing required 'actual_duration' ({ctx}). "
                "actual_duration must be explicitly provided (e.g. equal to duration "
                "for afk/offline slots, or the computed online/tracked time for "
                "offline_task slots) — it is never silently inferred."
            )

        # Ensure end matches start+duration. Prevents downstream code from having
        # to recompute or work around stale end values from split-slot mutations.
        expected_end = self.start + self.duration
        if abs((self.end - expected_end).total_seconds()) > 1:
            raise TimelineSlotValidationError(
                f"TimelineSlot 'end' ({self.end}) is inconsistent with "
                f"start+duration ({expected_end}) ({ctx}). "
                f"Difference: {(self.end - expected_end).total_seconds()} seconds."
            )

        # offline_task slots require event_duration to display the offline/online split.
        # Without it, the display logic cannot compute offline_time = duration - event_duration.
        if self.type == "offline_task" and self.event_duration is None:
            raise TimelineSlotValidationError(
                f"offline_task slot missing required 'event_duration' ({ctx}). "
                "event_duration is required to compute the offline/online split display."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict format for compatibility with existing code."""
        d = {
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "project": self.project,
            "task": self.task,
            "duration": self.duration,
            "actual_duration": self.actual_duration,
            "productive_duration": self.productive_duration,
        }
        if self.categories:
            d["categories"] = self.categories
        if self.tags:
            d["tags"] = self.tags
        if self.afk_duration:
            d["afk_duration"] = self.afk_duration
        if self.offline_extension_duration:
            d["offline_extension_duration"] = self.offline_extension_duration
        # Always include event_duration if it exists (even if 0), since offline_task slots
        # require it for validation. timedelta(0) is falsy, so check is not None explicitly.
        if self.event_duration is not None:
            d["event_duration"] = self.event_duration
        if self.apps:
            d["apps"] = self.apps
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TimelineSlot":
        """Create TimelineSlot from dict (for compatibility).

        HARDENING: This method enforces all required fields to prevent silent data loss.
        Prior behavior: actual_duration would silently default in __post_init__.
        New behavior: raises TimelineSlotValidationError if missing.

        Required keys (enforced):
            type: slot type ('regular', 'afk', 'offline', 'offline_extension', 'offline_task')
            start: start time (datetime)
            duration: wall-clock duration (timedelta)
            actual_duration: actual activity duration (timedelta) — must be explicit, never inferred

        Derived (if missing):
            end: computed as start + duration if not provided in dict. This enables:
                 - Consolidation code to build dicts without computing end (we derive it)
                 - Consistency validation in __post_init__ to catch mutations

        Raises TimelineSlotValidationError if any required key is missing.
        """

        def _require(key: str):
            if key not in d or d[key] is None:
                ctx = f"project={d.get('project')!r} task={d.get('task')!r} start={d.get('start')!r} type={d.get('type')!r}"
                raise TimelineSlotValidationError(
                    f"TimelineSlot.from_dict: missing required key {key!r} ({ctx})"
                )
            return d[key]

        _require("type")
        _require("start")
        _require("duration")
        _require("actual_duration")

        start = d["start"]
        duration = d["duration"]
        end = d.get("end")
        if end is None:
            end = start + duration

        return cls(
            type=d["type"],
            start=start,
            end=end,
            project=d.get("project", ""),
            task=d.get("task", ""),
            duration=duration,
            productive_duration=d.get("productive_duration", timedelta(0)),
            categories=d.get("categories", []),
            tags=d.get("tags", []),
            actual_duration=d["actual_duration"],
            afk_duration=d.get("afk_duration"),
            offline_extension_duration=d.get("offline_extension_duration"),
            event_duration=d.get("event_duration"),
            apps=d.get("apps"),
        )

    def overlaps(self, other: "TimelineSlot") -> bool:
        """Check if this slot overlaps with another slot."""
        return self.start < other.end and self.end > other.start

    def contains(self, dt: datetime) -> bool:
        """Check if a datetime falls within this slot."""
        return self.start <= dt < self.end


class Timeline:
    """
    Manages a sorted collection of TimelineSlots.

    This class maintains slots in chronological order and provides
    a clean API for operations. It stores GRANULAR data only -
    consolidation and merging are separate operations.
    """

    def __init__(self):
        """Initialize empty timeline."""
        self.slots: List[TimelineSlot] = []

    def add_slot(self, slot: TimelineSlot) -> None:
        """
        Add a slot to the timeline, maintaining sort order.

        Args:
            slot: TimelineSlot to add
        """
        self.slots.append(slot)
        self._sort()

    def add_slots(self, slots: List[TimelineSlot]) -> None:
        """
        Add multiple slots, maintaining sort order.

        Args:
            slots: List of TimelineSlots to add
        """
        self.slots.extend(slots)
        self._sort()

    def add_from_dict(self, slot_dict: Dict[str, Any]) -> None:
        """
        Add a slot from dict format (for compatibility).

        Args:
            slot_dict: Dictionary representation of a slot
        """
        slot = TimelineSlot.from_dict(slot_dict)
        self.add_slot(slot)

    def get_slots(self) -> List[TimelineSlot]:
        """Get all slots in chronological order."""
        return list(self.slots)

    def get_slots_as_dicts(self) -> List[Dict[str, Any]]:
        """Get all slots as dicts (for compatibility)."""
        return [slot.to_dict() for slot in self.slots]

    def get_slots_in_range(self, start: datetime, end: datetime) -> List[TimelineSlot]:
        """
        Get slots within a time range.

        Args:
            start: Range start time
            end: Range end time

        Returns:
            List of slots that overlap the range
        """
        return [s for s in self.slots if s.start < end and s.end > start]

    def get_slots_by_project(self, project: str) -> List[TimelineSlot]:
        """Get all slots for a specific project."""
        return [s for s in self.slots if s.project == project]

    def get_slots_by_task(self, project: str, task: str) -> List[TimelineSlot]:
        """Get all slots for a specific (project, task) pair."""
        return [s for s in self.slots if s.project == project and s.task == task]

    def get_slots_by_type(self, slot_type: str) -> List[TimelineSlot]:
        """Get all slots of a specific type."""
        return [s for s in self.slots if s.type == slot_type]

    def total_duration(self) -> timedelta:
        """Calculate total duration across all slots."""
        return sum((s.duration for s in self.slots), timedelta(0))

    def total_actual_duration(self) -> timedelta:
        """Calculate total actual duration across all slots."""
        return sum((s.actual_duration or s.duration for s in self.slots), timedelta(0))

    def total_productive_duration(self) -> timedelta:
        """Calculate total productive duration across all slots."""
        return sum((s.productive_duration for s in self.slots), timedelta(0))

    def count(self) -> int:
        """Get number of slots in timeline."""
        return len(self.slots)

    def _sort(self) -> None:
        """Sort slots by start time (internal method)."""
        self.slots.sort(key=lambda s: s.start)

    def __iter__(self):
        """Iterate over slots in chronological order."""
        return iter(self.slots)

    def __len__(self):
        """Get number of slots."""
        return len(self.slots)

    def __repr__(self):
        """String representation."""
        return f"Timeline({len(self.slots)} slots, {self.total_duration()})"

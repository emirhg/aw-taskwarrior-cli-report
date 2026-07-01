"""
Timeline and TimelineSlot abstractions for granular timeslot management.

This module provides type-safe representations of timeline data without
aggregation. Consolidation and merging are separate operations.

TimelineSlot: Represents a single granular timeslot with all tracked metadata
Timeline: Manages a sorted collection of TimelineSlots
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any


@dataclass
class TimelineSlot:
    """
    Represents a single granular timeslot.

    This is the atomic unit of timeline data. No aggregation happens here.
    All fields represent raw, unaggregated tracking data.

    Attributes:
        type: Slot type ('task', 'afk', 'offline_task', 'offline', 'offline_extension')
        start: Slot start time (timezone-aware)
        end: Slot end time (timezone-aware)
        project: Project name
        task: Task name
        duration: Actual duration of work (not wall-clock)
        productive_duration: Time spent on productive activities
        categories: List of category/app/title breakdown
        tags: Tags associated with the slot
        actual_duration: Alternative duration field (for compatibility)
        afk_duration: AFK time within this slot (if applicable)
        offline_extension_duration: OFFLINE gap time within this slot
        event_duration: Duration of tracked events (for offline tasks)
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
        """Validate and normalize slot data."""
        if self.actual_duration is None:
            self.actual_duration = self.duration

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
        if self.event_duration:
            d["event_duration"] = self.event_duration
        if self.apps:
            d["apps"] = self.apps
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'TimelineSlot':
        """Create TimelineSlot from dict (for compatibility)."""
        return cls(
            type=d.get("type", "task"),
            start=d["start"],
            end=d["end"],
            project=d.get("project", ""),
            task=d.get("task", ""),
            duration=d.get("duration", timedelta(0)),
            productive_duration=d.get("productive_duration", timedelta(0)),
            categories=d.get("categories", []),
            tags=d.get("tags", []),
            actual_duration=d.get("actual_duration"),
            afk_duration=d.get("afk_duration"),
            offline_extension_duration=d.get("offline_extension_duration"),
            event_duration=d.get("event_duration"),
            apps=d.get("apps"),
        )

    def overlaps(self, other: 'TimelineSlot') -> bool:
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
        return [s for s in self.slots if s.overlaps(TimelineSlot(
            type="", start=start, end=end, project="", task="", duration=timedelta(0)
        ))]

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

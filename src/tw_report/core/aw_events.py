"""
Typed subclasses of aw_core.models.Event for bucket-specific event data.

This module provides three specialized Event subclasses, one per ActivityWatch bucket:
- WindowEvent: for window/desktop-activity events (app, title, category)
- AFKEvent: for away-from-keyboard events (status)
- TaskWarriorEvent: for TaskWarrior task-tracking events (project, task, tags, uuid)

Each subclass wraps the underlying Event.data dict with typed properties, replacing
dozens of scattered `.data.get(...)` duck-typing calls throughout the codebase with
a single source of truth for how to extract each bucket's schema.
"""

from datetime import timedelta
from typing import List, Optional

from aw_core.models import Event


class WindowEvent(Event):
    """Event from the window/desktop-activity bucket."""

    @property
    def app(self) -> str:
        """Application name."""
        return self.data.get("app", "Unknown App")

    @property
    def title(self) -> str:
        """Window title."""
        return self.data.get("title", "No Title")

    @property
    def category(self) -> List[str]:
        """Category breakdown (app classification)."""
        return self.data.get("$category", ["Uncategorized"])

    @category.setter
    def category(self, value: List[str]) -> None:
        """Set category breakdown."""
        self.data["$category"] = value

    @property
    def offline_extension_duration(self) -> Optional[timedelta]:
        """OFFLINE gap duration detected within this window event."""
        return self.data.get("offline_extension_duration")

    @offline_extension_duration.setter
    def offline_extension_duration(self, value: Optional[timedelta]) -> None:
        """Set offline extension duration."""
        if value is None:
            self.data.pop("offline_extension_duration", None)
        else:
            self.data["offline_extension_duration"] = value


class AFKEvent(Event):
    """Event from the afk bucket (away-from-keyboard tracking)."""

    @property
    def status(self) -> str:
        """AFK status: 'afk' or 'not-afk'."""
        return self.data.get("status", "unknown")

    @property
    def is_afk(self) -> bool:
        """True if status is 'afk'."""
        return self.status == "afk"


class TaskWarriorEvent(Event):
    """Event from the taskwarrior bucket (TaskWarrior task tracking)."""

    @property
    def task(self) -> str:
        """Task name/description. Falls back through title, label, task, then NO_TASK."""
        from tw_report.core.filtering import NO_TASK

        return (
            self.data.get("title")
            or self.data.get("label")
            or self.data.get("task")
            or NO_TASK
        )

    @property
    def project(self) -> str:
        """Project name."""
        from tw_report.core.filtering import NO_PROJECT

        return self.data.get("project", NO_PROJECT)

    @property
    def tags(self) -> List[str]:
        """Tags associated with the task, normalized to a list."""
        raw = self.data.get("tags", [])
        return [raw] if isinstance(raw, str) else list(raw)

    @property
    def has_offline_tag(self) -> bool:
        """True if the task is tagged 'offline'."""
        return "offline" in (t.lower() for t in self.tags)

    @property
    def uuid(self) -> Optional[str]:
        """Task UUID."""
        return self.data.get("uuid")


# Map from ActivityWatch bucket name to Event subclass
# Used when fetching events to re-wrap them in the appropriate typed class
BUCKET_EVENT_CLASSES = {
    "window": WindowEvent,
    "afk": AFKEvent,
    "taskwarrior": TaskWarriorEvent,
}

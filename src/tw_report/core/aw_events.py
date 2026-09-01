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


SYSTEM_OFF_MINIMUM_DURATION = timedelta(minutes=1)


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
    """Event from TaskWarrior tracking."""

    @property
    def project(self) -> str:
        """Project name."""
        return self.data.get("project", "No project")

    @property
    def task(self) -> str:
        """Task name."""
        return self.data.get("task", "No task")

    @property
    def uuid(self) -> Optional[str]:
        """TaskWarrior UUID."""
        return self.data.get("uuid")

    @property
    def tags(self) -> List[str]:
        """Task tags."""
        return self.data.get("tags", [])

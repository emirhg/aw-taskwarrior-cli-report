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
        """Task name/identifier: explicit task field, else description, else UUID (short), else 'No task'."""
        # Prefer explicit 'task' field if present (some workflows may set this)
        if "task" in self.data and self.data["task"]:
            return self.data["task"]
        # Fall back to description (human-readable task name from TaskWarrior)
        if "description" in self.data and self.data["description"]:
            desc = self.data["description"]
            # Truncate to ~40 chars for display; remove URLs
            if "http" in desc:
                # Extract just the problem name/number if it's a LeetCode URL
                if "leetcode" in desc.lower():
                    parts = desc.split(":")
                    if len(parts) > 1:
                        return parts[0].strip()
            return desc[:50] if len(desc) > 50 else desc
        # Fall back to UUID (short form for identification)
        if "uuid" in self.data and self.data["uuid"]:
            uuid_str = self.data["uuid"]
            return uuid_str[:8]
        # Last resort
        return "No task"

    @property
    def uuid(self) -> Optional[str]:
        """TaskWarrior UUID."""
        return self.data.get("uuid")

    @property
    def tags(self) -> List[str]:
        """Task tags."""
        return self.data.get("tags", [])

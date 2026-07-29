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

    def split_by_coverage(self, window_events: List["WindowEvent"], min_off_duration: Optional[timedelta] = None) -> dict:
        """Classify this AFK event and split into OFFLINE and ONLINE_AFK portions.

        Determines if this AFK event (status="afk") represents a real offline period or a false positive.
        A valid OFFLINE period must be a single continuous gap with no window coverage, lasting at least
        min_off_duration. If the gap is fragmented or too small, emits only ONLINE_AFK portions (where
        windows exist) and ignores the small gaps.

        Args:
            window_events: Window bucket events overlapping this AFK period
            min_off_duration: Minimum continuous gap to classify as SYSTEM OFF.
                Defaults to SYSTEM_OFF_MINIMUM_DURATION if not provided.

        Returns:
            dict with:
                "is_false_positive": bool - whether this is a false positive (system was off)
                "offline_portion": (datetime_start, datetime_end) | None - SYSTEM OFF period (if valid)
                "online_afk_portions": [(datetime_start, datetime_end), ...] - SYSTEM ON portions with AFK

        Example:
            AFK: 10:00-11:00 (60 min), Windows: [10:05-10:20], [10:30-10:40]
            → Gaps: [10:00-10:05], [10:20-10:30], [10:40-11:00] (fragmented)
            → is_false_positive: True (detected as offline)
            → online_afk_portions: [(10:05-10:20), (10:30-10:40)]

            AFK: 10:00-11:00 (60 min), No windows
            → is_false_positive: False (entire period is offline)
            → offline_portion: (10:00-11:00)
            → online_afk_portions: []
        """
        import sys
        if min_off_duration is None:
            min_off_duration = SYSTEM_OFF_MINIMUM_DURATION

        afk_start = self.timestamp
        afk_end = self.timestamp + self.duration

        # If no window events provided/found, system was off (no recording data)
        # Treat entire AFK period as OFFLINE (false positive AFK from AFK bucket)
        if not window_events:
            return {
                "is_false_positive": True,
                "offline_portion": (afk_start, afk_end),
                "online_afk_portions": [],
            }

        # Filter windows that overlap this AFK period and sort by start time
        overlapping_windows = []
        for w in window_events:
            w_start = w.timestamp
            w_end = w_start + w.duration
            if w_start < afk_end and w_end > afk_start:
                overlapping_windows.append(w)

        overlapping_windows.sort(key=lambda w: w.timestamp)

        # If no windows, entire AFK is offline
        if not overlapping_windows:
            return {
                "is_false_positive": self.duration >= min_off_duration,
                "offline_portion": (afk_start, afk_end),
                "online_afk_portions": [],
            }

        # Calculate complement: gaps where there are no windows
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
        import sys
        if len(gaps) != 1:
            # Multiple gaps detected. Classify based on gap structure:
            # - If gaps are small (< 5 min each): system was on, user was idle (fragmented work)
            # - If there's ONE large gap (> 1 hour): system was off, came back online briefly
            largest_gap_duration = max((g[1] - g[0] for g in gaps), default=timedelta(0))

            if largest_gap_duration > timedelta(hours=1):
                # System was off - use largest gap as offline period
                offline_start, offline_end = max(gaps, key=lambda g: g[1] - g[0])
                return {
                    "is_false_positive": False,
                    "offline_portion": (offline_start, offline_end),
                    "online_afk_portions": [(g[0], g[1]) for g in gaps if (g[1] - g[0]) < timedelta(hours=1)],
                }
            else:
                # All gaps small: system was on, user was idle (fragmented work periods)
                return {
                    "is_false_positive": True,
                    "offline_portion": None,
                    "online_afk_portions": [(afk_start, afk_end)],
                }

        # Single continuous gap: check if it meets minimum duration
        gap_start, gap_end = gaps[0]
        gap_duration = gap_end - gap_start

        if gap_duration < min_off_duration:
            # Gap too small: system was on, user was idle
            return {
                "is_false_positive": True,
                "offline_portion": None,
                "online_afk_portions": [(afk_start, afk_end)],
            }

        # Valid OFFLINE period found
        # Merge overlapping/adjacent windows into consolidated ONLINE_AFK periods
        sorted_windows = sorted(overlapping_windows, key=lambda w: w.timestamp)
        merged_periods = []
        current_start = None
        current_end = None

        for w in sorted_windows:
            w_start = w.timestamp
            w_end = w_start + w.duration

            if current_start is None:
                current_start = w_start
                current_end = w_end
            elif w_start <= current_end:
                current_end = max(current_end, w_end)
            else:
                merged_periods.append((current_start, current_end))
                current_start = w_start
                current_end = w_end

        if current_start is not None:
            merged_periods.append((current_start, current_end))

        return {
            "is_false_positive": False,
            "offline_portion": (gap_start, gap_end),
            "online_afk_portions": merged_periods,
        }

    def is_false_positive(self, window_events: List["WindowEvent"]) -> bool:
        """Check if this AFK event is a false positive (system was offline).

        Args:
            window_events: Window bucket events to check coverage against

        Returns:
            True if system was offline during this AFK period, False if truly idle
        """
        return self.split_by_coverage(window_events)["is_false_positive"]


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

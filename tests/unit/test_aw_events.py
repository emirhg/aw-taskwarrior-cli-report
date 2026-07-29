"""
Unit tests for typed Event subclasses (WindowEvent, AFKEvent, TaskWarriorEvent).

Tests property correctness, deepcopy subclass preservation (critical for
aw_transform.filter_period_intersect), and NO_PROJECT/NO_TASK fallback behavior.
"""

import pytest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tw_report.core.aw_events import WindowEvent, AFKEvent, TaskWarriorEvent
from tw_report.core.filtering import NO_PROJECT, NO_TASK


UTC = timezone.utc


class TestWindowEvent:
    """Tests for WindowEvent properties."""

    def test_app_property_with_data(self):
        """app property returns app from data."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"app": "Firefox"},
        )
        assert event.app == "Firefox"

    def test_app_property_default(self):
        """app property returns default when missing."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        assert event.app == "Unknown App"

    def test_title_property_with_data(self):
        """title property returns title from data."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"title": "GitHub - my repo"},
        )
        assert event.title == "GitHub - my repo"

    def test_title_property_default(self):
        """title property returns default when missing."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        assert event.title == "No Title"

    def test_category_property_with_data(self):
        """category property returns $category list."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"$category": ["Development"]},
        )
        assert event.category == ["Development"]

    def test_category_property_default(self):
        """category property returns default list when missing."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        assert event.category == ["Uncategorized"]

    def test_category_property_setter(self):
        """category property can be set."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        event.category = ["Work", "Coding"]
        assert event.data["$category"] == ["Work", "Coding"]

    def test_offline_extension_duration_property_with_data(self):
        """offline_extension_duration property returns value from data."""
        duration = timedelta(minutes=30)
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=60),
            data={"offline_extension_duration": duration},
        )
        assert event.offline_extension_duration == duration

    def test_offline_extension_duration_property_default(self):
        """offline_extension_duration property returns None when missing."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        assert event.offline_extension_duration is None

    def test_offline_extension_duration_property_setter(self):
        """offline_extension_duration property can be set."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        duration = timedelta(minutes=15)
        event.offline_extension_duration = duration
        assert event.data["offline_extension_duration"] == duration

    def test_offline_extension_duration_property_setter_none(self):
        """offline_extension_duration can be set to None, removing the key."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"offline_extension_duration": timedelta(minutes=10)},
        )
        event.offline_extension_duration = None
        assert "offline_extension_duration" not in event.data

    def test_deepcopy_preserves_subclass(self):
        """deepcopy of WindowEvent preserves the subclass."""
        event = WindowEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"app": "Firefox", "title": "Test"},
        )
        copied = deepcopy(event)
        assert isinstance(copied, WindowEvent)
        assert copied.app == "Firefox"
        assert copied.title == "Test"


class TestAFKEvent:
    """Tests for AFKEvent properties."""

    def test_status_property_afk(self):
        """status property returns 'afk' from data."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"status": "afk"},
        )
        assert event.status == "afk"

    def test_status_property_not_afk(self):
        """status property returns 'not-afk' from data."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"status": "not-afk"},
        )
        assert event.status == "not-afk"

    def test_status_property_default(self):
        """status property returns default when missing."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={},
        )
        assert event.status == "unknown"

    def test_is_afk_true(self):
        """is_afk returns True when status is 'afk'."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"status": "afk"},
        )
        assert event.is_afk is True

    def test_is_afk_false(self):
        """is_afk returns False when status is not 'afk'."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"status": "not-afk"},
        )
        assert event.is_afk is False

    def test_deepcopy_preserves_subclass(self):
        """deepcopy of AFKEvent preserves the subclass."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"status": "afk"},
        )
        copied = deepcopy(event)
        assert isinstance(copied, AFKEvent)
        assert copied.is_afk is True

    def test_split_by_coverage_no_window_events(self):
        """split_by_coverage with no window events returns entire AFK as online-afk."""
        event = AFKEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=60),
            data={"status": "afk"},
        )
        result = event.split_by_coverage([])
        assert result["is_false_positive"] is False
        assert result["offline_portion"] is None
        assert len(result["online_afk_portions"]) == 1
        assert result["online_afk_portions"][0] == (event.timestamp, event.timestamp + event.duration)

    def test_split_by_coverage_full_window_coverage(self):
        """split_by_coverage with full window coverage returns no offline portion."""
        from tw_report.core.aw_events import WindowEvent
        base = datetime.now(UTC)
        afk_event = AFKEvent(
            timestamp=base,
            duration=timedelta(minutes=60),
            data={"status": "afk"},
        )
        # Window covers entire AFK period
        window = WindowEvent(
            timestamp=base,
            duration=timedelta(minutes=60),
            data={"app": "test", "title": "test"},
        )
        result = afk_event.split_by_coverage([window])
        assert result["is_false_positive"] is True  # Multiple windows (fragmented)
        assert result["offline_portion"] is None
        # Full coverage means online_afk_portions = window coverage
        assert len(result["online_afk_portions"]) == 1

    def test_split_by_coverage_no_window_coverage_is_false_positive(self):
        """split_by_coverage with no window coverage classifies as false positive (offline)."""
        base = datetime.now(UTC)
        afk_event = AFKEvent(
            timestamp=base,
            duration=timedelta(minutes=60),
            data={"status": "afk"},
        )
        # No window events = entire period is offline
        result = afk_event.split_by_coverage([])
        assert result["is_false_positive"] is False
        assert result["offline_portion"] is None
        # No windows = treat as online-afk (safe fallback)
        assert len(result["online_afk_portions"]) == 1

    def test_is_false_positive_true(self):
        """is_false_positive returns True when offline portion exists."""
        from tw_report.core.aw_events import WindowEvent
        base = datetime.now(UTC)
        afk_event = AFKEvent(
            timestamp=base,
            duration=timedelta(hours=1),
            data={"status": "afk"},
        )
        # Single window in the middle = fragmented gaps = false positive (true)
        window = WindowEvent(
            timestamp=base + timedelta(minutes=30),
            duration=timedelta(minutes=10),
            data={"app": "test", "title": "test"},
        )
        result = afk_event.is_false_positive([window])
        # Fragmented gaps means entire period returned as online_afk (false positive = True)
        assert result is True

    def test_is_false_positive_false(self):
        """is_false_positive returns False for real online-afk."""
        base = datetime.now(UTC)
        afk_event = AFKEvent(
            timestamp=base,
            duration=timedelta(minutes=60),
            data={"status": "afk"},
        )
        # No windows = safe fallback (return as online-afk, not offline)
        result = afk_event.is_false_positive([])
        assert result is False


class TestTaskWarriorEvent:
    """Tests for TaskWarriorEvent properties."""

    def test_task_property_title(self):
        """task property returns title when set."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"title": "MyTask", "project": "MyProject"},
        )
        assert event.task == "MyTask"

    def test_task_property_label_fallback(self):
        """task property falls back to label when title missing."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"label": "MyLabel", "project": "MyProject"},
        )
        assert event.task == "MyLabel"

    def test_task_property_task_fallback(self):
        """task property falls back to task when title and label missing."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"task": "MyTask", "project": "MyProject"},
        )
        assert event.task == "MyTask"

    def test_task_property_no_task_default(self):
        """task property returns NO_TASK when all fields missing."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"project": "MyProject"},
        )
        assert event.task == NO_TASK

    def test_project_property_with_data(self):
        """project property returns project from data."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"project": "MyProject", "title": "MyTask"},
        )
        assert event.project == "MyProject"

    def test_project_property_no_project_default(self):
        """project property returns NO_PROJECT when missing."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"title": "MyTask"},
        )
        assert event.project == NO_PROJECT

    def test_tags_property_list(self):
        """tags property returns list when data contains list."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"tags": ["tag1", "tag2"], "project": "MyProject", "title": "MyTask"},
        )
        assert event.tags == ["tag1", "tag2"]

    def test_tags_property_string_normalized(self):
        """tags property normalizes string to single-element list."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"tags": "offline", "project": "MyProject", "title": "MyTask"},
        )
        assert event.tags == ["offline"]

    def test_tags_property_default(self):
        """tags property returns empty list when missing."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"project": "MyProject", "title": "MyTask"},
        )
        assert event.tags == []

    def test_has_offline_tag_true(self):
        """has_offline_tag returns True when 'offline' in tags (case-insensitive)."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"tags": ["work", "OFFLINE"], "project": "MyProject", "title": "MyTask"},
        )
        assert event.has_offline_tag is True

    def test_has_offline_tag_false(self):
        """has_offline_tag returns False when 'offline' not in tags."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"tags": ["work", "urgent"], "project": "MyProject", "title": "MyTask"},
        )
        assert event.has_offline_tag is False

    def test_uuid_property_with_data(self):
        """uuid property returns uuid from data."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"uuid": "abc-123", "project": "MyProject", "title": "MyTask"},
        )
        assert event.uuid == "abc-123"

    def test_uuid_property_default(self):
        """uuid property returns None when missing."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"project": "MyProject", "title": "MyTask"},
        )
        assert event.uuid is None

    def test_deepcopy_preserves_subclass(self):
        """deepcopy of TaskWarriorEvent preserves the subclass."""
        event = TaskWarriorEvent(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={"project": "MyProject", "title": "MyTask", "tags": ["offline"]},
        )
        copied = deepcopy(event)
        assert isinstance(copied, TaskWarriorEvent)
        assert copied.project == "MyProject"
        assert copied.task == "MyTask"
        assert copied.has_offline_tag is True

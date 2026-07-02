"""
Unit tests for task matching and identification (tw_report.core.task_matching).

Tests verify task overlap detection, metadata extraction, offline-tag detection,
and offline category structure building.
"""

from datetime import datetime, timedelta, timezone

import pytest
from aw_core.models import Event

from tw_report.core.filtering import NO_PROJECT, NO_TASK
from tw_report.core.task_matching import (
    build_offline_category_structure,
    find_active_task,
    get_task_info,
    task_has_offline_tag,
)


class TestFindActiveTask:
    """Test task overlap detection."""

    @pytest.fixture
    def base_time(self):
        """Base time for event creation."""
        return datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def test_exact_overlap(self, base_time):
        """Task that exactly overlaps the event."""
        event = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"app": "vim"},
        )
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"task": "Code review"},
        )

        result = find_active_task(event, [task])
        assert result == task

    def test_task_contains_event(self, base_time):
        """Task that contains the entire event."""
        event = Event(
            timestamp=base_time + timedelta(minutes=15),
            duration=timedelta(minutes=30),
            data={"app": "vim"},
        )
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"task": "Code review"},
        )

        result = find_active_task(event, [task])
        assert result == task

    def test_event_contains_task(self, base_time):
        """Event that contains the entire task."""
        event = Event(
            timestamp=base_time,
            duration=timedelta(hours=2),
            data={"app": "vim"},
        )
        task = Event(
            timestamp=base_time + timedelta(minutes=30),
            duration=timedelta(minutes=30),
            data={"task": "Code review"},
        )

        result = find_active_task(event, [task])
        assert result == task

    def test_partial_overlap(self, base_time):
        """Task that partially overlaps the event."""
        event = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"app": "vim"},
        )
        task = Event(
            timestamp=base_time + timedelta(minutes=30),
            duration=timedelta(hours=1),
            data={"task": "Code review"},
        )

        result = find_active_task(event, [task])
        assert result == task

    def test_no_overlap(self, base_time):
        """Task that doesn't overlap the event."""
        event = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"app": "vim"},
        )
        task = Event(
            timestamp=base_time + timedelta(hours=2),
            duration=timedelta(hours=1),
            data={"task": "Code review"},
        )

        result = find_active_task(event, [task])
        assert result is None

    def test_multiple_tasks_returns_first(self, base_time):
        """With multiple overlapping tasks, returns the first one."""
        event = Event(
            timestamp=base_time,
            duration=timedelta(hours=2),
            data={"app": "vim"},
        )
        task1 = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"task": "Task 1"},
        )
        task2 = Event(
            timestamp=base_time + timedelta(minutes=30),
            duration=timedelta(hours=1),
            data={"task": "Task 2"},
        )

        result = find_active_task(event, [task1, task2])
        assert result == task1  # First in list

    def test_empty_task_list(self, base_time):
        """With no tasks, should return None."""
        event = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"app": "vim"},
        )

        result = find_active_task(event, [])
        assert result is None


class TestGetTaskInfo:
    """Test task metadata extraction."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def test_all_fields_present(self, base_time):
        """Extract when all fields are present (title takes priority)."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={
                "title": "Code review",
                "label": "Review",
                "task": "review-123",
                "project": "Platform",
            },
        )

        name, project = get_task_info(task)

        assert name == "Code review"
        assert project == "Platform"

    def test_fallback_to_label(self, base_time):
        """Fall back to label if title is missing."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={
                "label": "Review",
                "task": "review-123",
                "project": "Platform",
            },
        )

        name, project = get_task_info(task)

        assert name == "Review"

    def test_fallback_to_task(self, base_time):
        """Fall back to task if title and label are missing."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={
                "task": "review-123",
                "project": "Platform",
            },
        )

        name, project = get_task_info(task)

        assert name == "review-123"

    def test_no_task_name_defaults_to_no_task(self, base_time):
        """Use NO_TASK sentinel when no name fields present."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"project": "Platform"},
        )

        name, project = get_task_info(task)

        assert name == NO_TASK
        assert project == "Platform"

    def test_no_project_defaults_to_no_project(self, base_time):
        """Use NO_PROJECT sentinel when project is missing."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"title": "Code review"},
        )

        name, project = get_task_info(task)

        assert name == "Code review"
        assert project == NO_PROJECT


class TestTaskHasOfflineTag:
    """Test offline-tag detection."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def test_offline_tag_in_list(self, base_time):
        """Task with 'offline' in tags list."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"tags": ["offline", "work"]},
        )

        assert task_has_offline_tag(task) is True

    def test_offline_tag_as_string(self, base_time):
        """Task with 'offline' as single string tag."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"tags": "offline"},
        )

        assert task_has_offline_tag(task) is True

    def test_case_insensitive(self, base_time):
        """Offline tag detection should be case-insensitive."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"tags": ["OFFLINE", "WORK"]},
        )

        assert task_has_offline_tag(task) is True

    def test_no_offline_tag(self, base_time):
        """Task without offline tag."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"tags": ["work", "urgent"]},
        )

        assert task_has_offline_tag(task) is False

    def test_empty_tags(self, base_time):
        """Task with empty tags."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={"tags": []},
        )

        assert task_has_offline_tag(task) is False

    def test_missing_tags(self, base_time):
        """Task with no tags field."""
        task = Event(
            timestamp=base_time,
            duration=timedelta(hours=1),
            data={},
        )

        assert task_has_offline_tag(task) is False


class TestBuildOfflineCategoryStructure:
    """Test offline category structure building."""

    @pytest.fixture
    def duration(self):
        return timedelta(hours=2)

    def test_timeline_format_with_times(self, duration):
        """With start_time and end_time, returns timeline format."""
        start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

        result = build_offline_category_structure(duration, start_time=start, end_time=end)

        assert result["category"] == "Offline"
        assert result["duration"] == duration
        assert result["start"] == start
        assert result["end"] == end
        assert result["apps"] == []

    def test_hierarchical_format_without_times(self, duration):
        """Without start_time and end_time, returns hierarchical format."""
        result = build_offline_category_structure(duration)

        assert result["total_duration"] == duration
        assert result["apps"] == {}
        assert result["prod_score"] == 0.0

    def test_hierarchical_format_partial_times(self, duration):
        """With only start_time (not end_time), returns hierarchical format."""
        start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

        result = build_offline_category_structure(duration, start_time=start)

        assert result["total_duration"] == duration
        assert "category" not in result

    def test_zero_duration(self):
        """Should handle zero duration."""
        result = build_offline_category_structure(timedelta(0))

        assert result["total_duration"] == timedelta(0)
        assert result["prod_score"] == 0.0

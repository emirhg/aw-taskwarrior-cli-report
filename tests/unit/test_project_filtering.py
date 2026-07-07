"""
Tests for project-based filtering optimization.

Verifies that project filtering can skip window bucket queries when
only task-level information is needed, and that project filter values
can be resolved from task IDs or UUIDs.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import argparse
import json

import pytest
from aw_core.models import Event

from tw_report.core.project_filtering import (
    get_events_by_project,
    should_skip_window_bucket,
    _is_uuid_like,
    resolve_project_filter_value,
)


class TestGetEventsByProject:
    """Test project-based event filtering."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock ActivityWatchClient."""
        return Mock()

    @pytest.fixture
    def time_range(self):
        """Create a sample time range."""
        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
        return start, end

    @pytest.fixture
    def sample_events(self):
        """Create sample taskwarrior events with different projects."""
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        return [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={
                    "title": "Climb Project Task",
                    "project": "Climb > Expedition",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=2),
                data={
                    "title": "Work Task",
                    "project": "Work > Development",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=3),
                duration=timedelta(hours=1),
                data={
                    "title": "Another Climb Task",
                    "project": "Climb > Training",
                },
            ),
        ]

    def test_get_events_by_project_all(self, mock_client, time_range, sample_events):
        """Test fetching all events without project filter."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_project(
            mock_client, "aw-watcher-taskwarrior_host", start, end
        )

        assert len(result) == 3
        assert result == sample_events

    def test_get_events_by_project_filter(self, mock_client, time_range, sample_events):
        """Test filtering events by project name (substring match)."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_project(
            mock_client, "aw-watcher-taskwarrior_host", start, end, project="Climb"
        )

        assert len(result) == 2
        assert all("Climb" in e.data.get("project", "") for e in result)

    def test_get_events_by_project_case_insensitive(
        self, mock_client, time_range, sample_events
    ):
        """Test that project filtering is case-insensitive."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_project(
            mock_client, "aw-watcher-taskwarrior_host", start, end, project="climb"
        )

        assert len(result) == 2

    def test_get_events_by_project_no_matches(
        self, mock_client, time_range, sample_events
    ):
        """Test filtering with no matching projects."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_project(
            mock_client, "aw-watcher-taskwarrior_host", start, end, project="NonExistent"
        )

        assert result == []

    def test_get_events_by_project_empty_list(self, mock_client, time_range):
        """Test filtering on empty event list."""
        start, end = time_range
        mock_client.get_events.return_value = []

        result = get_events_by_project(
            mock_client, "aw-watcher-taskwarrior_host", start, end, project="Climb"
        )

        assert result == []


class TestIsUuidLike:
    """Test UUID format detection."""

    def test_valid_uuid(self):
        """Should recognize valid UUID format."""
        assert _is_uuid_like("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uuid_case_insensitive(self):
        """Should recognize UUID regardless of case."""
        assert (
            _is_uuid_like("550E8400-E29B-41D4-A716-446655440000") is True
        )

    def test_invalid_uuid_wrong_format(self):
        """Should reject strings with wrong UUID format."""
        assert _is_uuid_like("not-a-uuid") is False

    def test_invalid_uuid_partial(self):
        """Should reject partial/truncated UUID."""
        assert _is_uuid_like("550e8400-e29b-41d4-a716") is False

    def test_invalid_uuid_extra_chars(self):
        """Should reject UUID with extra characters."""
        assert (
            _is_uuid_like("550e8400-e29b-41d4-a716-446655440000-extra") is False
        )

    def test_numeric_string(self):
        """Should reject plain numeric strings as UUIDs."""
        assert _is_uuid_like("12345") is False


class TestResolveProjectFilterValue:
    """Test project filter value resolution."""

    def test_resolve_integer_task_id(self):
        """Should resolve integer task ID to project name."""
        task_json = [{"uuid": "test-uuid", "project": "Climb > Training"}]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_project_filter_value("48")

            assert error is None
            assert resolved == "Climb > Training"

    def test_resolve_uuid_to_project(self):
        """Should resolve UUID to project name."""
        task_json = [
            {"uuid": "550e8400-e29b-41d4-a716-446655440000", "project": "Work > Dev"}
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_project_filter_value(
                "550e8400-e29b-41d4-a716-446655440000"
            )

            assert error is None
            assert resolved == "Work > Dev"

    def test_plain_pattern_unchanged(self):
        """Should return plain string patterns unchanged."""
        resolved, error = resolve_project_filter_value("Climb")

        assert error is None
        assert resolved == "Climb"

    def test_invalid_task_id_error(self):
        """Should return error tuple when task ID not found."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "task")

            resolved, error = resolve_project_filter_value("999")

            assert resolved is None
            assert "has no project assigned" in error

    def test_empty_project_field_error(self):
        """Should return error when task has no project assigned."""
        task_json = [{"uuid": "test-uuid", "project": ""}]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_project_filter_value("48")

            assert resolved is None
            assert "has no project assigned" in error

    def test_missing_project_field_error(self):
        """Should return error when task has no project field."""
        task_json = [{"uuid": "test-uuid"}]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_project_filter_value("48")

            assert resolved is None
            assert "has no project assigned" in error

    def test_multiple_patterns_mixed(self):
        """Should handle mix of IDs and patterns (resolve each independently)."""
        # This is tested in CLI integration, not here
        # (main.py loops through each value in args.project)
        pass


class TestShouldSkipWindowBucket:
    """Test window bucket skip optimization logic."""

    def test_skip_with_project_filter_timesheet_detail_1(self):
        """Should skip window bucket: project filter + timesheet + detail 1."""
        args = argparse.Namespace(
            timesheet=True,
            project=["Climb"],
            task=None,
            app=None,
            search=None,
            detail_level=1,
        )

        assert should_skip_window_bucket(args, detail_level=1) is True

    def test_skip_with_project_filter_timesheet_detail_2(self):
        """Should skip window bucket: project filter + timesheet + detail 2."""
        args = argparse.Namespace(
            timesheet=True,
            project=["Climb"],
            task=None,
            app=None,
            search=None,
            detail_level=2,
        )

        assert should_skip_window_bucket(args, detail_level=2) is True

    def test_keep_with_app_filter(self):
        """Should NOT skip window bucket: app filter requires window events."""
        args = argparse.Namespace(
            timesheet=True,
            project=["Climb"],
            task=None,
            app=["Firefox"],
            search=None,
        )

        assert should_skip_window_bucket(args, detail_level=1) is False

    def test_keep_with_high_detail_level(self):
        """Should NOT skip window bucket: detail 3+ requires app/category data."""
        args = argparse.Namespace(
            timesheet=True,
            project=["Climb"],
            task=None,
            app=None,
            search=None,
        )

        assert should_skip_window_bucket(args, detail_level=3) is False

    def test_keep_without_timesheet(self):
        """Should NOT skip window bucket: hierarchical report needs window data."""
        args = argparse.Namespace(
            timesheet=False,
            project=["Climb"],
            task=None,
            app=None,
            search=None,
        )

        assert should_skip_window_bucket(args, detail_level=1) is False

    def test_skip_with_task_filter_timesheet(self):
        """Should skip window bucket: task filter + timesheet."""
        args = argparse.Namespace(
            timesheet=True,
            project=None,
            task=["Code review"],
            app=None,
            search=None,
        )

        assert should_skip_window_bucket(args, detail_level=1) is True

    def test_skip_with_search_term_timesheet(self):
        """Should skip window bucket: search term + timesheet."""
        args = argparse.Namespace(
            timesheet=True,
            project=None,
            task=None,
            app=None,
            search="Climbing",
        )

        assert should_skip_window_bucket(args, detail_level=1) is True

    def test_keep_with_no_filters(self):
        """Should NOT skip window bucket: no filters, need all data."""
        args = argparse.Namespace(
            timesheet=True,
            project=None,
            task=None,
            app=None,
            search=None,
        )

        assert should_skip_window_bucket(args, detail_level=1) is False

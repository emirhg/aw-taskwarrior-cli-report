"""
Unit tests for task UUID filtering (tw_report.core.task_uuid_filtering).

Tests verify UUID lookup from TaskWarrior and event filtering by UUID,
with proper error handling and graceful degradation.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import json
import subprocess

import pytest
from aw_core.models import Event

from tw_report.core.task_uuid_filtering import (
    get_task_uuid,
    get_events_by_uuid,
    get_task_description,
)


class TestGetTaskUuid:
    """Test TaskWarrior task UUID lookup."""

    def test_valid_task_uuid_lookup(self):
        """Should extract UUID from valid taskwarrior export output."""
        task_json = [
            {
                "uuid": "a1b2c3d4-e5f6-47a8-b9c0-d1e2f3a4b5c6",
                "description": "Write code review",
                "project": "myproject",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            uuid = get_task_uuid(48)

            assert uuid == "a1b2c3d4-e5f6-47a8-b9c0-d1e2f3a4b5c6"
            mock_run.assert_called_once_with(
                ["task", "48", "export"],
                capture_output=True,
                text=True,
                check=True,
            )

    def test_invalid_task_id(self):
        """Should return None when task ID doesn't exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "task")

            uuid = get_task_uuid(999)

            assert uuid is None

    def test_empty_export_result(self):
        """Should return None when export returns empty list."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout="[]",
                returncode=0,
            )

            uuid = get_task_uuid(48)

            assert uuid is None

    def test_malformed_json_output(self):
        """Should return None when taskwarrior returns invalid JSON."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout="invalid json",
                returncode=0,
            )

            uuid = get_task_uuid(48)

            assert uuid is None

    def test_missing_uuid_field(self):
        """Should return None when export result has no uuid field."""
        task_json = [
            {
                "description": "Task without UUID",
                "project": "myproject",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            uuid = get_task_uuid(48)

            assert uuid is None

    def test_multiple_tasks_uses_first(self):
        """Should use first task if export returns multiple (shouldn't happen)."""
        task_json = [
            {
                "uuid": "first-uuid-1234",
                "description": "First task",
            },
            {
                "uuid": "second-uuid-5678",
                "description": "Second task",
            },
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            uuid = get_task_uuid(48)

            assert uuid == "first-uuid-1234"

    def test_task_id_type_conversion(self):
        """Should convert int task ID to string for subprocess call."""
        task_json = [{"uuid": "test-uuid"}]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            get_task_uuid(123)

            # Verify task ID was converted to string
            call_args = mock_run.call_args[0][0]
            assert call_args[1] == "123"


class TestGetEventsByUuid:
    """Test event filtering by UUID."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock ActivityWatchClient."""
        return Mock()

    @pytest.fixture
    def time_range(self):
        """Create a sample time range for testing."""
        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
        return start, end

    @pytest.fixture
    def sample_events(self):
        """Create sample taskwarrior events with UUIDs."""
        base_time = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        return [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={
                    "uuid": "uuid-task-1",
                    "title": "Code review",
                    "project": "myproject",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=2),
                data={
                    "uuid": "uuid-task-2",
                    "title": "Write code",
                    "project": "myproject",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=3),
                duration=timedelta(hours=1),
                data={
                    "uuid": "uuid-task-1",
                    "title": "Code review",
                    "project": "myproject",
                },
            ),
        ]

    def test_filter_by_matching_uuid(self, mock_client, time_range, sample_events):
        """Should filter events to only those matching the UUID."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, "uuid-task-1"
        )

        assert len(result) == 2
        assert all(e.data.get("uuid") == "uuid-task-1" for e in result)

    def test_filter_by_uuid_no_matches(self, mock_client, time_range, sample_events):
        """Should return empty list when UUID doesn't match any events."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_uuid(
            mock_client,
            "aw-watcher-taskwarrior_host",
            start,
            end,
            "nonexistent-uuid",
        )

        assert result == []

    def test_filter_by_uuid_none_returns_all(self, mock_client, time_range, sample_events):
        """Should return all events when UUID is None."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, None
        )

        assert len(result) == 3
        assert result == sample_events

    def test_filter_empty_event_list(self, mock_client, time_range):
        """Should handle empty event list gracefully."""
        start, end = time_range
        mock_client.get_events.return_value = []

        result = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, "some-uuid"
        )

        assert result == []

    def test_filter_events_without_uuid_field(self, mock_client, time_range):
        """Should handle events missing uuid field (shouldn't match)."""
        start, end = time_range
        base_time = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={"title": "Task without UUID"},
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=1),
                data={
                    "uuid": "has-uuid",
                    "title": "Task with UUID",
                },
            ),
        ]
        mock_client.get_events.return_value = events

        result = get_events_by_uuid(
            mock_client,
            "aw-watcher-taskwarrior_host",
            start,
            end,
            "has-uuid",
        )

        assert len(result) == 1
        assert result[0].data.get("uuid") == "has-uuid"

    def test_filter_by_uuid_case_sensitive(self, mock_client, time_range):
        """UUID filtering should be case-sensitive."""
        start, end = time_range
        base_time = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={"uuid": "UUID-TASK-1", "title": "Task"},
            ),
        ]
        mock_client.get_events.return_value = events

        result = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, "uuid-task-1"
        )

        # Should not match due to case difference
        assert result == []

    def test_filter_respects_time_range(self, mock_client):
        """Should only filter events that were fetched (within time range)."""
        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)

        base_time = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={"uuid": "task-1", "title": "In range"},
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=1),
                data={"uuid": "task-1", "title": "Also in range"},
            ),
        ]
        mock_client.get_events.return_value = events

        result = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, "task-1"
        )

        # Filtering happens on returned events (already time-range filtered by AW)
        assert len(result) == 2


class TestGetTaskDescription:
    """Test task description (name) field extraction."""

    def test_get_task_description_by_id(self):
        """Test getting description from a valid task ID."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "Documentar una presentación",
                "project": "Antikythera",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            description = get_task_description(48)

            assert description == "Documentar una presentación"

    def test_get_task_description_by_uuid(self):
        """Test getting description from a task UUID."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "Code review for PR #123",
                "project": "Work",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            description = get_task_description("550e8400-e29b-41d4-a716-446655440000")

            assert description == "Code review for PR #123"

    def test_get_task_description_invalid_id(self):
        """Test getting description from invalid task ID."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "task")

            description = get_task_description(999)

            assert description is None

    def test_get_task_description_missing_field(self):
        """Test when task has no description field."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "project": "Work",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            description = get_task_description(48)

            assert description is None


class TestGetTaskProject:
    """Test task project field extraction."""

    def test_get_task_project_by_id(self):
        """Test getting project from a valid task ID."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "My task",
                "project": "Climbing > Training",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            from tw_report.core.task_uuid_filtering import get_task_project

            project = get_task_project(48)

            assert project == "Climbing > Training"

    def test_get_task_project_by_uuid(self):
        """Test getting project from a task UUID."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "My task",
                "project": "Web > Development",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            from tw_report.core.task_uuid_filtering import get_task_project

            project = get_task_project("550e8400-e29b-41d4-a716-446655440000")

            assert project == "Web > Development"

    def test_get_task_project_invalid_id(self):
        """Test getting project from invalid task ID."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "task")

            from tw_report.core.task_uuid_filtering import get_task_project

            project = get_task_project(999)

            assert project is None

    def test_get_task_project_empty_project_field(self):
        """Test when task has empty project field."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "My task",
                "project": "",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            from tw_report.core.task_uuid_filtering import get_task_project

            project = get_task_project(48)

            assert project == ""

    def test_get_task_project_missing_project_field(self):
        """Test when task has no project field."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "My task",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            from tw_report.core.task_uuid_filtering import get_task_project

            project = get_task_project(48)

            assert project is None


class TestTaskUuidFilteringIntegration:
    """Integration tests for UUID filtering in the context of main flow."""

    def test_get_events_by_uuid_with_real_event_structure(self):
        """Test filtering with realistic ActivityWatch event structure."""
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        task_uuid = "550e8400-e29b-41d4-a716-446655440000"

        events = [
            Event(
                timestamp=base_time,
                duration=timedelta(minutes=30),
                data={
                    "uuid": task_uuid,
                    "title": "Code review PR #123",
                    "project": "web-app",
                    "tags": ["work"],
                },
            ),
            Event(
                timestamp=base_time + timedelta(minutes=30),
                duration=timedelta(minutes=20),
                data={
                    "uuid": "different-uuid",
                    "title": "Standup meeting",
                    "project": "web-app",
                    "tags": ["meeting"],
                },
            ),
            Event(
                timestamp=base_time + timedelta(minutes=50),
                duration=timedelta(minutes=40),
                data={
                    "uuid": task_uuid,
                    "title": "Code review PR #123",
                    "project": "web-app",
                    "tags": ["work"],
                },
            ),
        ]

        mock_client = Mock()
        mock_client.get_events.return_value = events

        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)

        result = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, task_uuid
        )

        # Should have only the two events matching task_uuid
        assert len(result) == 2
        assert all(e.data.get("uuid") == task_uuid for e in result)
        # Total duration should be 70 minutes (30 + 40)
        total_duration = sum((e.duration for e in result), timedelta())
        assert total_duration == timedelta(minutes=70)

    def test_uuid_lookup_pipeline(self):
        """Test the full pipeline: task ID -> UUID -> event filtering."""
        task_id = 48
        task_uuid = "550e8400-e29b-41d4-a716-446655440000"

        # Mock taskwarrior export
        task_json = [{"uuid": task_uuid, "description": "My task"}]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=json.dumps(task_json), returncode=0)
            result_uuid = get_task_uuid(task_id)

        assert result_uuid == task_uuid

        # Now mock ActivityWatch filtering
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={"uuid": task_uuid, "title": "My task"},
            ),
        ]
        mock_client = Mock()
        mock_client.get_events.return_value = events

        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)

        filtered = get_events_by_uuid(
            mock_client, "aw-watcher-taskwarrior_host", start, end, result_uuid
        )

        assert len(filtered) == 1
        assert filtered[0].data.get("uuid") == task_uuid

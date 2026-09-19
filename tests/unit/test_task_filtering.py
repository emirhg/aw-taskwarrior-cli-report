"""
Tests for task-based filtering and auto-detection.

Verifies that task filtering can skip window bucket queries when only
task-level information is needed, and that task filter values can be
resolved from task IDs or UUIDs (like --project).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import argparse
import json
import subprocess

import pytest
from aw_core.models import Event

from tw_report.core.task_filtering import (
    get_events_by_task,
    get_events_by_tasks,
    resolve_task_filter_value,
)


class TestGetEventsByTask:
    """Test task-based event filtering."""

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
        """Create sample taskwarrior events with different task names."""
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        return [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={
                    "task": "Documentar presentación",
                    "project": "Antikythera",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=2),
                data={
                    "task": "Code review",
                    "project": "Work",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=3),
                duration=timedelta(hours=1),
                data={
                    "task": "Documentar proceso",
                    "project": "Antikythera",
                },
            ),
        ]

    def test_get_events_by_task_all(self, mock_client, time_range, sample_events):
        """Test fetching all events without task filter."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_task(
            mock_client, "aw-watcher-taskwarrior_host", start, end
        )

        assert len(result) == 3
        assert result == sample_events

    def test_get_events_by_task_filter(self, mock_client, time_range, sample_events):
        """Test filtering events by task name (substring match)."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_task(
            mock_client, "aw-watcher-taskwarrior_host", start, end, task="Documentar"
        )

        assert len(result) == 2
        assert all("Documentar" in e.data.get("task", "") for e in result)

    def test_get_events_by_task_case_insensitive(
        self, mock_client, time_range, sample_events
    ):
        """Test that task filtering is case-insensitive."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_task(
            mock_client, "aw-watcher-taskwarrior_host", start, end, task="documentar"
        )

        assert len(result) == 2

    def test_get_events_by_task_no_matches(
        self, mock_client, time_range, sample_events
    ):
        """Test filtering with no matching tasks."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_task(
            mock_client, "aw-watcher-taskwarrior_host", start, end, task="Nonexistent"
        )

        assert result == []

    def test_get_events_by_task_empty_list(self, mock_client, time_range):
        """Test filtering on empty event list."""
        start, end = time_range
        mock_client.get_events.return_value = []

        result = get_events_by_task(
            mock_client, "aw-watcher-taskwarrior_host", start, end, task="Documentar"
        )

        assert result == []


class TestGetEventsByTasks:
    """Test multi-task-based event filtering (PHASE 14)."""

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
        """Create sample taskwarrior events with different task names."""
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        return [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={
                    "task": "Documentar presentación",
                    "project": "Antikythera",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=2),
                data={
                    "task": "Code review",
                    "project": "Work",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=3),
                duration=timedelta(hours=1),
                data={
                    "task": "Documentar proceso",
                    "project": "Antikythera",
                },
            ),
        ]

    def test_get_events_by_tasks_all(self, mock_client, time_range, sample_events):
        """Test fetching all events without task filter."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_tasks(
            mock_client, "aw-watcher-taskwarrior_host", start, end
        )

        assert len(result) == 3
        assert result == sample_events

    def test_get_events_by_tasks_single_pattern(self, mock_client, time_range, sample_events):
        """Test filtering by single task pattern."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_tasks(
            mock_client, "aw-watcher-taskwarrior_host", start, end, tasks=["Documentar"]
        )

        assert len(result) == 2
        assert all("Documentar" in e.data.get("task", "") for e in result)

    def test_get_events_by_tasks_multiple_patterns_or_match(self, mock_client, time_range, sample_events):
        """Test filtering by multiple task patterns (OR match)."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_tasks(
            mock_client, "aw-watcher-taskwarrior_host", start, end,
            tasks=["Documentar", "Code review"]
        )

        assert len(result) == 3  # All events match one of the patterns

    def test_get_events_by_tasks_case_insensitive(self, mock_client, time_range, sample_events):
        """Test that task filtering is case-insensitive."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_tasks(
            mock_client, "aw-watcher-taskwarrior_host", start, end,
            tasks=["documentar"]
        )

        assert len(result) == 2

    def test_get_events_by_tasks_no_matches(self, mock_client, time_range, sample_events):
        """Test filtering with no matching tasks."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events_by_tasks(
            mock_client, "aw-watcher-taskwarrior_host", start, end,
            tasks=["Nonexistent"]
        )

        assert result == []

    def test_get_events_by_tasks_empty_list(self, mock_client, time_range):
        """Test filtering on empty event list."""
        start, end = time_range
        mock_client.get_events.return_value = []

        result = get_events_by_tasks(
            mock_client, "aw-watcher-taskwarrior_host", start, end,
            tasks=["Documentar", "Code review"]
        )

        assert result == []


class TestResolveTaskFilterValue:
    """Test task filter value resolution."""

    def test_resolve_integer_task_id(self):
        """Should resolve integer task ID to task description."""
        task_json = [
            {
                "uuid": "test-uuid",
                "description": "Documentar presentación",
                "project": "Antikythera",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_task_filter_value("48")

            assert error is None
            assert resolved == "Documentar presentación"

    def test_resolve_uuid_to_description(self):
        """Should resolve UUID to task description."""
        task_json = [
            {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "description": "Code review PR #456",
                "project": "Work",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_task_filter_value(
                "550e8400-e29b-41d4-a716-446655440000"
            )

            assert error is None
            assert resolved == "Code review PR #456"

    def test_plain_pattern_unchanged(self):
        """Should return plain string patterns unchanged."""
        resolved, error = resolve_task_filter_value("Documentar")

        assert error is None
        assert resolved == "Documentar"

    def test_invalid_task_id_error(self):
        """Should return error when task ID not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "task")

            resolved, error = resolve_task_filter_value("999")

            assert resolved is None
            assert "has no description" in error

    def test_missing_description_field_error(self):
        """Should return error when task has no description field."""
        task_json = [
            {
                "uuid": "test-uuid",
                "project": "Work",
            }
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=json.dumps(task_json),
                returncode=0,
            )

            resolved, error = resolve_task_filter_value("48")

            assert resolved is None
            assert "has no description" in error

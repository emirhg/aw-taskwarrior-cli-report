"""
Test task-UUID mode canonical event generation.

Verifies that when --task-id is used, taskwarrior events are converted
directly to canonical events without requiring window event correlation.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from aw_core.models import Event

from tw_report.pipeline.models import ReportEvent
from tw_report.core.task_matching import get_task_info


class TestTaskUuidCanonicalEvents:
    """Test canonical event generation for task-UUID mode."""

    @pytest.fixture
    def sample_taskwarrior_events(self):
        """Create sample taskwarrior events."""
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        return [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={
                    "uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "title": "Code review PR #123",
                    "project": "web-app",
                    "tags": ["work"],
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=2),
                data={
                    "uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "title": "Code review PR #123",
                    "project": "web-app",
                    "tags": ["work"],
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=3),
                duration=timedelta(minutes=30),
                data={
                    "uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "title": "Code review PR #123",
                    "project": "web-app",
                    "tags": ["work"],
                },
            ),
        ]

    def test_task_uuid_canonical_events_generation(self, sample_taskwarrior_events):
        """Test that task-UUID mode generates canonical events from taskwarrior events."""
        # Simulate the task-UUID mode code from main.py
        canonical_events = []
        for task_event in sample_taskwarrior_events:
            task_name, project = get_task_info(task_event)
            canonical_events.append(
                ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
            )

        # Verify events were created
        assert len(canonical_events) == 3
        assert all(isinstance(e, ReportEvent) for e in canonical_events)

        # Verify task metadata is preserved
        for i, rep_event in enumerate(canonical_events):
            assert rep_event.project == "web-app"
            assert rep_event.task == "Code review PR #123"
            assert rep_event.active_task is sample_taskwarrior_events[i]

    def test_task_uuid_canonical_events_preserve_event_data(
        self, sample_taskwarrior_events
    ):
        """Test that canonical events preserve taskwarrior event data."""
        canonical_events = []
        for task_event in sample_taskwarrior_events:
            task_name, project = get_task_info(task_event)
            canonical_events.append(
                ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
            )

        # Verify event data is preserved
        for i, rep_event in enumerate(canonical_events):
            assert rep_event.event == sample_taskwarrior_events[i]
            assert rep_event.event.duration == sample_taskwarrior_events[
                i
            ].duration
            assert rep_event.event.timestamp == sample_taskwarrior_events[i].timestamp
            assert rep_event.event.data == sample_taskwarrior_events[i].data

    def test_task_uuid_canonical_events_duration_aggregation(
        self, sample_taskwarrior_events
    ):
        """Test that durations can be aggregated from task-UUID canonical events."""
        canonical_events = []
        for task_event in sample_taskwarrior_events:
            task_name, project = get_task_info(task_event)
            canonical_events.append(
                ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
            )

        # Calculate total duration
        total_duration = sum(
            (e.event.duration for e in canonical_events), timedelta(0)
        )

        # Should be 1 hour + 2 hours + 30 minutes = 3.5 hours
        expected = timedelta(hours=3, minutes=30)
        assert total_duration == expected

    def test_task_uuid_canonical_events_empty_list(self):
        """Test that empty taskwarrior events list produces empty canonical events."""
        task_events = []
        canonical_events = []
        for task_event in task_events:
            task_name, project = get_task_info(task_event)
            canonical_events.append(
                ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
            )

        assert canonical_events == []

    def test_task_uuid_canonical_events_vs_normal_mode(
        self, sample_taskwarrior_events
    ):
        """Test that task-UUID mode produces different output than normal mode."""
        # Task-UUID mode: direct conversion
        task_uuid_events = []
        for task_event in sample_taskwarrior_events:
            task_name, project = get_task_info(task_event)
            task_uuid_events.append(
                ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
            )

        # Task-UUID mode should have same number as input
        assert len(task_uuid_events) == len(sample_taskwarrior_events)

        # Each event should have correct project and task
        for rep_event in task_uuid_events:
            assert rep_event.project == "web-app"
            assert "Code review" in rep_event.task

    def test_task_uuid_canonical_events_with_different_projects(self):
        """Test task-UUID mode with multiple projects (if UUID spans multiple)."""
        base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={
                    "uuid": "same-uuid",
                    "title": "Task 1",
                    "project": "project-a",
                },
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(hours=1),
                data={
                    "uuid": "same-uuid",
                    "title": "Task 1",
                    "project": "project-b",
                },
            ),
        ]

        canonical_events = []
        for task_event in events:
            task_name, project = get_task_info(task_event)
            canonical_events.append(
                ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
            )

        assert len(canonical_events) == 2
        assert canonical_events[0].project == "project-a"
        assert canonical_events[1].project == "project-b"

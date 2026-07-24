"""Tests for untracked gap generation (untracked time without window events)."""

import pytest
from datetime import datetime, timedelta, timezone
from aw_core.models import Event

from tw_report.pipeline.generation import generate_untracked_gap_events, MIN_EVENT_DURATION
from tw_report.core.filtering import NO_PROJECT, NO_TASK


UTC = timezone.utc


class TestUntrackedGapGeneration:
    """Test synthetic NO_PROJECT event generation for gaps in task coverage."""

    def test_entirely_uncovered_not_afk_period(self):
        """A not-afk period with no overlapping tasks generates one synthetic event."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=2),
            data={},
        )
        # No task events

        result = generate_untracked_gap_events([not_afk_event], None)

        assert len(result) == 1
        assert result[0].project == NO_PROJECT
        assert result[0].task == NO_TASK
        assert result[0].active_task is None
        assert result[0].event.timestamp == datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
        assert result[0].event.duration == timedelta(hours=2)

    def test_entirely_covered_period_no_gaps(self):
        """A not-afk period fully covered by a task generates no synthetic events."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=2),
            data={},
        )
        # Task covers entire period
        task_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=2),
            data={"project": "Work", "task": "Meeting"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task_event])

        assert len(result) == 0

    def test_gap_before_task(self):
        """Gap before a task generates one synthetic event."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=2),  # 10:00-12:00
            data={},
        )
        # Task starts at 11:00
        task_event = Event(
            timestamp=datetime(2026, 7, 23, 11, 0, tzinfo=UTC),
            duration=timedelta(hours=1),  # 11:00-12:00
            data={"project": "Work", "task": "Task1"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task_event])

        assert len(result) == 1
        assert result[0].event.timestamp == datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
        assert result[0].event.duration == timedelta(hours=1)  # 10:00-11:00

    def test_gap_after_task(self):
        """Gap after a task generates one synthetic event."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=2),  # 10:00-12:00
            data={},
        )
        # Task ends at 11:00
        task_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=1),  # 10:00-11:00
            data={"project": "Work", "task": "Task1"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task_event])

        assert len(result) == 1
        assert result[0].event.timestamp == datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
        assert result[0].event.duration == timedelta(hours=1)  # 11:00-12:00

    def test_gap_between_tasks(self):
        """Gap between two tasks generates one synthetic event."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=3),  # 10:00-13:00
            data={},
        )
        task1 = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=1),  # 10:00-11:00
            data={"project": "Work", "task": "Task1"},
        )
        task2 = Event(
            timestamp=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
            duration=timedelta(hours=1),  # 12:00-13:00
            data={"project": "Work", "task": "Task2"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task1, task2])

        assert len(result) == 1
        assert result[0].event.timestamp == datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
        assert result[0].event.duration == timedelta(hours=1)  # 11:00-12:00

    def test_multiple_gaps(self):
        """Multiple gaps generate multiple synthetic events."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=4),  # 10:00-14:00
            data={},
        )
        task1 = Event(
            timestamp=datetime(2026, 7, 23, 10, 30, tzinfo=UTC),
            duration=timedelta(minutes=30),  # 10:30-11:00
            data={"project": "Work", "task": "Task1"},
        )
        task2 = Event(
            timestamp=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
            duration=timedelta(hours=1),  # 12:00-13:00
            data={"project": "Work", "task": "Task2"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task1, task2])

        assert len(result) == 3
        # Gap before task1
        assert result[0].event.timestamp == datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
        assert result[0].event.duration == timedelta(minutes=30)
        # Gap between tasks
        assert result[1].event.timestamp == datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
        assert result[1].event.duration == timedelta(hours=1)
        # Gap after task2
        assert result[2].event.timestamp == datetime(2026, 7, 23, 13, 0, tzinfo=UTC)
        assert result[2].event.duration == timedelta(hours=1)

    def test_short_gaps_filtered_out(self):
        """Gaps shorter than MIN_EVENT_DURATION are excluded."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=1),
            data={},
        )
        # Task covers all but 30 seconds (gap too short)
        task_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, 30, tzinfo=UTC),
            duration=timedelta(minutes=59, seconds=30),
            data={"project": "Work", "task": "Task1"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task_event])

        # Should be filtered out (gap is 30 seconds, MIN_EVENT_DURATION is 60)
        assert len(result) == 0

    def test_multiple_not_afk_periods(self):
        """Multiple not-afk periods each generate gaps independently."""
        not_afk1 = Event(
            timestamp=datetime(2026, 7, 23, 9, 0, tzinfo=UTC),
            duration=timedelta(hours=1),
            data={},
        )
        not_afk2 = Event(
            timestamp=datetime(2026, 7, 23, 14, 0, tzinfo=UTC),
            duration=timedelta(hours=1),
            data={},
        )
        # Task only in second period
        task_event = Event(
            timestamp=datetime(2026, 7, 23, 14, 30, tzinfo=UTC),
            duration=timedelta(minutes=30),
            data={"project": "Work", "task": "Task1"},
        )

        result = generate_untracked_gap_events([not_afk1, not_afk2], [task_event])

        # First period entirely uncovered, second has gap before task
        assert len(result) == 2
        assert result[0].event.timestamp == datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
        assert result[0].event.duration == timedelta(hours=1)
        assert result[1].event.timestamp == datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
        assert result[1].event.duration == timedelta(minutes=30)

    def test_overlapping_tasks(self):
        """Overlapping tasks are merged before gap detection."""
        not_afk_event = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=3),  # 10:00-13:00
            data={},
        )
        # Two overlapping tasks
        task1 = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=1, minutes=30),  # 10:00-11:30
            data={"project": "Work", "task": "Task1"},
        )
        task2 = Event(
            timestamp=datetime(2026, 7, 23, 11, 0, tzinfo=UTC),
            duration=timedelta(hours=1, minutes=30),  # 11:00-12:30
            data={"project": "Work", "task": "Task2"},
        )

        result = generate_untracked_gap_events([not_afk_event], [task1, task2])

        # One gap after merged coverage (10:00-12:30 covered, 12:30-13:00 uncovered)
        assert len(result) == 1
        assert result[0].event.timestamp == datetime(2026, 7, 23, 12, 30, tzinfo=UTC)
        assert result[0].event.duration == timedelta(minutes=30)

    def test_empty_inputs(self):
        """Empty inputs produce appropriate results."""
        assert generate_untracked_gap_events([], None) == []
        assert generate_untracked_gap_events([], []) == []

        not_afk = Event(
            timestamp=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
            duration=timedelta(hours=1),
            data={},
        )
        # No task events means entire not-afk period is uncovered
        result = generate_untracked_gap_events([not_afk], None)
        assert len(result) == 1
        assert result[0].event.duration == timedelta(hours=1)

        # Empty task list also means entire period is uncovered
        result = generate_untracked_gap_events([not_afk], [])
        assert len(result) == 1
        assert result[0].event.duration == timedelta(hours=1)

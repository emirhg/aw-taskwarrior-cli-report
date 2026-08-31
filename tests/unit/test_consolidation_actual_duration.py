"""Unit tests for consolidation actual_duration calculation.

Tests that consolidate_sessions() correctly sums actual_duration values
from merged slots, not using wall-clock durations.
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.pipeline.consolidation import consolidate_sessions


@pytest.fixture
def tz():
    """UTC-6 timezone for test slots."""
    return timezone(timedelta(hours=-6))


@pytest.fixture
def base_time(tz):
    """2026-08-30 11:00 UTC-6"""
    return datetime(2026, 8, 30, 11, 0, tzinfo=tz)


def make_slot(start, duration, actual_duration=None, project="P1", task="T1", tz_info=None):
    """Helper to create a slot dict."""
    if tz_info is None:
        tz_info = timezone(timedelta(hours=-6))

    return {
        "start": start,
        "end": start + duration,
        "duration": duration,
        "actual_duration": actual_duration if actual_duration is not None else duration,
        "project": project,
        "task": task,
        "type": "regular",
        "tags": [],
    }


class TestConsolidationActualDuration:
    """Test that consolidation correctly sums actual_duration values."""

    def test_single_slot_unchanged(self, base_time):
        """Single slot should remain unchanged."""
        slots = [
            make_slot(
                base_time,
                timedelta(hours=1),
                actual_duration=timedelta(minutes=50),  # 10 min AFK
                task="Task1"
            )
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        assert consolidated[0]["actual_duration"] == timedelta(minutes=50)
        assert consolidated[0]["duration"] == timedelta(hours=1)

    def test_two_slots_same_task_sum_actual_duration(self, base_time):
        """Two slots of same task should sum actual_duration."""
        slots = [
            make_slot(
                base_time,
                timedelta(hours=1),
                actual_duration=timedelta(minutes=50),  # 10 min AFK
                task="Task1"
            ),
            make_slot(
                base_time + timedelta(hours=1, minutes=30),
                timedelta(hours=1),
                actual_duration=timedelta(minutes=55),  # 5 min AFK
                task="Task1"
            ),
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        # actual_duration should be sum: 50m + 55m = 105m = 1h45m
        assert consolidated[0]["actual_duration"] == timedelta(minutes=105)
        # duration should be wall-clock: first start to last end (1.5h + 1h = 2.5h)
        assert consolidated[0]["duration"] == timedelta(hours=2, minutes=30)

    def test_three_slots_same_task_with_gaps(self, base_time):
        """Three slots with gaps should merge correctly."""
        # Three 1-hour slots with gaps between them
        slots = [
            make_slot(
                base_time,
                timedelta(hours=1),
                actual_duration=timedelta(minutes=50),
                task="Task1"
            ),
            # 30-minute gap
            make_slot(
                base_time + timedelta(hours=1, minutes=30),
                timedelta(hours=1),
                actual_duration=timedelta(minutes=55),
                task="Task1"
            ),
            # 30-minute gap
            make_slot(
                base_time + timedelta(hours=3),
                timedelta(hours=1),
                actual_duration=timedelta(minutes=48),
                task="Task1"
            ),
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        # actual_duration should be sum: 50 + 55 + 48 = 153 minutes
        assert consolidated[0]["actual_duration"] == timedelta(minutes=153)
        # wall-clock duration from first start to last end: 4 hours
        assert consolidated[0]["duration"] == timedelta(hours=4)

    def test_interruption_creates_separate_groups(self, base_time):
        """Task interrupted by different task should create separate groups."""
        slots = [
            make_slot(base_time, timedelta(hours=1), actual_duration=timedelta(minutes=50), task="Task1"),
            make_slot(base_time + timedelta(hours=1, minutes=30), timedelta(hours=1), actual_duration=timedelta(minutes=45), task="Task2"),
            make_slot(base_time + timedelta(hours=2, minutes=30), timedelta(hours=1), actual_duration=timedelta(minutes=55), task="Task1"),
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 3
        # Task1 group 1
        assert consolidated[0]["task"] == "Task1"
        assert consolidated[0]["actual_duration"] == timedelta(minutes=50)
        # Task2
        assert consolidated[1]["task"] == "Task2"
        assert consolidated[1]["actual_duration"] == timedelta(minutes=45)
        # Task1 group 2 (separate because interrupted)
        assert consolidated[2]["task"] == "Task1"
        assert consolidated[2]["actual_duration"] == timedelta(minutes=55)

    def test_actual_duration_all_afk(self, base_time):
        """Slots with mostly AFK time should have low actual_duration."""
        slots = [
            make_slot(
                base_time,
                timedelta(hours=1),
                actual_duration=timedelta(minutes=5),  # 55 min AFK
                task="Task1"
            ),
            make_slot(
                base_time + timedelta(hours=1, minutes=30),
                timedelta(hours=1),
                actual_duration=timedelta(minutes=3),  # 57 min AFK
                task="Task1"
            ),
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        # actual_duration: 5 + 3 = 8 minutes (very little active time)
        assert consolidated[0]["actual_duration"] == timedelta(minutes=8)
        # wall-clock: still 2.5 hours
        assert consolidated[0]["duration"] == timedelta(hours=2, minutes=30)

    def test_zero_actual_duration_slots(self, base_time):
        """Slots with zero actual_duration should be handled correctly."""
        slots = [
            make_slot(
                base_time,
                timedelta(hours=1),
                actual_duration=timedelta(0),  # Pure AFK
                task="Task1"
            ),
            make_slot(
                base_time + timedelta(hours=1, minutes=30),
                timedelta(hours=1),
                actual_duration=timedelta(minutes=30),
                task="Task1"
            ),
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        # actual_duration: 0 + 30 = 30 minutes
        assert consolidated[0]["actual_duration"] == timedelta(minutes=30)

    def test_preserves_other_fields(self, base_time):
        """Consolidation should preserve other slot fields."""
        slots = [
            make_slot(
                base_time,
                timedelta(hours=1),
                actual_duration=timedelta(minutes=50),
                project="MyProject",
                task="MyTask"
            ),
            make_slot(
                base_time + timedelta(hours=1, minutes=30),
                timedelta(hours=1),
                actual_duration=timedelta(minutes=55),
                project="MyProject",
                task="MyTask"
            ),
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        assert consolidated[0]["project"] == "MyProject"
        assert consolidated[0]["task"] == "MyTask"
        assert consolidated[0]["type"] == "regular"

    def test_many_slots_same_task(self, base_time):
        """Many consecutive slots should all be merged."""
        # Create 10 slots of same task
        slots = [
            make_slot(
                base_time + timedelta(hours=i, minutes=i*5),
                timedelta(minutes=30),
                actual_duration=timedelta(minutes=25),  # 5 min AFK each
                task="Task1"
            )
            for i in range(10)
        ]

        consolidated = consolidate_sessions(slots)

        assert len(consolidated) == 1
        # actual_duration: 10 * 25 min = 250 min = 4h10m
        assert consolidated[0]["actual_duration"] == timedelta(minutes=250)

    def test_different_types_not_merged(self, base_time):
        """Slots with different types should NOT be merged, even with same task."""
        slots = [
            # Active slot
            {
                "start": base_time,
                "end": base_time + timedelta(hours=1),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(minutes=50),
                "project": "P1",
                "task": "T1",
                "type": "regular",
                "tags": [],
            },
            # AFK slot (gap 30m)
            {
                "start": base_time + timedelta(hours=1, minutes=30),
                "end": base_time + timedelta(hours=1, minutes=30) + timedelta(minutes=30),
                "duration": timedelta(minutes=30),
                "actual_duration": timedelta(minutes=30),  # Full duration is AFK
                "project": "P1",
                "task": "T1",
                "type": "afk",
                "tags": [],
            },
            # Another active slot
            {
                "start": base_time + timedelta(hours=2),
                "end": base_time + timedelta(hours=2) + timedelta(hours=1),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(minutes=48),
                "project": "P1",
                "task": "T1",
                "type": "regular",
                "tags": [],
            },
        ]

        consolidated = consolidate_sessions(slots)

        # Should NOT merge because types differ
        assert len(consolidated) == 3  # Regular, AFK, Regular stay separate
        # Regular slots can be merged separately if adjacent, but AFK breaks the sequence
        # Verify that actual_duration values are NOT summed across types
        assert any(s["type"] == "afk" for s in consolidated)
        assert any(s["type"] == "regular" for s in consolidated)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

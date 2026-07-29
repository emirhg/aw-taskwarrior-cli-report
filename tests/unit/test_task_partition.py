"""Test TaskWarrior task duration partitioning into ACTIVE/AFK portions (AFK-only, no window data)."""
import pytest
from datetime import datetime, timedelta, timezone
from aw_core.models import Event

from tw_report.core.events import partition_task_duration


class TestTaskPartition:
    """Test partitioning of TaskWarrior task durations based on AFK + TaskWarrior data only."""

    @staticmethod
    def create_task_event(start, duration):
        """Helper to create a TaskWarrior task event."""
        return Event(
            timestamp=start,
            duration=duration,
            data={"project": "Test", "description": "Test task"}
        )

    @staticmethod
    def create_afk_event(start, duration, status="afk"):
        """Helper to create an AFK event."""
        return Event(
            timestamp=start,
            duration=duration,
            data={"status": status}
        )

    def test_all_active_no_afk(self):
        """Test: task with no AFK overlap (all active work time)."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        task = self.create_task_event(base, timedelta(minutes=30))
        afk_events = []

        result = partition_task_duration(task, afk_events)

        assert len(result["active_portions"]) == 1
        assert result["active_portions"][0] == (base, base + timedelta(minutes=30))
        assert len(result["afk_portions"]) == 0

    def test_partial_afk_coverage(self):
        """Test: task with some AFK periods during active time."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        # Task: 14:00-15:30 (90 min)
        task = self.create_task_event(base, timedelta(minutes=90))

        # AFK: 14:20-14:30, 14:50-15:00 (20 min idle during task)
        afk_events = [
            self.create_afk_event(base + timedelta(minutes=20), timedelta(minutes=10)),
            self.create_afk_event(base + timedelta(minutes=50), timedelta(minutes=10)),
        ]

        result = partition_task_duration(task, afk_events)

        # Active: 70 min (14:00-14:20, 14:30-14:50, 15:00-15:30)
        assert len(result["active_portions"]) == 3
        total_active = sum(
            (end - start for start, end in result["active_portions"]),
            timedelta(0)
        )
        assert total_active == timedelta(minutes=70)

        # AFK: 20 min (14:20-14:30, 14:50-15:00)
        assert len(result["afk_portions"]) == 2
        total_afk = sum(
            (end - start for start, end in result["afk_portions"]),
            timedelta(0)
        )
        assert total_afk == timedelta(minutes=20)

        # Total: 70 + 20 = 90 min ✓
        assert total_active + total_afk == timedelta(minutes=90)

    def test_entire_task_active(self):
        """Test: task with no AFK events (all active)."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        task = self.create_task_event(base, timedelta(minutes=60))
        afk_events = []

        result = partition_task_duration(task, afk_events)

        assert len(result["active_portions"]) == 1
        assert result["active_portions"][0] == (base, base + timedelta(minutes=60))
        assert len(result["afk_portions"]) == 0

    def test_overlapping_afk_merged(self):
        """Test: overlapping AFK periods are properly merged."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        task = self.create_task_event(base, timedelta(minutes=60))

        # Two overlapping AFK: 14:00-14:30, 14:20-14:50 → merged to 14:00-14:50
        afk_events = [
            self.create_afk_event(base, timedelta(minutes=30)),
            self.create_afk_event(base + timedelta(minutes=20), timedelta(minutes=30)),
        ]

        result = partition_task_duration(task, afk_events)

        # Should be merged into single 50-minute AFK period
        assert len(result["afk_portions"]) == 1
        total_afk = sum(
            (end - start for start, end in result["afk_portions"]),
            timedelta(0)
        )
        assert total_afk == timedelta(minutes=50)

        # Active: 10 min at the end
        assert len(result["active_portions"]) == 1
        assert (result["active_portions"][0][1] - result["active_portions"][0][0]) == timedelta(minutes=10)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])

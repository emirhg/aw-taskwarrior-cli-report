"""Test TaskWarrior task duration partitioning into ACTIVE/AFK/OFFLINE portions."""
import pytest
from datetime import datetime, timedelta, timezone
from aw_core.models import Event

from tw_report.core.events import partition_task_duration


class TestTaskPartition:
    """Test partitioning of TaskWarrior task durations."""

    @staticmethod
    def create_task_event(start, duration):
        """Helper to create a TaskWarrior task event."""
        return Event(
            timestamp=start,
            duration=duration,
            data={"project": "Test", "description": "Test task"}
        )

    @staticmethod
    def create_window_event(start, duration, app="TestApp"):
        """Helper to create a window event."""
        return Event(
            timestamp=start,
            duration=duration,
            data={"app": app, "title": "Test Window"}
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
        """Test: task completely covered by window events, no AFK."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        task = self.create_task_event(base, timedelta(minutes=30))
        windows = [
            self.create_window_event(base, timedelta(minutes=30))  # Entire task is work
        ]
        afk_events = []

        result = partition_task_duration(task, windows, afk_events)

        assert len(result["active_portions"]) == 1
        assert len(result["afk_portions"]) == 0
        assert len(result["offline_portions"]) == 0
        assert result["unaccounted_duration"] == timedelta(0)

    def test_partial_coverage_with_gap(self):
        """Test: task has work time, idle time, and offline gap."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        # Task: 14:00-15:30 (90 min)
        task = self.create_task_event(base, timedelta(minutes=90))

        # Windows: 14:00-14:20, 14:30-14:50 (40 min total activity)
        windows = [
            self.create_window_event(base, timedelta(minutes=20)),
            self.create_window_event(base + timedelta(minutes=30), timedelta(minutes=20)),
        ]

        # AFK: 14:20-14:30, 14:50-15:00 (20 min total idle)
        afk_events = [
            self.create_afk_event(base + timedelta(minutes=20), timedelta(minutes=10)),
            self.create_afk_event(base + timedelta(minutes=50), timedelta(minutes=10)),
        ]

        result = partition_task_duration(task, windows, afk_events)

        # Active: 40 min (14:00-14:20, 14:30-14:50)
        assert len(result["active_portions"]) == 2
        total_active = sum(
            (end - start for start, end in result["active_portions"]),
            timedelta(0)
        )
        assert total_active == timedelta(minutes=40)

        # AFK: 20 min (14:20-14:30, 14:50-15:00)
        assert len(result["afk_portions"]) == 2
        total_afk = sum(
            (end - start for start, end in result["afk_portions"]),
            timedelta(0)
        )
        assert total_afk == timedelta(minutes=20)

        # Offline: 30 min (14:00 start gap + 15:00-15:30 end gap, but starts at first window)
        # Actually: gaps before first window, between coverage, after last coverage
        # Task 14:00-15:30, coverage 14:00-14:50, gap 14:50-15:00, gap 15:00-15:30
        # So offline is only 15:00-15:30 = 30 min
        total_offline = sum(
            (end - start for start, end in result["offline_portions"]),
            timedelta(0)
        )
        assert total_offline == timedelta(minutes=30)

        # Total: 40 + 20 + 30 = 90 min ✓
        assert total_active + total_afk + total_offline == timedelta(minutes=90)

    def test_entire_task_offline(self):
        """Test: task with no window or AFK events (all offline)."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        task = self.create_task_event(base, timedelta(minutes=60))
        windows = []
        afk_events = []

        result = partition_task_duration(task, windows, afk_events)

        assert len(result["active_portions"]) == 0
        assert len(result["afk_portions"]) == 0
        assert len(result["offline_portions"]) == 1
        assert result["offline_portions"][0] == (base, base + timedelta(minutes=60))
        assert result["unaccounted_duration"] == timedelta(minutes=60)

    def test_overlapping_windows_merged(self):
        """Test: overlapping windows are properly merged."""
        tz = timezone(timedelta(hours=-6))
        base = datetime(2026, 7, 28, 14, 0, 0, tzinfo=tz)

        task = self.create_task_event(base, timedelta(minutes=60))

        # Two overlapping windows: 14:00-14:30, 14:20-14:50 → merged to 14:00-14:50
        windows = [
            self.create_window_event(base, timedelta(minutes=30)),
            self.create_window_event(base + timedelta(minutes=20), timedelta(minutes=30)),
        ]
        afk_events = []

        result = partition_task_duration(task, windows, afk_events)

        # Should be merged into single 50-minute period
        assert len(result["active_portions"]) == 1
        total_active = sum(
            (end - start for start, end in result["active_portions"]),
            timedelta(0)
        )
        assert total_active == timedelta(minutes=50)

        # Offline: 10 min at the end
        assert len(result["offline_portions"]) == 1
        assert (result["offline_portions"][0][1] - result["offline_portions"][0][0]) == timedelta(minutes=10)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])

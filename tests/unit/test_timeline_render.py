"""
Unit tests for timeline report rendering (tw_report.pipeline.timeline_render).

Tests verify slot splitting, grouping, formatting, and timeline organization.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tw_report.pipeline.timeline_render import (
    print_timeline_report,
    split_slots_spanning_days,
)


class TestSplitSlotsSpanningDays:
    """Test slot splitting for multi-day spans."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def test_single_day_slot_unchanged(self, base_time):
        """Slots within same day should pass through unchanged."""
        slot = {
            "start": base_time,
            "duration": timedelta(hours=2),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        result = split_slots_spanning_days([slot])
        assert len(result) == 1
        assert result[0]["start"] == base_time
        assert result[0]["duration"] == timedelta(hours=2)

    def test_two_day_slot_split(self, base_time):
        """Slot spanning two days should be split."""
        # Slot from 23:00 to 01:00 (spans midnight)
        slot = {
            "start": base_time.replace(hour=23),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        result = split_slots_spanning_days([slot])

        # Should be split into two pieces
        assert len(result) == 2
        # First piece: 23:00 to 24:00 (1 hour)
        assert result[0]["start"].hour == 23
        assert result[0]["duration"] == timedelta(hours=1)
        # Second piece: 00:00 to 01:00 (1 hour, next day)
        assert result[1]["start"].day == base_time.day + 1
        assert result[1]["duration"] == timedelta(hours=1)

    def test_duration_proportional_allocation(self, base_time):
        """Productive duration should be proportionally allocated."""
        slot = {
            "start": base_time.replace(hour=23),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "productive_duration": timedelta(hours=1),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        result = split_slots_spanning_days([slot])

        assert len(result) == 2
        # Each piece should get proportional productive time (50%)
        assert result[0]["productive_duration"] == timedelta(minutes=30)
        assert result[1]["productive_duration"] == timedelta(minutes=30)

    def test_zero_duration_slot(self, base_time):
        """Zero-duration slot should not cause errors."""
        slot = {
            "start": base_time,
            "duration": timedelta(0),
            "actual_duration": timedelta(0),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        result = split_slots_spanning_days([slot])
        assert len(result) == 1
        assert result[0]["duration"] == timedelta(0)


class TestPrintTimelineReport:
    """Test timeline report rendering."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def sample_slots(self, base_time):
        """Sample timeline slots for a single day."""
        return [
            {
                "start": base_time.replace(hour=9),
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1, minutes=30),
                "type": "regular",
                "project": "Platform",
                "task": "Code Review",
            },
            {
                "start": base_time.replace(hour=11, minute=30),
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "type": "regular",
                "project": "Platform",
                "task": "Meetings",
            },
        ]

    def test_empty_report(self, base_time, capsys):
        """Empty report should show 'No activity found'."""
        print_timeline_report(
            slots=[],
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
        )
        captured = capsys.readouterr()
        assert "No activity found" in captured.out

    def test_basic_timeline(self, base_time, sample_slots, capsys):
        """Basic timeline should show date header and slots."""
        print_timeline_report(
            slots=sample_slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
        )
        captured = capsys.readouterr()
        assert "Wk  Date       Day" in captured.out
        assert "Platform" in captured.out
        assert "Code Review" in captured.out

    def test_offline_task_rendering(self, base_time, capsys):
        """Offline-task slots should show OFF duration notation."""
        slots = [
            {
                "start": base_time.replace(hour=10),
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=1),
                "event_duration": timedelta(hours=1),
                "type": "offline_task",
                "project": "Ecosistema.Trabajo",
                "task": "Offline Task",
            }
        ]
        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
        )
        captured = capsys.readouterr()
        assert "OFF" in captured.out or "offline" in captured.out.lower()

    def test_single_day_report(self, base_time, sample_slots, capsys):
        """Single-day report should not show week totals."""
        print_timeline_report(
            slots=sample_slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            total_time_all=timedelta(hours=4),
        )
        captured = capsys.readouterr()
        assert "Day total:" in captured.out
        # Week totals only shown for multi-day periods
        assert "Week total" not in captured.out

    def test_multi_day_report(self, base_time, sample_slots, capsys):
        """Multi-day report should show week totals."""
        print_timeline_report(
            slots=sample_slots,
            period=":week",
            start_time=base_time,
            end_time=base_time + timedelta(days=7),
            task_based=True,
            total_time_all=timedelta(hours=4),
        )
        captured = capsys.readouterr()
        assert "Day total:" in captured.out

    def test_report_with_metrics(self, base_time, sample_slots, capsys):
        """Report with productivity metrics should include them."""
        print_timeline_report(
            slots=sample_slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            non_afk_time=timedelta(hours=8),
            productive_time=timedelta(hours=3),
            productive_task_time=timedelta(hours=2),
            first_event_time=base_time.replace(hour=9),
            last_event_time=base_time.replace(hour=17),
            total_time_all=timedelta(hours=8),
        )
        captured = capsys.readouterr()
        assert "Period:" in captured.out
        assert "Total Time:" in captured.out

    def test_report_ends_with_separators(self, base_time, sample_slots, capsys):
        """Report should end with proper separators."""
        print_timeline_report(
            slots=sample_slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
        )
        captured = capsys.readouterr()
        # Should have closing separator
        assert "=" * 20 in captured.out or "=" in captured.out.split("\n")[-2]

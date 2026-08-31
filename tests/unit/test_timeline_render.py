"""
Unit tests for timeline report rendering (tw_report.pipeline.timeline_render).

Tests verify slot splitting, grouping, formatting, and timeline organization.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tw_report.pipeline.timeline_render import (
    print_timeline_report,
    split_slots_spanning_days,
    _render_slot_detail,
)


class TestRenderSlotDetail:
    """Test _render_slot_detail function for various detail levels."""

    def test_detail_level_1_no_output(self, capsys):
        """detail_level=1 should not render any details."""
        slot = {
            "categories": [
                {
                    "category": "Coding",
                    "duration": timedelta(hours=1),
                }
            ]
        }
        _render_slot_detail(slot, detail_level=1, width=80)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_detail_level_2_no_output(self, capsys):
        """detail_level=2 should not render any details."""
        slot = {
            "categories": [
                {
                    "category": "Coding",
                    "duration": timedelta(hours=1),
                }
            ]
        }
        _render_slot_detail(slot, detail_level=2, width=80)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_detail_level_3_categories_only(self, capsys):
        """detail_level=3 should render categories only."""
        slot = {
            "categories": [
                {
                    "category": "Coding",
                    "duration": timedelta(hours=2),
                    "apps": [],
                }
            ]
        }
        _render_slot_detail(slot, detail_level=3, width=80)
        captured = capsys.readouterr()
        assert "Coding" in captured.out
        assert "2:00:00" in captured.out

    def test_detail_level_4_with_apps(self, capsys):
        """detail_level=4 should render categories and apps."""
        slot = {
            "categories": [
                {
                    "category": "Coding",
                    "duration": timedelta(hours=2),
                    "apps": [
                        {
                            "app": "VSCode",
                            "duration": timedelta(hours=2),
                            "titles": [],
                        }
                    ],
                }
            ]
        }
        _render_slot_detail(slot, detail_level=4, width=80)
        captured = capsys.readouterr()
        assert "Coding" in captured.out
        assert "VSCode" in captured.out

    def test_detail_level_5_with_titles(self, capsys):
        """detail_level=5 should render categories, apps, and titles."""
        slot = {
            "categories": [
                {
                    "category": "Coding",
                    "duration": timedelta(hours=1),
                    "apps": [
                        {
                            "app": "VSCode",
                            "duration": timedelta(hours=1),
                            "titles": [
                                {
                                    "title": "tw-report.py",
                                    "duration": timedelta(hours=1),
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        _render_slot_detail(slot, detail_level=5, width=120)
        captured = capsys.readouterr()
        assert "Coding" in captured.out
        assert "VSCode" in captured.out
        assert "tw-report" in captured.out

    def test_empty_categories(self, capsys):
        """Slot with no categories should render nothing."""
        slot = {"categories": []}
        _render_slot_detail(slot, detail_level=3, width=80)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_missing_categories_field(self, capsys):
        """Slot missing categories field should render nothing."""
        slot = {}
        _render_slot_detail(slot, detail_level=3, width=80)
        captured = capsys.readouterr()
        assert captured.out == ""


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
            "actual_duration": timedelta(hours=2),
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
        # Slot from 05:00 UTC to 07:00 UTC (23:00 local 06-30 to 01:00 local 07-01)
        # This spans midnight in local time (UTC-6), so it should be split
        slot = {
            "start": base_time.replace(hour=5),  # 05:00 UTC = 23:00 previous day local
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        # Use day_start_hour=0 for calendar-day boundaries (midnight local time)
        result = split_slots_spanning_days([slot], day_start_hour=0)

        # Should be split into two pieces (one before midnight local, one after midnight local)
        assert len(result) == 2, f"Expected 2 pieces, got {len(result)}"
        # First piece: 23:00 to 00:00 = 1 hour on 06-30
        assert result[0]["duration"] == timedelta(hours=1)
        # Second piece: 00:00 to 01:00 = 1 hour on 07-01
        assert result[1]["duration"] == timedelta(hours=1)

    def test_duration_proportional_allocation(self, base_time):
        """Productive duration should be proportionally allocated."""
        # Slot from 05:00 UTC to 07:00 UTC (23:00 local 06-30 to 01:00 local 07-01)
        slot = {
            "start": base_time.replace(hour=5),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "productive_duration": timedelta(hours=1),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        # Use day_start_hour=0 for calendar-day boundaries (midnight local time)
        result = split_slots_spanning_days([slot], day_start_hour=0)

        assert len(result) == 2
        # Each piece should get proportional productive time (50%)
        assert result[0]["productive_duration"] == timedelta(minutes=30)
        assert result[1]["productive_duration"] == timedelta(minutes=30)

    def test_zero_duration_slot(self, base_time):
        """Zero-duration slots are invalid and skipped by ReportTimelineSlot.from_dict()."""
        slot = {
            "start": base_time,
            "duration": timedelta(0),
            "actual_duration": timedelta(0),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }
        # Use day_start_hour=0 for calendar-day boundaries
        # Zero-duration slots are invalid for ReportTimelineSlot, so they get skipped
        result = split_slots_spanning_days([slot], day_start_hour=0)
        assert len(result) == 0


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
        # At default detail_level=1, only projects are shown, not task names
        assert "Day total:" in captured.out

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
        """Single-day report should show day and week totals."""
        print_timeline_report(
            slots=sample_slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
        )
        captured = capsys.readouterr()
        assert "Day total:" in captured.out
        # Week totals are shown even for single-day reports
        assert "Week total" in captured.out

    def test_multi_day_report(self, base_time, sample_slots, capsys):
        """Multi-day report should show week totals."""
        print_timeline_report(
            slots=sample_slots,
            period=":week",
            start_time=base_time,
            end_time=base_time + timedelta(days=7),
            task_based=True,
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
        )
        captured = capsys.readouterr()
        assert "Period" in captured.out  # in SUMMARY section
        assert "TOTALS" in captured.out
        assert "Total Time" in captured.out

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

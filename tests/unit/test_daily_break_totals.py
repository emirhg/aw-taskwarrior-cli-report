"""Test per-day break time calculations respecting day boundaries."""

from datetime import datetime, timedelta, timezone

from tw_report.core.report_slot import (
    compute_daily_break_totals,
    compute_total_break_time,
    ReportTimelineSlot,
)


class TestDailyBreakTotals:
    """Test compute_daily_break_totals and compute_total_break_time."""

    def test_simple_break_calculation(self):
        """Two slots on the same logical day with a gap = one break."""
        # Two slots with a 30-minute gap between them
        slot1 = ReportTimelineSlot(
            start=datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
        )
        slot2 = ReportTimelineSlot(
            start=datetime(2026, 9, 18, 10, 30, 0, tzinfo=timezone.utc),
            end=datetime(2026, 9, 18, 11, 30, 0, tzinfo=timezone.utc),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
        )

        totals = compute_daily_break_totals([slot1, slot2], day_start_hour=4)
        # There should be exactly one logical day with one 30-minute break
        assert len(totals) == 1
        assert list(totals.values())[0] == timedelta(minutes=30)

    def test_total_break_time_aggregates(self):
        """Total break time should sum breaks from all logical days."""
        slots = [
            ReportTimelineSlot(
                start=datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc),
                end=datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
            ),
            ReportTimelineSlot(
                start=datetime(2026, 9, 18, 10, 30, 0, tzinfo=timezone.utc),
                end=datetime(2026, 9, 18, 11, 30, 0, tzinfo=timezone.utc),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
            ),
        ]

        total = compute_total_break_time(slots, day_start_hour=4)
        assert total == timedelta(minutes=30)

    def test_no_breaks_for_single_slot(self):
        """Single slot should result in zero break time."""
        slot = ReportTimelineSlot(
            start=datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
        )

        total = compute_total_break_time([slot], day_start_hour=4)
        assert total == timedelta(0)

    def test_sub_minute_gap_not_counted(self):
        """Gaps < 1 minute should not be counted as breaks."""
        slots = [
            ReportTimelineSlot(
                start=datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc),
                end=datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
            ),
            ReportTimelineSlot(
                start=datetime(2026, 9, 18, 10, 0, 30, tzinfo=timezone.utc),  # 30 sec gap
                end=datetime(2026, 9, 18, 11, 0, 30, tzinfo=timezone.utc),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
            ),
        ]

        total = compute_total_break_time(slots, day_start_hour=4)
        assert total == timedelta(0)  # 30 sec gap below 1-minute threshold

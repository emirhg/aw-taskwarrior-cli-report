"""Test Total Time calculation fix (Phase 16) — ensure Total Time = Worked Time + Break Time."""

from datetime import datetime, timedelta, timezone

from tw_report.pipeline.models import ReportTotals
from tw_report.pipeline.report_render import print_report_totals


class TestTotalTimeCalculation:
    """Regression tests for Total Time calculation bug (Phase 16)."""

    def test_total_time_equals_worked_plus_break_with_large_event_window(self, capsys):
        """Total Time should equal Worked + Break, not last_event_time - first_event_time.

        This is the core regression test for Phase 16 bug fix. When first_event_time
        and last_event_time span a huge multi-month range (e.g., --project X :all
        spanning from April to September) but worked_time + break_time is small
        (e.g., ~187 hours), the old code would incorrectly use the calendar span
        (~3824 hours) instead of the sum of components.

        With the fix, Total Time must always equal Worked + Break, even when the
        raw event window is much larger.
        """
        # Simulate the exact bug scenario: first/last events 5 months apart,
        # but only 187 hours of actual work + breaks
        first_event_time = datetime(2026, 4, 12, 22, 30, tzinfo=timezone.utc)
        last_event_time = datetime(2026, 9, 19, 6, 54, tzinfo=timezone.utc)

        # The calendar span is huge (5 months)
        calendar_span = last_event_time - first_event_time
        assert calendar_span > timedelta(hours=3800), "Setup: calendar span should be ~3800+ hours"

        # But actual work + breaks is much smaller (~187 hours)
        online_time = timedelta(hours=58, minutes=5, seconds=19)
        offline_time = timedelta(hours=74, minutes=31, seconds=1)
        active_time = timedelta(hours=46, minutes=18, seconds=33)
        afk_time = timedelta(hours=11, minutes=46, seconds=46)
        total_break = timedelta(hours=55, minutes=7, seconds=29)
        productive_time = timedelta(hours=132, minutes=36, seconds=21)

        # The sum should be ~187 hours (worked + break)
        worked_time = online_time + offline_time
        total_expected = worked_time + total_break
        assert total_expected < timedelta(hours=200), "Setup: total should be ~187 hours"

        # Create ReportTotals object (only accepts online, offline, afk, productive)
        totals = ReportTotals(
            online_time=online_time,
            offline_time=offline_time,
            afk_time=afk_time,
            productive_time=productive_time,
        )

        # Call the function and verify Total Time is the sum, not the calendar span
        print_report_totals(
            total_time_all=totals,
            total_break=total_break,
            first_event_time=first_event_time,
            last_event_time=last_event_time,
        )

        captured = capsys.readouterr()
        output = captured.out

        # Extract the "Total Time" line from output
        total_time_line = [line for line in output.split('\n') if 'Total Time' in line]
        assert len(total_time_line) > 0, "Total Time line should be present in output"

        # Verify the Total Time line shows the sum, not the calendar span
        total_line = total_time_line[0]
        assert 'Total Time' in total_line

        # The old bug would show ~3824 hours (calendar span), new code shows ~187 hours
        assert '3824' not in total_line, (
            f"Bug regression detected: Total Time is using calendar span instead of sum. "
            f"Line: {total_line}"
        )

        # Verify it's in the right ballpark (187-189 hours range)
        assert any(h in total_line for h in ['187', '188', '189']), (
            f"Total Time should be ~187-189 hours (Worked+Break), got: {total_line}"
        )

    def test_total_time_single_day_unchanged(self, capsys):
        """Single-day case should be unaffected by the fix (sanity check)."""
        # Single day case: event window IS roughly equal to worked + break
        day = datetime(2026, 9, 18, tzinfo=timezone.utc)
        first_event_time = day.replace(hour=9, minute=0)
        last_event_time = day.replace(hour=18, minute=0)

        online_time = timedelta(hours=7)
        offline_time = timedelta(0)
        active_time = timedelta(hours=7)
        afk_time = timedelta(0)
        total_break = timedelta(hours=2)
        productive_time = timedelta(hours=7)

        worked_time = online_time + offline_time  # 7 hours
        expected_total = worked_time + total_break  # 9 hours
        calendar_span = last_event_time - first_event_time  # 9 hours

        # For single day, these happen to be close/equal
        assert abs(expected_total - calendar_span) < timedelta(minutes=1), (
            "Setup: single-day case should have calendar_span ≈ worked + break"
        )

        totals = ReportTotals(
            online_time=online_time,
            offline_time=offline_time,
            afk_time=afk_time,
            productive_time=productive_time,
        )

        print_report_totals(
            total_time_all=totals,
            total_break=total_break,
            first_event_time=first_event_time,
            last_event_time=last_event_time,
        )

        captured = capsys.readouterr()
        output = captured.out

        # Verify Total Time is present and reasonable (should be ~9 hours)
        total_time_line = [line for line in output.split('\n') if 'Total Time' in line]
        assert len(total_time_line) > 0
        assert '9:' in total_time_line[0], "Single-day total should show ~9 hours"

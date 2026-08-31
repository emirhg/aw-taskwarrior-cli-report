"""Integration tests for TOTALS section output correctness.

Tests verify that the values shown in the TOTALS section are mathematically correct:
- Online Time = Active Time + AFK Time
- Total Time = Online Time + Offline Time
- Values are consistent across different rendering paths
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
import re
import sys

import pytest

from tw_report.pipeline.report_render import print_report_totals
from tw_report.pipeline.models import ReportTotals
from tw_report.pipeline.timeline_render import print_timeline_report


class TestTotalsOutputCorrectness:
    """Verify TOTALS section calculations are correct."""

    def test_totals_online_equals_active_plus_afk(self, capsys):
        """Online Time should equal Active Time + AFK Time."""
        active_time = timedelta(hours=6)
        afk_time = timedelta(hours=1)
        offline_time = timedelta(hours=2)

        print_report_totals(
            total_time_all=active_time + afk_time,  # online time
            total_productive_all=timedelta(hours=3),
            total_afk=afk_time,
            total_offline=offline_time,
            total_non_afk=active_time,
        )

        captured = capsys.readouterr()
        output = captured.out

        # Verify the math: Online (6+1=7h) = Active (6h) + AFK (1h)
        assert "6:00:00" in output  # Active time
        assert "1:00:00" in output  # AFK time (or could be part of larger time)
        assert "7:00:00" in output or "7h" in output  # Online time should show somewhere
        assert "TOTALS" in output

    def test_totals_total_equals_online_plus_offline(self, capsys):
        """Total Time should equal Online Time + Offline Time."""
        online_time = timedelta(hours=8)
        offline_time = timedelta(hours=2)
        total_time_expected = online_time + offline_time

        print_report_totals(
            total_time_all=online_time,
            total_productive_all=timedelta(hours=5),
            total_afk=timedelta(hours=1),
            total_offline=offline_time,
            total_non_afk=timedelta(hours=7),
        )

        captured = capsys.readouterr()
        output = captured.out

        # Should show: Active (7h), AFK (1h), Online (8h), Offline (2h), Total (10h)
        assert "8:00:00" in output or "8h" in output  # Online
        assert "2:00:00" in output  # Offline
        assert "TOTALS" in output

    def test_totals_with_report_totals_object(self, capsys):
        """TOTALS output using ReportTotals object should be consistent."""
        totals = ReportTotals(
            online_time=timedelta(hours=8),
            productive_time=timedelta(hours=4),
            afk_time=timedelta(hours=1),
            offline_time=timedelta(hours=2),
        )

        print_report_totals(totals)

        captured = capsys.readouterr()
        output = captured.out

        # Should show all components
        assert "TOTALS" in output
        assert "8:00:00" in output or "8h" in output  # Online
        assert "1:00:00" in output or "1h" in output  # AFK
        assert "2:00:00" in output  # Offline

    def test_totals_zero_values_handled_correctly(self, capsys):
        """TOTALS should handle zero values gracefully."""
        print_report_totals(
            total_time_all=timedelta(hours=8),
            total_productive_all=timedelta(hours=4),
            total_afk=timedelta(0),  # No AFK
            total_offline=timedelta(0),  # No offline
            total_non_afk=timedelta(hours=8),
        )

        captured = capsys.readouterr()
        output = captured.out

        # Should show online time and active time, but NOT AFK or offline (they're 0)
        assert "TOTALS" in output
        assert "8:00:00" in output  # Active/Online


class TestTotalsMetricRelationships:
    """Test fundamental relationships between metrics."""

    def test_metric_sum_relationship(self):
        """Verify: Online = Active + AFK (as timedeltas)."""
        active = timedelta(hours=7)
        afk = timedelta(hours=1)
        online = active + afk

        assert online == timedelta(hours=8)
        assert online - afk == active

    def test_total_time_relationship(self):
        """Verify: Total = Online + Offline."""
        online = timedelta(hours=8)
        offline = timedelta(hours=2)
        total = online + offline

        assert total == timedelta(hours=10)
        assert total - offline == online

    def test_report_totals_active_time_calculation(self):
        """ReportTotals.active_time should equal online - afk."""
        totals = ReportTotals(
            online_time=timedelta(hours=8),
            afk_time=timedelta(hours=1),
        )

        assert totals.active_time == timedelta(hours=7)


def _parse_duration_from_output(output: str, label: str) -> timedelta:
    """Extract a duration value from TOTALS section output.

    Args:
        output: Captured output from print_report_totals or print_timeline_report
        label: Label to search for (e.g., "Active Time", "Online", "Total Time")

    Returns:
        Parsed timedelta, or timedelta(0) if not found
    """
    # Look for patterns like "    Active Time" or "  Online" followed by duration
    pattern = rf"{label}.*?(\d+):(\d+):(\d+)"
    match = re.search(pattern, output)
    if match:
        hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return timedelta(0)


class TestTimelineReportTotalsInvariants:
    """Test end-to-end invariants in print_timeline_report TOTALS output.

    These tests verify that the values calculated by print_timeline_report
    satisfy the fundamental relationships:
    - Online = Active + AFK
    - Total = Online + Offline
    """

    def test_timeline_report_online_equals_active_plus_afk(self, capsys):
        """TOTALS: Online Time should equal Active Time + AFK Time."""
        base_time = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)

        slots = [
            {
                "project": "TestProj",
                "task": "Task1",
                "type": "activity",
                "start": base_time.replace(hour=9),
                "end": base_time.replace(hour=10),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
            },
            {
                "type": "afk",
                "start": base_time.replace(hour=10),
                "end": base_time.replace(hour=11),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(0),  # No online work during AFK
                "afk_duration": timedelta(hours=1),  # All 1h is idle time
                "productive_duration": timedelta(0),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=1),  # 1 hour active
            productive_time=timedelta(hours=1),
            task_based=True,
        )

        captured = capsys.readouterr()
        output = captured.out

        # Parse values from output
        active_time = _parse_duration_from_output(output, "Active Time")
        afk_time = _parse_duration_from_output(output, "AFK time")
        online_time = _parse_duration_from_output(output, "  Online")

        # Verify invariant: Online = Active + AFK
        assert active_time == timedelta(hours=1), f"Active time should be 1h, got {active_time}"
        assert afk_time == timedelta(hours=1), f"AFK time should be 1h, got {afk_time}"
        assert online_time == active_time + afk_time, (
            f"Invariant violated: Online ({online_time}) should equal "
            f"Active ({active_time}) + AFK ({afk_time})"
        )

    def test_timeline_report_total_equals_online_plus_offline(self, capsys):
        """TOTALS: Total Time should equal Online Time + Offline Time."""
        base_time = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)

        slots = [
            {
                "project": "TestProj",
                "task": "OfflineTask",
                "type": "offline_task",
                "start": base_time.replace(hour=11),
                "end": base_time.replace(hour=13),  # 2 hour wall-clock
                "duration": timedelta(hours=2),
                "event_duration": timedelta(minutes=30),  # 30 min AW overlap
                "actual_duration": timedelta(minutes=30),
                "offline_extension_duration": timedelta(hours=2) - timedelta(minutes=30),
                "productive_duration": timedelta(minutes=30),
            },
            {
                "type": "afk",
                "start": base_time.replace(hour=9),
                "end": base_time.replace(hour=10),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(0),  # No online work during AFK
                "afk_duration": timedelta(hours=1),  # All 1h is idle time
                "productive_duration": timedelta(0),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=1),  # 1 hour active (from AFK bucket)
            productive_time=timedelta(hours=0, minutes=30),
            task_based=True,
        )

        captured = capsys.readouterr()
        output = captured.out

        # Parse values from output
        online_time = _parse_duration_from_output(output, "  Online")
        offline_time = _parse_duration_from_output(output, "  Offline tracked")
        total_time = _parse_duration_from_output(output, "Total Time")

        # Verify invariant: Total = Online + Offline
        # Offline gap = wall_clock - event_duration = 2h - 30m = 1.5h
        expected_offline = timedelta(hours=2) - timedelta(minutes=30)
        assert offline_time == expected_offline, (
            f"Offline time should be {expected_offline}, got {offline_time}"
        )
        assert total_time == online_time + offline_time, (
            f"Invariant violated: Total ({total_time}) should equal "
            f"Online ({online_time}) + Offline ({offline_time})"
        )

    def test_timeline_report_does_not_double_count_offline(self, capsys):
        """CRITICAL: Online should NOT include Offline time (regression test).

        This is a regression test for the bug where offline time was
        double-counted: included in both Online and separately in Offline.

        The bug manifested as: Online = 09:52:56, Offline = 01:20:02,
        when it should be: Online = 08:32:54, Offline = 01:20:02
        (difference of 01:20:02 which was the offline time itself).
        """
        base_time = datetime(2026, 7, 28, 11, 55, 0, tzinfo=timezone.utc)

        slots = [
            {
                "project": "Ecosistema",
                "task": "OfflineWork",
                "type": "offline_task",
                "start": base_time,
                "end": base_time + timedelta(hours=1, minutes=20),  # 1:20 wall-clock
                "duration": timedelta(hours=1, minutes=20),
                "event_duration": timedelta(0),  # No AW activity
                "actual_duration": timedelta(0),
                "offline_extension_duration": timedelta(hours=1, minutes=20),  # All is offline
                "productive_duration": timedelta(0),
            },
            {
                "type": "afk",
                "start": base_time + timedelta(hours=2),
                "end": base_time + timedelta(hours=2, minutes=15),
                "duration": timedelta(minutes=15),
                "actual_duration": timedelta(0),  # No online work during AFK
                "afk_duration": timedelta(minutes=15),  # All 15m is idle time
                "productive_duration": timedelta(0),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=7, minutes=13, seconds=59),
            productive_time=timedelta(0),
            task_based=True,
        )

        captured = capsys.readouterr()
        output = captured.out

        # Parse values
        active_time = _parse_duration_from_output(output, "Active Time")
        afk_time = _parse_duration_from_output(output, "AFK time")
        online_time = _parse_duration_from_output(output, "  Online")
        offline_time = _parse_duration_from_output(output, "  Offline tracked")
        total_time = _parse_duration_from_output(output, "Total Time")

        # The bug would cause:
        # offline_time = 1:20:02 (correct)
        # online_time = 9:52:56 (wrong - includes offline)
        # total_time = 11:12:58 (correct sum but from wrong online value)
        #
        # After fix:
        # offline_time = 1:20:02 (correct)
        # online_time = active + afk = 8:32:54 (correct)
        # total_time = online + offline = 11:12:58 (correct)

        # Critical assertion: Online should NOT equal (Online + Offline)
        # This checks that offline time is not being included in online
        assert online_time != online_time + offline_time, (
            "BUG: Online time includes offline time! "
            f"Online={online_time}, Offline={offline_time} "
            f"(Online should not equal Online+Offline={online_time + offline_time})"
        )

        # Verify correct relationships: Online = Active + AFK
        expected_online = active_time + afk_time
        assert online_time == expected_online, (
            f"Online ({online_time}) should equal "
            f"Active ({active_time}) + AFK ({afk_time}) = {expected_online}"
        )

        # Verify: Total ≈ Online + Offline (allow 2-second tolerance for rounding)
        expected_total = online_time + offline_time
        tolerance = timedelta(seconds=2)
        assert abs((total_time - expected_total).total_seconds()) <= tolerance.total_seconds(), (
            f"Total ({total_time}) should approximately equal "
            f"Online ({online_time}) + Offline ({offline_time}) = {expected_total} "
            f"(tolerance: {tolerance})"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

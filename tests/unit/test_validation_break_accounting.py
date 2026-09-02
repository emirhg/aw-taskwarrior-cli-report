"""Test that Worked Time + Break Time = Tracked Activity (critical validation).

This test ensures the fundamental accounting equation holds:
    Worked Time (Online + Offline) + Break Time (gaps) = Total Tracked Activity

This is not just a check—it's a guarantee that all time is accounted for and
no time is lost or double-counted in the break timing system.
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
import re
import sys

import pytest

from tw_report.pipeline.models import PeriodMetrics
from tw_report.pipeline.timeline_render import print_timeline_report


def _extract_duration_from_totals(output: str, label: str) -> timedelta:
    """Extract a duration value from TOTALS section output.

    Searches for label followed by duration in HH:MM:SS format.
    Returns timedelta(0) if not found.
    """
    pattern = rf"{re.escape(label)}.*?(\d+):(\d+):(\d+)"
    match = re.search(pattern, output)
    if match:
        hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return timedelta(0)


class TestValidationBreakAccounting:
    """Test the critical validation: Worked + Break = Tracked Activity."""

    def test_validation_equation_holds_with_breaks(self, capsys):
        """Worked Time + Break Time should equal Total Time shown."""
        base_time = datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc)

        # Create slots with intentional gaps:
        # - Slot 1: 09:00-10:00 (1 hour work)
        # - GAP: 10:00-10:30 (30 min break)
        # - Slot 2: 10:30-11:00 (30 min work)
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
                "project": "TestProj",
                "task": "Task2",
                "type": "activity",
                "start": base_time.replace(hour=10, minute=30),
                "end": base_time.replace(hour=11),
                "duration": timedelta(minutes=30),
                "actual_duration": timedelta(minutes=30),
                "productive_duration": timedelta(minutes=30),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=1, minutes=30),  # 90 minutes active
            productive_time=timedelta(hours=1, minutes=30),
            task_based=True,
            total_break=timedelta(minutes=30),  # The 30-minute gap
        )

        captured = capsys.readouterr()
        output = captured.out

        # Extract key metrics
        worked_time = _extract_duration_from_totals(output, "  Worked Time")
        break_time = _extract_duration_from_totals(output, "  Break Time")
        total_time = _extract_duration_from_totals(output, "Total Time")

        # Verify the equation: Worked + Break = Total
        expected_total = worked_time + break_time
        assert total_time == expected_total, (
            f"CRITICAL VALIDATION FAILED: "
            f"Worked Time ({worked_time}) + Break Time ({break_time}) = {expected_total}, "
            f"but Total Time shows {total_time}"
        )

    def test_validation_equation_with_offline_time(self, capsys):
        """Worked Time (Online + Offline) + Break Time = Total Time."""
        base_time = datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc)

        # Create slots with offline time:
        # - Slot 1: 09:00-09:30 (online work)
        # - Slot 2: 09:30-10:00 (offline task - system powered off)
        # - GAP: 10:00-10:15 (15 min break)
        # - Slot 3: 10:15-10:45 (online work)
        slots = [
            {
                "project": "Work",
                "task": "OnlineTask",
                "type": "activity",
                "start": base_time.replace(hour=9),
                "end": base_time.replace(hour=9, minute=30),
                "duration": timedelta(minutes=30),
                "actual_duration": timedelta(minutes=30),
                "productive_duration": timedelta(minutes=30),
            },
            {
                "project": "Work",
                "task": "OfflineWork",
                "type": "offline_task",
                "start": base_time.replace(hour=9, minute=30),
                "end": base_time.replace(hour=10),  # 30 min wall-clock
                "duration": timedelta(minutes=30),
                "event_duration": timedelta(0),  # No AW overlap
                "actual_duration": timedelta(0),
                "offline_extension_duration": timedelta(minutes=30),
                "productive_duration": timedelta(0),
            },
            {
                "project": "Work",
                "task": "OnlineTask2",
                "type": "activity",
                "start": base_time.replace(hour=10, minute=15),
                "end": base_time.replace(hour=10, minute=45),
                "duration": timedelta(minutes=30),
                "actual_duration": timedelta(minutes=30),
                "productive_duration": timedelta(minutes=30),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=1),  # 60 min online activity
            productive_time=timedelta(hours=1),
            task_based=True,
            total_break=timedelta(minutes=15),  # The 15-minute gap
        )

        captured = capsys.readouterr()
        output = captured.out

        # Extract metrics
        worked_time = _extract_duration_from_totals(output, "  Worked Time")
        break_time = _extract_duration_from_totals(output, "  Break Time")
        total_time = _extract_duration_from_totals(output, "Total Time")

        # Verify: Worked + Break = Total
        expected_total = worked_time + break_time
        assert total_time == expected_total, (
            f"VALIDATION FAILED with offline time: "
            f"Worked ({worked_time}) + Break ({break_time}) = {expected_total}, "
            f"got Total = {total_time}"
        )

    def test_validation_no_breaks_means_worked_equals_total(self, capsys):
        """When there are no breaks, Worked Time = Total Time."""
        base_time = datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc)

        # Single continuous slot (no gaps)
        slots = [
            {
                "project": "Work",
                "task": "Task1",
                "type": "activity",
                "start": base_time.replace(hour=9),
                "end": base_time.replace(hour=12),
                "duration": timedelta(hours=3),
                "actual_duration": timedelta(hours=3),
                "productive_duration": timedelta(hours=3),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=3),
            productive_time=timedelta(hours=3),
            task_based=True,
            total_break=timedelta(0),  # No breaks
        )

        captured = capsys.readouterr()
        output = captured.out

        worked_time = _extract_duration_from_totals(output, "  Worked Time")
        break_time = _extract_duration_from_totals(output, "  Break Time")
        total_time = _extract_duration_from_totals(output, "Total Time")

        # When break_time = 0, then Worked Time should equal Total Time
        assert break_time == timedelta(0), "Break time should be zero for continuous work"
        assert total_time == worked_time, (
            f"When there are no breaks, Total Time ({total_time}) should equal "
            f"Worked Time ({worked_time})"
        )

    def test_period_metrics_add_with_breaks(self):
        """PeriodMetrics should correctly accumulate break time."""
        metrics = PeriodMetrics()

        # Add some work with breaks
        metrics.add(
            online=timedelta(hours=2),
            afk=timedelta(minutes=15),
            offline=timedelta(hours=1),
            productive=timedelta(hours=1, minutes=30),
            break_time=timedelta(minutes=20),
        )

        assert metrics.online_duration == timedelta(hours=2)
        assert metrics.break_duration == timedelta(minutes=20)

        # Add more breaks
        metrics.add(break_time=timedelta(minutes=10))

        assert metrics.break_duration == timedelta(minutes=30)

    def test_validation_printed_equation(self, capsys):
        """The validation line should show the math equation clearly."""
        base_time = datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc)

        slots = [
            {
                "project": "Work",
                "task": "Task1",
                "type": "activity",
                "start": base_time.replace(hour=9),
                "end": base_time.replace(hour=10),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
            },
        ]

        print_timeline_report(
            slots=slots,
            period=":today",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            non_afk_time=timedelta(hours=1),
            productive_time=timedelta(hours=1),
            task_based=True,
            total_break=timedelta(minutes=15),
        )

        captured = capsys.readouterr()
        output = captured.out

        # Verify that validation section is present and shows the accounting check
        assert "Validation:" in output, "Validation section should be printed in TOTALS"
        assert "Tracked Activity:" in output, "Validation should show Tracked Activity"
        assert "Components sum:" in output, "Validation should show Components sum"
        assert "Status:" in output, "Validation should show PASS/MISMATCH status"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

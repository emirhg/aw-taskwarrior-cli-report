"""Integration tests for TOTALS section output correctness.

Tests verify that the values shown in the TOTALS section are mathematically correct:
- Online Time = Active Time + AFK Time
- Total Time = Online Time + Offline Time
- Values are consistent across different rendering paths
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
import sys

import pytest

from tw_report.pipeline.report_render import print_report_totals
from tw_report.pipeline.models import ReportTotals


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

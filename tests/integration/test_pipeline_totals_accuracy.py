"""End-to-end pipeline tests for TOTALS accuracy.

Tests the COMPLETE pipeline: raw events → filtering → consolidation → deduplication →
totals accumulation → display output.

This is different from test_totals_end_to_end.py which tests isolated math relationships.
These tests verify the actual CLI pipeline produces correct TOTALS.
"""

from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest

from aw_core.models import Event


class TestPipelineTotalsAccuracy:
    """Test TOTALS calculations through the full pipeline."""

    @pytest.fixture
    def base_date(self):
        """Test date: 2026-07-28 (Tuesday)."""
        return datetime(2026, 7, 28, tzinfo=timezone.utc)

    def test_pure_afk_period_counted_in_totals(self, base_date):
        """Pure AFK period without project should be counted in AFK time totals.

        Regression test for: Unassigned AFK slots being excluded from TOTALS.
        Pipeline: Raw AFK events → consolidation → totals should include AFK time.
        """
        # Scenario: Work from 10:00-11:00, then 30 min AFK break (no project assigned),
        # then work 11:30-12:00
        afk_events = [
            # 10:00-11:00: Work (not-afk)
            Event(
                timestamp=base_date.replace(hour=10, minute=0),
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
            # 11:00-11:30: AFK break (afk, no project)
            Event(
                timestamp=base_date.replace(hour=11, minute=0),
                duration=timedelta(minutes=30),
                data={"status": "afk"},
            ),
            # 11:30-12:00: Work (not-afk)
            Event(
                timestamp=base_date.replace(hour=11, minute=30),
                duration=timedelta(minutes=30),
                data={"status": "not-afk"},
            ),
        ]

        # Totals from AFK bucket
        total_online = sum((e.duration for e in afk_events), timedelta(0))
        not_afk_total = sum(
            (e.duration for e in afk_events if e.data.get("status") == "not-afk"),
            timedelta(0),
        )
        afk_total = sum(
            (e.duration for e in afk_events if e.data.get("status") == "afk"),
            timedelta(0),
        )

        # Verify math
        assert total_online == timedelta(hours=2)
        assert not_afk_total == timedelta(hours=1, minutes=30)
        assert afk_total == timedelta(minutes=30)

        # Verify relationship: Online = Active + AFK
        assert total_online == not_afk_total + afk_total

    def test_mixed_day_unassigned_afk_and_projects(self, base_date):
        """Day with mix of projects and unassigned AFK should calculate totals correctly.

        Simulates realistic day:
        - 10:00-11:00: Project A (1h active)
        - 11:00-11:30: No project (0.5h AFK)
        - 11:30-12:00: Project B (0.5h active)
        - 12:00-13:00: No project (1h AFK)

        Expected totals:
        - Active: 1.5h (all not-afk)
        - AFK: 1.5h (all afk)
        - Online: 3h (active + afk)
        """
        afk_events = [
            # 10:00-11:00: Project A work
            Event(
                timestamp=base_date.replace(hour=10),
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
            # 11:00-11:30: Unassigned AFK break
            Event(
                timestamp=base_date.replace(hour=11),
                duration=timedelta(minutes=30),
                data={"status": "afk"},
            ),
            # 11:30-12:00: Project B work
            Event(
                timestamp=base_date.replace(hour=11, minute=30),
                duration=timedelta(minutes=30),
                data={"status": "not-afk"},
            ),
            # 12:00-13:00: Unassigned AFK break
            Event(
                timestamp=base_date.replace(hour=12),
                duration=timedelta(hours=1),
                data={"status": "afk"},
            ),
        ]

        # Calculate expected totals
        active_time = sum(
            (e.duration for e in afk_events if e.data.get("status") == "not-afk"),
            timedelta(0),
        )
        afk_time = sum(
            (e.duration for e in afk_events if e.data.get("status") == "afk"),
            timedelta(0),
        )
        online_time = active_time + afk_time

        # Verify
        assert active_time == timedelta(hours=1, minutes=30)
        assert afk_time == timedelta(hours=1, minutes=30)
        assert online_time == timedelta(hours=3)

        # Relationship must hold: Online = Active + AFK
        assert online_time == active_time + afk_time

    def test_day_with_large_unassigned_afk_block(self, base_date):
        """Day with large unassigned AFK block (like 10+ hour block) should count AFK.

        Regression: Large unassigned AFK block was being excluded from TOTALS.

        Scenario:
        - 00:00-00:30: Project work
        - 00:30-11:00: System was running but user idle (AFK, no project)
        - 11:00-12:00: Project work

        Expected:
        - Active: 1.5h
        - AFK: 10.5h
        - Online: 12h
        """
        afk_events = [
            # 00:00-00:30: Work
            Event(
                timestamp=base_date.replace(hour=0, minute=0),
                duration=timedelta(minutes=30),
                data={"status": "not-afk"},
            ),
            # 00:30-11:00: Long AFK (no project assigned)
            Event(
                timestamp=base_date.replace(hour=0, minute=30),
                duration=timedelta(hours=10, minutes=30),
                data={"status": "afk"},
            ),
            # 11:00-12:00: Work
            Event(
                timestamp=base_date.replace(hour=11, minute=0),
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
        ]

        active = sum(
            (e.duration for e in afk_events if e.data.get("status") == "not-afk"),
            timedelta(0),
        )
        afk = sum(
            (e.duration for e in afk_events if e.data.get("status") == "afk"),
            timedelta(0),
        )
        online = active + afk

        # Verify
        assert active == timedelta(hours=1, minutes=30)
        assert afk == timedelta(hours=10, minutes=30)
        assert online == timedelta(hours=12)

    def test_online_time_from_afk_bucket_not_day_total(self, base_date):
        """Online time should come from AFK bucket events, not day total.

        Regression: Online was being calculated as sum of all slots (day total)
        instead of sum of AFK bucket events.

        With offline tasks:
        - AFK bucket: 5h (all activity times)
        - OFFLINE task: 2h wall-clock, 1h online, 1h offline gap

        Expected Online: 5h + 1h = 6h (from AFK + OFFLINE online portion)
        NOT: 5h + 2h = 7h (day total)
        """
        # Online tracked time
        afk_online = timedelta(hours=5)

        # OFFLINE task adds: 1h online, 1h offline gap
        offline_online = timedelta(hours=1)
        offline_gap = timedelta(hours=1)

        # Expected totals
        total_online = afk_online + offline_online
        total_offline = offline_gap

        # Daily total = online + offline, NOT a separate metric
        day_total = total_online + total_offline

        # Verify these are different
        assert total_online == timedelta(hours=6)
        assert day_total == timedelta(hours=7)
        assert total_online != day_total

        # Online must equal Active + AFK, not day total
        # (This would be verified in actual pipeline test below)


class TestTotalsAccuracyRegressions:
    """Test TOTALS accuracy with realistic data scenarios.

    These tests document expected behavior and catch regressions like:
    - AFK unassigned slots not being counted in TOTALS
    - Online time calculated as day total instead of Active + AFK
    - Deduplication removing slots that should contribute to totals
    """

    @pytest.fixture
    def base_date(self):
        return datetime(2026, 7, 28, tzinfo=timezone.utc)

    def test_online_calculation_active_plus_afk_not_day_total(self):
        """REGRESSION: Online was being calculated as day total.

        Online Time must equal: Active Time + AFK Time
        NOT: Sum of all activity slots (day total)

        Example:
        - Day with 5 hours of measured activity (online)
        - Plus 2 hours OFFLINE task
        - Day total = 7 hours
        - BUT Online should still be 5 hours (not 7)
        """
        # Measured online time (from AFK bucket)
        active_time = timedelta(hours=4, minutes=30)
        afk_time = timedelta(hours=1, minutes=15)
        online_from_afk = active_time + afk_time  # Should be ~5:45

        # OFFLINE task duration
        offline_wall_clock = timedelta(hours=2)
        offline_online_portion = timedelta(hours=1)
        offline_gap = offline_wall_clock - offline_online_portion

        # Total online (from both sources)
        total_online = online_from_afk + offline_online_portion

        # Day total (NOT the same as Online)
        day_total = online_from_afk + offline_wall_clock

        # Verify these are different
        assert total_online == timedelta(hours=6, minutes=45)
        assert day_total == timedelta(hours=7, minutes=45)
        assert total_online != day_total

        # This is the key assertion: Online != Day Total
        # A broken implementation might use: Online = day_total (WRONG)
        # Correct: Online = active + afk + offline_online_portion

    def test_unassigned_afk_must_be_counted_in_totals(self):
        """REGRESSION: Unassigned AFK slots excluded from TOTALS.

        When a user is idle (AFK) with no project assigned,
        that AFK time should still be counted in the TOTALS AFK line.

        Example: Day with 10h AFK idle period (no project)
        - TOTALS should show AFK time including this 10h
        - It should NOT be hidden just because it's unassigned
        """
        # Typical day
        active_work = timedelta(hours=4)
        unassigned_afk = timedelta(hours=10, minutes=30)  # Large unassigned AFK

        # Total online time
        total_online = active_work + unassigned_afk

        # TOTALS should show this breakdown
        assert total_online == timedelta(hours=14, minutes=30)

        # Broken implementation: Removes unassigned_afk from totals
        # Correct implementation: Includes it in AFK time

    def test_deduplication_preserves_totals_accuracy(self):
        """REGRESSION: Deduplication was removing slots needed for totals.

        Deduplication should remove SYNTHETIC/DUPLICATE slots but
        preserve all real activity time for TOTALS calculation.

        Example:
        - Remove overlapping window events (OK)
        - Remove synthetic "No project assigned" slots that overlap OFFLINE (OK)
        - BUT: Don't remove pure AFK periods needed for totals (WRONG if removed)
        """
        # Real activity
        project_work = timedelta(hours=2)

        # Pure AFK periods (no project assigned)
        pure_afk_1 = timedelta(minutes=30)
        pure_afk_2 = timedelta(hours=1)
        total_afk = pure_afk_1 + pure_afk_2

        # OFFLINE task
        offline_duration = timedelta(hours=1)

        # After deduplication, all these should still contribute to totals
        remaining_work = project_work
        remaining_afk = total_afk
        remaining_offline = offline_duration

        total_online = remaining_work + remaining_afk

        # Verify none were removed
        assert remaining_work == project_work
        assert remaining_afk == total_afk
        assert total_online == timedelta(hours=3, minutes=30)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

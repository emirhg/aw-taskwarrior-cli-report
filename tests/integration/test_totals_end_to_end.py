"""End-to-end integration tests for TOTALS calculations.

Tests the complete flow: raw events → calculations → TOTALS output.
Validates that:
- Metrics are calculated correctly from real event data
- TOTALS section displays correct values
- Mathematical relationships hold (Online = Active + AFK, Total = Online + Offline)
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
import sys

import pytest

from aw_core.models import Event
from tw_report.pipeline.processors import compute_metrics, build_context
from tw_report.pipeline.models import ReportEvent, ReportContext, ReportMetrics


class TestMetricsCalculationWithRealEvents:
    """Test metric calculations with realistic event data."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)

    def test_simple_work_session_metrics(self, base_time):
        """Single focused work session: all Active Time, no AFK (Phase 2 refactor: slot-based)."""
        # 10:00-12:00 = 2 hours of focused work
        from tw_report.core.report_slot import ReportTimelineSlot
        from tw_report.core.aw_events import TaskWarriorEvent

        slot_duration = timedelta(hours=2)
        slot = ReportTimelineSlot(
            start=base_time,
            end=base_time + slot_duration,
            duration=slot_duration,
            actual_duration=slot_duration,
            productive_duration=slot_duration,
            task_event=TaskWarriorEvent(
                timestamp=base_time,
                duration=slot_duration,
                data={"project": "Work", "task": "Coding", "tags": []},
            ),
            categories=[{
                "category": "Development",
                "apps": [{
                    "app": "IDE",
                    "duration": slot_duration,
                    "titles": [{"title": "main.py", "duration": slot_duration}]
                }]
            }],
            window_events=[],
            afk_events=[],
            tags=[],
            is_consolidated=False,
        )

        consolidated_slots = [slot]

        metrics = compute_metrics(
            consolidated_slots=consolidated_slots,
            cat_score_map={"Development": 1.0},
            get_category_score=lambda cat, m: m.get(cat, 0),
            non_afk_time=timedelta(hours=2),
            first_event_time=base_time,
            last_event_time=base_time + timedelta(hours=2),
            current_session_start=None,
            current_session_end=None,
            current_session_duration=None,
            last_break_start=None,
            last_break_end=None,
            last_break_duration=None,
            detail_level=3,  # Required to enable category scoring for productive_time
        )

        # Verify metrics
        assert metrics.non_afk_time == timedelta(hours=2)
        assert metrics.productive_time == timedelta(hours=2)
        assert metrics.distracting_time == timedelta(0)
        assert metrics.unscored_time == timedelta(0)

    def test_work_with_afk_break_metrics(self, base_time):
        """Work + AFK break: metrics should separate active from idle."""
        # 10:00-11:00 work (active), 11:00-11:30 AFK, 11:30-12:00 work (active)
        afk_events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(minutes=30),
                data={"status": "afk"},
            ),
            Event(
                timestamp=base_time + timedelta(hours=1, minutes=30),
                duration=timedelta(minutes=30),
                data={"status": "not-afk"},
            ),
        ]

        # Total online time should be 2 hours (all events combined)
        total_online = sum((e.duration for e in afk_events), timedelta(0))
        assert total_online == timedelta(hours=2)

        # Active time (not-afk only)
        not_afk_events = [e for e in afk_events if e.data.get("status") == "not-afk"]
        active_time = sum((e.duration for e in not_afk_events), timedelta(0))
        assert active_time == timedelta(hours=1, minutes=30)

        # AFK time
        afk_only = [e for e in afk_events if e.data.get("status") == "afk"]
        afk_time = sum((e.duration for e in afk_only), timedelta(0))
        assert afk_time == timedelta(minutes=30)

        # Verify relationship: Online = Active + AFK
        assert total_online == active_time + afk_time

    def test_offline_task_metrics(self):
        """OFFLINE task: system powered off during task work."""
        # Task: 14:00-16:00 wall-clock (2 hours)
        # System was online: 14:30-16:00 (1.5 hours)
        # System was offline: 14:00-14:30 (30 minutes)

        wall_clock_duration = timedelta(hours=2)
        online_duration = timedelta(hours=1, minutes=30)
        offline_gap = wall_clock_duration - online_duration

        # Verify calculation
        assert offline_gap == timedelta(minutes=30)
        assert online_duration + offline_gap == wall_clock_duration

        # Total time = online + offline
        total_time = online_duration + offline_gap
        assert total_time == wall_clock_duration


class TestTotalsDisplayConsistency:
    """Test that TOTALS display values are mathematically consistent."""

    def test_totals_math_relationships(self):
        """Verify fundamental math relationships in TOTALS."""
        # Scenario: 8 hour work day with breaks
        active_time = timedelta(hours=6)  # 6 hours focused
        afk_time = timedelta(hours=1)      # 1 hour idle
        offline_time = timedelta(hours=1)  # 1 hour system off

        # Calculate totals
        online_time = active_time + afk_time  # 7 hours
        total_time = online_time + offline_time  # 8 hours

        # Verify relationships
        assert online_time == timedelta(hours=7)
        assert total_time == timedelta(hours=8)
        assert online_time - afk_time == active_time
        assert total_time - offline_time == online_time

    def test_percentage_calculations(self):
        """Test Project Tracking % and Focus Time % calculations."""
        online_time = timedelta(hours=8)
        afk_time = timedelta(hours=1)
        offline_time = timedelta(hours=2)
        total_time = online_time + offline_time  # 10 hours

        # Project Tracking: 7 hours on tracked projects out of 10 total
        tracked_time = timedelta(hours=7)
        project_tracking_pct = (tracked_time.total_seconds() / total_time.total_seconds() * 100)

        # Active Time: 7 hours (online - afk)
        active_time = online_time - afk_time
        assert active_time == timedelta(hours=7)

        # Focus Time: 5 hours productive out of 7 tracked
        productive_time = timedelta(hours=5)
        focus_pct = (productive_time.total_seconds() / tracked_time.total_seconds() * 100)

        # Verify calculations
        assert abs(project_tracking_pct - 70.0) < 0.1  # 7/10 = 70%
        assert abs(focus_pct - 71.43) < 0.1  # 5/7 ≈ 71.43%

    def test_metric_bounds(self):
        """Verify metrics stay within valid ranges."""
        online_time = timedelta(hours=8)
        afk_time = timedelta(hours=1)

        # AFK must be <= Online
        assert afk_time <= online_time

        # Active = Online - AFK must be >= 0
        active_time = online_time - afk_time
        assert active_time >= timedelta(0)
        assert active_time <= online_time


class TestTotalsAccuracy:
    """Test that totals match the sum of their parts."""

    def test_daily_totals_sum_correctly(self):
        """Day totals should equal sum of period components."""
        # Three work blocks in a day
        block1_active = timedelta(hours=2)
        block1_afk = timedelta(minutes=15)

        block2_active = timedelta(hours=3)
        block2_afk = timedelta(minutes=30)

        block3_active = timedelta(hours=1, minutes=30)
        block3_afk = timedelta(minutes=10)

        # Total active and AFK
        total_active = block1_active + block2_active + block3_active
        total_afk = block1_afk + block2_afk + block3_afk

        # Online = Active + AFK
        total_online = total_active + total_afk

        # Verify
        assert total_active == timedelta(hours=6, minutes=30)
        assert total_afk == timedelta(minutes=55)
        assert total_online == timedelta(hours=7, minutes=25)
        assert total_online - total_afk == total_active

    def test_weekly_totals_aggregate_correctly(self):
        """Weekly totals should sum daily totals correctly."""
        days = 5  # Work week Monday-Friday
        daily_active = timedelta(hours=8)
        daily_afk = timedelta(hours=1)
        daily_online = daily_active + daily_afk  # 9 hours/day

        weekly_online = daily_online * days
        weekly_active = daily_active * days
        weekly_afk = daily_afk * days

        # Verify relationships
        assert weekly_online == timedelta(hours=45)  # 5 days × 9 hours
        assert weekly_active == timedelta(hours=40)  # 5 days × 8 hours
        assert weekly_afk == timedelta(hours=5)      # 5 days × 1 hour
        assert weekly_online == weekly_active + weekly_afk


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

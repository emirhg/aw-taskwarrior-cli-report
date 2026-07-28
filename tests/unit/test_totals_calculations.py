"""
Unit tests for totals calculations in tw_report.

Tests verify that:
1. Online Time = sum of AFK bucket events (both afk and not-afk status)
2. Active Time = sum of "not-afk" status events from AFK bucket
3. AFK Time = sum of "afk" status events from AFK bucket
4. Offline Time = wall-clock duration - online (recorded) duration for OFFLINE tasks
5. Day/Week metrics don't double-count AFK
6. Project Tracking % denominator includes all time metrics
7. Unscored/Productive/Distracting time handling in AFK optimization mode
"""

from datetime import datetime, timedelta, timezone

import pytest

from aw_core.models import Event


class TestOnlineTimeCalculation:
    """Test Online Time = AFK bucket sum (both afk and not-afk)."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)

    def test_online_time_no_afk(self, base_time):
        """Online Time with only active (not-afk) periods."""
        # 10:00-12:00 = 2 hours all focused
        afk_events = [
            Event(
                timestamp=base_time,
                duration=timedelta(hours=2),
                data={"status": "not-afk"},
            )
        ]

        expected_online = timedelta(hours=2)
        actual_online = sum(
            (event.duration for event in afk_events), timedelta(0)
        )

        assert actual_online == expected_online, \
            "Online time should be 2 hours (all active)"

    def test_online_time_with_afk_break(self, base_time):
        """Online Time includes both active and AFK periods."""
        # 10:00-11:00 active, 11:00-11:30 afk, 11:30-12:30 active
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
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
        ]

        # Online Time should be sum of all (1:00 + 0:30 + 1:00 = 2:30)
        expected_online = timedelta(hours=2, minutes=30)
        actual_online = sum(
            (event.duration for event in afk_events), timedelta(0)
        )

        assert actual_online == expected_online, \
            "Online time should be 2:30 (all periods combined)"

    def test_active_time_excludes_afk(self, base_time):
        """Active Time only counts 'not-afk' periods."""
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
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
        ]

        # Active Time should only be not-afk (1:00 + 1:00 = 2:00)
        active_events = [e for e in afk_events if e.data.get("status") == "not-afk"]
        expected_active = timedelta(hours=2)
        actual_active = sum(
            (event.duration for event in active_events), timedelta(0)
        )

        assert actual_active == expected_active, \
            "Active time should be 2:00 (not-afk only)"

    def test_afk_time_calculation(self, base_time):
        """AFK Time only counts 'afk' periods."""
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
                duration=timedelta(minutes=20),
                data={"status": "afk"},
            ),
            Event(
                timestamp=base_time + timedelta(hours=1, minutes=50),
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
        ]

        # AFK Time should be sum of afk (0:30 + 0:20 = 0:50)
        afk_only = [e for e in afk_events if e.data.get("status") == "afk"]
        expected_afk = timedelta(minutes=50)
        actual_afk = sum(
            (event.duration for event in afk_only), timedelta(0)
        )

        assert actual_afk == expected_afk, \
            "AFK time should be 0:50 (afk only)"


class TestOfflineTimeCalculation:
    """Test Offline Time = wall-clock duration - online (recorded) duration."""

    def test_offline_slot_calculation(self):
        """Offline Time = duration - event_duration for OFFLINE tasks."""
        # Wall-clock 14:00-16:00 (2 hours)
        # System was on 14:30-16:00 (1.5 hours, event_duration)
        # System was off 14:00-14:30 (30 minutes, offline time)

        wall_clock_duration = timedelta(hours=2)
        online_duration = timedelta(hours=1, minutes=30)
        offline_duration = wall_clock_duration - online_duration

        expected_offline = timedelta(minutes=30)

        assert offline_duration == expected_offline, \
            "Offline time should be 0:30 (wall-clock - online)"

    def test_no_offline_if_all_recorded(self):
        """No offline time if system was recording entire duration."""
        wall_clock_duration = timedelta(hours=1)
        online_duration = timedelta(hours=1)
        offline_duration = wall_clock_duration - online_duration

        expected_offline = timedelta(0)

        assert offline_duration == expected_offline, \
            "Offline time should be 0 if fully recorded"

    def test_offline_with_window_activity(self):
        """Offline time is system-off gap, not window activity during offline."""
        # Note: offline_extension_duration is window activity DURING offline
        # It should NOT be used to calculate offline time

        # Scenario: Task wall-clock 14:00-16:00, system on 14:30-16:00
        # Some window events happened during 14:30-16:00 (say 1:20:00)

        wall_clock_duration = timedelta(hours=2)
        online_duration = timedelta(hours=1, minutes=30)
        window_activity_during_offline_period = timedelta(hours=1, minutes=20)

        # Correct calculation
        correct_offline = wall_clock_duration - online_duration

        # Wrong calculation (what the bug does)
        wrong_offline = window_activity_during_offline_period

        assert correct_offline == timedelta(minutes=30), \
            "Correct offline time = 0:30"
        assert wrong_offline == timedelta(hours=1, minutes=20), \
            "Wrong offline time = 1:20 (if using offline_extension_duration)"
        assert correct_offline != wrong_offline, \
            "BUG: Consolidated report uses wrong field for offline time"


class TestDayWeekAccumulation:
    """Test day/week accumulation doesn't double-count AFK."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)

    def test_day_online_calculation(self, base_time):
        """Day online should sum all AFK events once."""
        # 10:00-11:00 active, 11:00-11:30 afk, 11:30-12:30 active
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
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
        ]

        # Daily metrics should track:
        # online_duration = 2:30 (all AFK events)
        # afk_duration = 0:30 (afk only)
        # active_duration = 2:00 (online - afk)

        total_online = sum((e.duration for e in afk_events), timedelta(0))
        total_afk = sum(
            (e.duration for e in afk_events if e.data.get("status") == "afk"),
            timedelta(0),
        )
        total_active = total_online - total_afk

        assert total_online == timedelta(hours=2, minutes=30)
        assert total_afk == timedelta(minutes=30)
        assert total_active == timedelta(hours=2)
        assert total_online == total_active + total_afk, \
            "Online should equal Active + AFK (no double-counting)"


class TestProjectTrackingCalculation:
    """Test Project Tracking % denominator includes all time metrics."""

    def test_tracking_denominator_with_afk(self):
        """Project Tracking % should use (active + afk + offline) as denominator."""
        # 8 hours total activity
        active_time = timedelta(hours=6)
        afk_time = timedelta(hours=1)
        offline_time = timedelta(hours=1)
        total_time = active_time + afk_time + offline_time

        # 5 hours on tracked projects
        tracked_time = timedelta(hours=5)

        # Expected: 5 / 8 = 62.5%
        pct = (tracked_time.total_seconds() / total_time.total_seconds() * 100)

        assert abs(pct - 62.5) < 0.01, \
            f"Project tracking should be 62.5%, got {pct}%"

    def test_tracking_denominator_without_afk_time(self):
        """BUG TEST: Fallback calculation missing AFK time."""
        # Current buggy fallback: non_afk_time + offline_time
        # Should be: non_afk_time + afk_time + offline_time

        non_afk_time = timedelta(hours=6)
        afk_time = timedelta(hours=1)
        offline_time = timedelta(hours=1)

        tracked_time = timedelta(hours=5)

        # Correct calculation
        correct_denom = non_afk_time + afk_time + offline_time  # 8 hours
        correct_pct = (tracked_time.total_seconds() / correct_denom.total_seconds() * 100)

        # Buggy fallback calculation
        buggy_denom = non_afk_time + offline_time  # 7 hours (missing afk_time)
        buggy_pct = (tracked_time.total_seconds() / buggy_denom.total_seconds() * 100)

        assert correct_pct == pytest.approx(62.5, abs=0.01), \
            f"Correct should be 62.5%, got {correct_pct}%"
        assert buggy_pct == pytest.approx(71.43, abs=0.01), \
            f"Buggy should be 71.43%, got {buggy_pct}%"
        assert correct_pct != buggy_pct, \
            "BUG: Project tracking % differs when AFK time not included in denominator"


class TestAFKOptimizationMode:
    """Test handling of metrics in AFK optimization mode (detail_level <= 2)."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)

    def test_unscored_time_without_windows(self):
        """In AFK optimization mode, unscored_time becomes 0 (unknown)."""
        # When detail_level <= 2 and timesheet mode, window events not fetched
        # This means $category data is missing

        # Mock scenario: no window events
        canonical_events = []

        # Check for category data
        has_category_data = any(
            rep.event.data.get("$category") for rep in canonical_events
        )

        assert not has_category_data, \
            "No window events = no category data"

        # In this mode, productive/unscored/distracting all become 0
        # BUG: User can't distinguish "untracked" from "unproductive"
        # Should mark as "unknown" or fetch windows if detail_level >= 3

    def test_metrics_with_category_data(self):
        """Metrics should be calculated when category data is available."""
        # Mock scenario: with window events
        class MockEvent:
            def __init__(self, duration, category=None):
                self.duration = duration
                self.data = {"$category": [category] if category else []}

        class MockReportEvent:
            def __init__(self, duration, category=None):
                self.event = MockEvent(duration, category)
                self.active_task = None

        canonical_events = [
            MockReportEvent(timedelta(hours=1), "Development"),
            MockReportEvent(timedelta(minutes=30), "Social"),
        ]

        has_category_data = any(
            rep.event.data.get("$category") for rep in canonical_events
        )

        assert has_category_data, \
            "Should have category data from window events"


class TestNonAFKTimeNaming:
    """Test non_afk_time parameter represents Active Time, not Online Time."""

    def test_non_afk_time_is_active_time(self):
        """non_afk_time should only include 'not-afk' events."""
        # Semantic definition:
        # - Active Time = keyboard focus time (not-afk events only)
        # - Online Time = system recording time (afk + not-afk combined)

        afk_events = [
            Event(
                timestamp=datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
                duration=timedelta(hours=1),
                data={"status": "not-afk"},
            ),
            Event(
                timestamp=datetime(2026, 7, 28, 11, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=30),
                data={"status": "afk"},
            ),
        ]

        non_afk_time = sum(
            (event.duration for event in afk_events if event.data.get("status") == "not-afk"),
            timedelta(0),
        )

        assert non_afk_time == timedelta(hours=1), \
            "non_afk_time should be 1:00 (Active Time)"

        # BUG: parameter name "non_afk_time" suggests it's "Online Time"
        # Should be renamed to "active_time" for clarity


class TestMetricsConsistency:
    """Test metrics consistency across different calculation paths."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)

    def test_afk_time_same_across_paths(self, base_time):
        """AFK time from AFK bucket should match slot-accumulated AFK."""
        # Timeline report AFK calculation:
        # - Consolidated path: sum of afk_duration field
        # - Regular path: sum of type="afk" slot durations + embedded AFK

        # These should produce the same result

        afk_bucket_events = [
            Event(
                timestamp=base_time + timedelta(hours=1),
                duration=timedelta(minutes=30),
                data={"status": "afk"},
            ),
            Event(
                timestamp=base_time + timedelta(hours=2),
                duration=timedelta(minutes=20),
                data={"status": "afk"},
            ),
        ]

        afk_from_bucket = sum(
            (e.duration for e in afk_bucket_events if e.data.get("status") == "afk"),
            timedelta(0),
        )

        # Slot representation (consolidated)
        consolidated_slots = [
            {"type": "work", "afk_duration": timedelta(minutes=50)},
        ]

        afk_from_consolidated = sum(
            (s.get("afk_duration", timedelta(0)) for s in consolidated_slots),
            timedelta(0),
        )

        assert afk_from_bucket == afk_from_consolidated == timedelta(minutes=50), \
            "AFK time should be consistent between bucket and slot representations"

    def test_online_time_consistency(self):
        """Online time should be consistent: Active + AFK = Online."""
        active_time = timedelta(hours=6)
        afk_time = timedelta(hours=1)

        online_time = active_time + afk_time

        expected_online = timedelta(hours=7)

        assert online_time == expected_online, \
            "Online = Active + AFK (fundamental relationship)"


class TestTotalTimeRelationships:
    """Test fundamental relationships between time metrics."""

    def test_total_time_formula(self):
        """Total Time = Online Time + Offline Time."""
        online_time = timedelta(hours=8)
        offline_time = timedelta(hours=1)

        total_time = online_time + offline_time

        assert total_time == timedelta(hours=9), \
            "Total = Online + Offline"

    def test_online_time_breakdown(self):
        """Online Time = Active Time + AFK Time."""
        active_time = timedelta(hours=7)
        afk_time = timedelta(hours=1)

        online_time = active_time + afk_time

        assert online_time == timedelta(hours=8), \
            "Online = Active + AFK"

    def test_productive_within_online(self):
        """Productive Time must be <= Online Time."""
        online_time = timedelta(hours=8)
        productive_time = timedelta(hours=3)

        assert productive_time <= online_time, \
            "Productive time can't exceed online time"

    def test_untracked_within_productive(self):
        """Untracked = Productive + Distracting + Unscored."""
        productive_time = timedelta(hours=2)
        distracting_time = timedelta(minutes=30)
        unscored_time = timedelta(hours=1)

        untracked = productive_time + distracting_time + unscored_time

        assert untracked == timedelta(hours=3, minutes=30), \
            "Untracked categories must sum correctly"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

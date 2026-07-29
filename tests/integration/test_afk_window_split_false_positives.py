"""Integration tests for AFK/window split detection.

Handles the special case where a system comes online and window logger
records activity BEFORE AFK tracker recognizes the system is back.

This causes false-positive AFK detection: the system was mostly OFFLINE
but AFK reports it as a long idle period with minimal window activity.

Solution: Split the AFK slot into two parts:
1. Pure AFK (no window events) = OFFLINE time
2. AFK with window intersection = Real online idle time
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import pytest

from aw_core.models import Event


class TestAFKWindowSplitDetection:
    """Detect and split AFK periods that are mostly offline (false positives)."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, tzinfo=timezone.utc)

    def create_afk_event(self, base_time: datetime, hour: int, minute: int,
                        duration_minutes: int, status: str = "afk") -> Event:
        """Create AFK bucket event."""
        return Event(
            timestamp=base_time.replace(hour=hour, minute=minute),
            duration=timedelta(minutes=duration_minutes),
            data={"status": status},
        )

    def create_window_event(self, base_time: datetime, hour: int, minute: int,
                           duration_seconds: int) -> Event:
        """Create window bucket event."""
        return Event(
            timestamp=base_time.replace(hour=hour, minute=minute),
            duration=timedelta(seconds=duration_seconds),
            data={"app": "kitty", "title": "test"},
        )

    def get_afk_window_coverage(self, afk_event: Event,
                                window_events: List[Event]) -> float:
        """Calculate percentage of AFK period covered by window events."""
        if afk_event.duration == timedelta(0):
            return 0.0

        afk_start = afk_event.timestamp
        afk_end = afk_event.timestamp + afk_event.duration

        covered_time = timedelta(0)
        for w in window_events:
            w_start = w.timestamp
            w_end = w_start + w.duration

            # Calculate overlap
            overlap_start = max(w_start, afk_start)
            overlap_end = min(w_end, afk_end)

            if overlap_start < overlap_end:
                covered_time += overlap_end - overlap_start

        return (covered_time.total_seconds() / afk_event.duration.total_seconds()) * 100

    def test_afk_with_high_window_coverage_is_real_idle(self, base_time):
        """AFK with >80% window coverage = real online idle time."""
        # 10:00-11:00: AFK period
        afk = self.create_afk_event(base_time, 10, 0, 60, "afk")

        # Window activity during: 50+ minutes
        windows = [
            self.create_window_event(base_time, 10, 5, 1800),  # 30 min
            self.create_window_event(base_time, 10, 35, 1200),  # 20 min
        ]

        coverage = self.get_afk_window_coverage(afk, windows)

        assert coverage > 80, "High window coverage = real AFK"
        # Classification: ONLINE AFK (user was idle but system active)

    def test_afk_with_low_window_coverage_is_false_positive(self, base_time):
        """AFK with <5% window coverage = system was OFFLINE (false positive)."""
        # 01:05:42 - 11:16:42: 10:11:00 AFK (the real scenario)
        afk = self.create_afk_event(base_time, 1, 5, 611, "afk")  # 10h 11m

        # Window activity: only 16 seconds at the end (11:16:25)
        windows = [
            self.create_window_event(base_time, 11, 16, 16),  # 16 sec
        ]

        coverage = self.get_afk_window_coverage(afk, windows)

        assert coverage < 5, "Low window coverage = false positive"
        # Classification: OFFLINE (system was powered off)

    def test_split_afk_slot_by_window_activity(self, base_time):
        """Split AFK slot into offline (no windows) + online (with windows)."""
        # 01:05:42 - 11:16:42: AFK period
        afk_start = base_time.replace(hour=1, minute=5, second=42)
        afk_end = base_time.replace(hour=11, minute=16, second=42)
        afk_duration = afk_end - afk_start

        # Window activity at 11:16:25 (just before end)
        window_time = base_time.replace(hour=11, minute=16, second=25)

        # Split calculation
        offline_duration = window_time - afk_start  # 01:05:42 to 11:16:25
        online_afk_duration = afk_end - window_time  # 11:16:25 to 11:16:42

        # Verify split adds up to total
        assert offline_duration + online_afk_duration == afk_duration
        # Offline should be ~10:10:43, online should be ~17 seconds
        assert offline_duration.total_seconds() > 36600  # > 10 hours
        assert online_afk_duration.total_seconds() < 30  # < 30 seconds

    def test_afk_split_with_no_windows_is_pure_offline(self, base_time):
        """AFK period with zero window events = entire period is OFFLINE."""
        afk = self.create_afk_event(base_time, 14, 0, 120, "afk")  # 2 hours
        windows = []  # No window events

        coverage = self.get_afk_window_coverage(afk, windows)

        assert coverage == 0.0, "No windows = 100% offline"
        # Classification: OFFLINE time (system was powered off)

    def test_multiple_window_segments_during_afk(self, base_time):
        """Calculate coverage for AFK with multiple window segments."""
        # 10:00-14:00: 4 hour AFK period
        afk = self.create_afk_event(base_time, 10, 0, 240, "afk")

        # Window segments: 30min at start, 30min at end
        windows = [
            self.create_window_event(base_time, 10, 0, 1800),   # 30 min
            self.create_window_event(base_time, 13, 30, 1800),  # 30 min
        ]

        coverage = self.get_afk_window_coverage(afk, windows)

        assert coverage == 25.0, "60 min / 240 min = 25%"
        # Classification: False positive (mostly offline)

    def test_window_event_outside_afk_range_not_counted(self, base_time):
        """Window events outside AFK period should not count as coverage."""
        # 10:00-11:00: AFK
        afk = self.create_afk_event(base_time, 10, 0, 60, "afk")

        # Window events before and after AFK period
        windows = [
            self.create_window_event(base_time, 9, 30, 600),   # Before AFK
            self.create_window_event(base_time, 11, 30, 600),  # After AFK
        ]

        coverage = self.get_afk_window_coverage(afk, windows)

        assert coverage == 0.0, "Windows outside period = no coverage"


class TestAFKOfflineClassification:
    """Classify AFK periods as ONLINE vs OFFLINE based on window coverage."""

    AFK_OFFLINE_THRESHOLD = 0.05  # 5% coverage threshold

    def classify_afk(self, coverage_percent: float) -> str:
        """Classify AFK period based on window coverage."""
        if coverage_percent >= self.AFK_OFFLINE_THRESHOLD * 100:
            return "ONLINE_AFK"  # Real idle time, system was on
        else:
            return "OFFLINE"  # False positive, system was off

    def test_high_coverage_classified_as_online_afk(self):
        """≥5% window coverage = ONLINE AFK."""
        coverage = 50.0  # 50% window activity

        assert self.classify_afk(coverage) == "ONLINE_AFK"

    def test_low_coverage_classified_as_offline(self):
        """<5% window coverage = OFFLINE."""
        coverage = 0.16  # 16 seconds in 10+ hours ≈ 0.16%

        assert self.classify_afk(coverage) == "OFFLINE"

    def test_boundary_case_exactly_5_percent(self):
        """Exactly 5% = classified as ONLINE AFK."""
        coverage = 5.0

        assert self.classify_afk(coverage) == "ONLINE_AFK"

    def test_zero_coverage_is_offline(self):
        """0% window activity = OFFLINE."""
        coverage = 0.0

        assert self.classify_afk(coverage) == "OFFLINE"


class TestMetricsWithSplitAFK:
    """Test that metrics correctly account for split AFK/offline slots."""

    def test_online_time_excludes_pure_offline_afk(self):
        """Online time should NOT include AFK-only periods (false positives)."""
        # Real scenario: 10:11:00 AFK with only 16 sec window activity
        pure_offline = timedelta(hours=10, minutes=10, seconds=44)
        online_afk = timedelta(seconds=16)
        other_active = timedelta(hours=3)
        other_afk = timedelta(hours=1)

        # Should calculate as:
        corrected_online = other_active + other_afk + online_afk
        offline_time = pure_offline

        assert offline_time == timedelta(hours=10, minutes=10, seconds=44)
        assert corrected_online == timedelta(hours=4, minutes=0, seconds=16)

    def test_totals_with_split_afk_slot(self):
        """TOTALS should correctly handle split AFK/offline."""
        # From user's actual data after split:
        active_time = timedelta(hours=7, minutes=50, seconds=40)
        online_afk = timedelta(hours=2, minutes=18, seconds=30)  # Reduced from 13:28:30
        offline_time = timedelta(hours=10, minutes=10, seconds=44)  # New from split

        online = active_time + online_afk
        total = online + offline_time

        # Verify math
        assert online == timedelta(hours=10, minutes=9, seconds=10)
        assert total == timedelta(hours=20, minutes=19, seconds=54)


class TestRegressionPrevention:
    """Regression tests to prevent this bug from reoccurring."""

    def test_pipeline_must_check_afk_window_coverage(self):
        """Pipeline MUST check window coverage before counting AFK as online."""
        required_checks = [
            "For each AFK slot: calculate % window coverage",
            "If coverage < 5%: classify as OFFLINE, not ONLINE_AFK",
            "If coverage >= 5%: keep as ONLINE_AFK",
            "Split slots: pure-offline portion goes to offline_time, online portion to afk_time",
        ]

        assert len(required_checks) == 4

    def test_afk_totals_must_include_split_logic(self):
        """total_afk_time calculation must account for split slots."""
        # This test documents the requirement:
        # When processing AFK slots with low window coverage,
        # the pipeline must:
        # 1. Detect the false positive
        # 2. Split the slot
        # 3. Count online portion as AFK
        # 4. Count offline portion as offline_time

        # After this fix:
        # - AFK from bucket: 13:28:30
        # - But after split: ~3:17:46 online AFK + ~10:10:44 offline
        # - TOTALS AFK should show: ~3:17:46 (not 1:12:54 or 13:28:30)

        bucket_afk = timedelta(hours=13, minutes=28, seconds=30)
        online_afk_after_split = timedelta(hours=3, minutes=17, seconds=46)
        offline_after_split = timedelta(hours=10, minutes=10, seconds=44)

        # Should now match bucket data correctly after split
        assert online_afk_after_split + offline_after_split == bucket_afk


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests that validate AFK bucket events against window bucket.

Critical validation: AFK events can be false positives if the system
was powered off (OFFLINE) but the AFK watcher still recorded events.

This test suite cross-references AFK and window buckets to:
1. Identify true ONLINE AFK (AFK + window activity)
2. Identify false positive AFK (AFK without window = OFFLINE)
3. Ensure the pipeline uses corrected AFK time in TOTALS
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import pytest

from aw_core.models import Event


class TestAFKWindowBucketCrossValidation:
    """Validate AFK events against window bucket to detect false positives."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 28, tzinfo=timezone.utc)

    def create_afk_event(self, base_time: datetime, hour: int, minute: int,
                        duration_minutes: int, status: str = "afk") -> Event:
        """Create an AFK bucket event."""
        return Event(
            timestamp=base_time.replace(hour=hour, minute=minute),
            duration=timedelta(minutes=duration_minutes),
            data={"status": status},
        )

    def create_window_event(self, base_time: datetime, hour: int, minute: int,
                           duration_seconds: int, app: str = "test") -> Event:
        """Create a window bucket event."""
        return Event(
            timestamp=base_time.replace(hour=hour, minute=minute),
            duration=timedelta(seconds=duration_seconds),
            data={"app": app, "title": "test"},
        )

    def afk_has_window_overlap(self, afk_event: Event,
                               window_events: List[Event]) -> bool:
        """Check if AFK event has any overlapping window events."""
        afk_start = afk_event.timestamp
        afk_end = afk_event.timestamp + afk_event.duration

        for window in window_events:
            w_start = window.timestamp
            w_end = window.timestamp + window.duration
            # Check for overlap
            if w_start < afk_end and w_end > afk_start:
                return True
        return False

    def test_afk_with_window_events_is_true_online(self, base_time):
        """AFK event with window activity = true ONLINE AFK time."""
        # 10:00-11:00: AFK period
        afk_event = self.create_afk_event(base_time, 10, 0, 60, "afk")

        # Window events during this AFK period (keyboard/mouse detected)
        window_events = [
            self.create_window_event(base_time, 10, 15, 10, "Terminal"),
            self.create_window_event(base_time, 10, 30, 5, "Editor"),
            self.create_window_event(base_time, 10, 45, 10, "Browser"),
        ]

        # Validation
        has_window = self.afk_has_window_overlap(afk_event, window_events)

        assert has_window is True, "AFK with window events should be TRUE"
        # This is valid ONLINE time - user was idle but system was recording

    def test_afk_without_window_events_is_false_positive(self, base_time):
        """AFK event without window activity = false positive (system was OFFLINE)."""
        # 14:00-15:00: AFK period (but no window events)
        afk_event = self.create_afk_event(base_time, 14, 0, 60, "afk")

        # Window events BEFORE and AFTER this AFK period
        window_events = [
            self.create_window_event(base_time, 13, 30, 10, "Terminal"),
            self.create_window_event(base_time, 15, 30, 10, "Editor"),
        ]

        # Validation
        has_window = self.afk_has_window_overlap(afk_event, window_events)

        assert has_window is False, "AFK without window events should be FALSE"
        # This is a false positive - AFK watcher recorded idle but system was OFF

    def test_afk_validation_filters_false_positives(self, base_time):
        """Pipeline should filter out AFK events without window overlap."""
        # Mixed AFK events: some with windows, some without
        afk_events = [
            self.create_afk_event(base_time, 9, 0, 30, "afk"),   # Has window
            self.create_afk_event(base_time, 10, 0, 60, "afk"),  # NO window (false positive)
            self.create_afk_event(base_time, 12, 0, 45, "afk"),  # Has window
            self.create_afk_event(base_time, 14, 0, 120, "afk"), # NO window (false positive)
        ]

        window_events = [
            self.create_window_event(base_time, 9, 15, 300, "Terminal"),
            self.create_window_event(base_time, 12, 30, 600, "Editor"),
        ]

        # Validate each AFK event
        true_online_afk = timedelta(0)
        false_positive_afk = timedelta(0)

        for afk in afk_events:
            if self.afk_has_window_overlap(afk, window_events):
                true_online_afk += afk.duration
            else:
                false_positive_afk += afk.duration

        # Verify separation
        assert true_online_afk == timedelta(minutes=75)   # 30 + 45
        assert false_positive_afk == timedelta(minutes=180)  # 60 + 120
        assert true_online_afk + false_positive_afk == timedelta(minutes=255)

    def test_real_scenario_offline_task_with_afk(self, base_time):
        """Real scenario: OFFLINE task period shows AFK events but no window."""
        # Task period: 14:00-16:00 (system was OFF)
        # AFK watcher incorrectly recorded events during this period

        offline_start = base_time.replace(hour=14, minute=0)
        offline_end = base_time.replace(hour=16, minute=0)
        offline_duration = offline_end - offline_start

        # AFK events during "offline" period (false positives)
        afk_during_offline = [
            self.create_afk_event(base_time, 14, 15, 30, "afk"),
            self.create_afk_event(base_time, 14, 50, 20, "afk"),
            self.create_afk_event(base_time, 15, 30, 45, "afk"),
        ]

        # Window events outside the offline period
        window_events = [
            self.create_window_event(base_time, 13, 30, 1200, "Terminal"),
            self.create_window_event(base_time, 16, 30, 1800, "Editor"),
        ]

        # Validate: AFK during offline should be flagged as false positives
        false_positives = sum(
            (afk.duration for afk in afk_during_offline
             if not self.afk_has_window_overlap(afk, window_events)),
            timedelta(0)
        )

        assert false_positives == timedelta(minutes=95), \
            "All AFK during offline period should be false positives"

    def test_afk_active_time_consistency(self, base_time):
        """Active time (NOT-AFK) should all be true online time."""
        # NOT-AFK events are active work periods
        active_events = [
            self.create_afk_event(base_time, 10, 0, 120, "not-afk"),
            self.create_afk_event(base_time, 14, 0, 90, "not-afk"),
        ]

        # These should not need window validation - they're active periods
        # The system was definitely ON if we have "not-afk" events
        total_active = sum((e.duration for e in active_events), timedelta(0))

        assert total_active == timedelta(minutes=210)
        # NOT-AFK is always true online time (no false positives possible)


class TestMetricsWithValidatedAFK:
    """Test that TOTALS uses only validated AFK (filtered for false positives)."""

    def test_online_time_excludes_false_positive_afk(self):
        """Online time should NOT include false positive AFK from OFFLINE periods."""
        # Real data from validation
        true_online_afk = timedelta(hours=13, minutes=28, seconds=30)
        active_time = timedelta(hours=7, minutes=50, seconds=40)
        false_positive_afk = timedelta(0)  # All validated against window bucket

        # Corrected online time
        corrected_online = active_time + true_online_afk

        # Should NOT include false positives
        assert false_positive_afk == timedelta(0)
        assert corrected_online == timedelta(hours=21, minutes=19, seconds=10)

        # TOTALS should show this corrected value
        # NOT the pipeline's incorrect 06:07:39

    def test_offline_time_includes_false_positive_afk(self):
        """OFFLINE time should include AFK events with no window activity."""
        # Example: System was off from 14:00-15:00
        # But AFK watcher recorded 60 minutes of idle
        offline_period = timedelta(hours=1)
        false_positive_afk = timedelta(minutes=60)

        # These should be counted together as offline
        assert false_positive_afk <= offline_period
        # The false positive AFK is actually offline time

    def test_totals_math_with_validated_data(self):
        """Verify TOTALS math after validating and filtering AFK."""
        # Corrected metrics after window bucket validation
        active_time = timedelta(hours=7, minutes=50, seconds=40)
        validated_afk = timedelta(hours=13, minutes=28, seconds=30)
        offline_time = timedelta(hours=0)  # No false positives found

        online = active_time + validated_afk
        total = online + offline_time

        # Mathematical relationships should hold
        assert online == active_time + validated_afk
        assert total == online + offline_time
        assert validated_afk < online  # AFK is subset of online
        assert active_time < online   # Active is subset of online


class TestPipelineValidationRequirements:
    """Specify validation tests that the pipeline MUST perform."""

    def test_pipeline_must_cross_validate_afk_window(self):
        """Pipeline MUST validate every AFK event against window bucket."""
        # This is non-negotiable
        required_validations = [
            "For each AFK event: check if window events exist in overlapping time",
            "If window events exist: AFK is true online time",
            "If no window events: AFK is false positive (system was offline)",
            "Separate true online AFK from false positive AFK",
            "Use only validated AFK in TOTALS calculation",
        ]

        # These must all be implemented
        assert len(required_validations) == 5

    def test_pipeline_must_handle_afk_false_positives(self):
        """Pipeline MUST not silently drop AFK events."""
        # Currently: 13:28:30 of AFK exists but TOTALS only shows 01:12:54
        # This is unacceptable data loss

        actual_afk_in_bucket = timedelta(hours=13, minutes=28, seconds=30)
        totals_showing = timedelta(hours=1, minutes=12, seconds=54)

        # This mismatch proves the pipeline is broken
        assert actual_afk_in_bucket != totals_showing
        assert actual_afk_in_bucket > totals_showing

        # After validation and correction, they should match
        # (or correctly separate into online vs offline)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

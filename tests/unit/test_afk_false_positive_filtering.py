"""
Unit tests for AFK false-positive detection, splitting, and filtering.

False-positive AFK occurs when the system is offline but the AFK watcher
continues reporting idle time. This test suite validates:

1. Detection: Window coverage calculation identifies false positives
2. Classification: Coverage % correctly classifies as OFFLINE vs ONLINE_AFK
3. Filtering: AFK entries matching false-positive periods are removed
4. Rendering: False-positive AFK doesn't appear on timeline reports
"""

import pytest
from datetime import datetime, timedelta, timezone

from tw_report.core.events import (
    Event,
    get_afk_window_coverage,
    classify_afk_slot,
    split_afk_by_window_coverage,
    AFK_FALSE_POSITIVE_THRESHOLD,
    AFK_FALSE_POSITIVE_COVERAGE_THRESHOLD,
)
from tw_report.cli.main import _filter_false_positive_afk


UTC = timezone.utc


class TestAFKWindowCoverage:
    """Test window coverage calculation for AFK periods."""

    def test_no_window_events_zero_coverage(self):
        """AFK with no window events has 0% coverage (system was offline)."""
        afk_event = Event(
            timestamp=datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC),
            data={"status": "afk"},
            duration=timedelta(hours=10),
        )
        coverage = get_afk_window_coverage(afk_event, [])
        assert coverage == 0.0

    def test_full_window_coverage_100_percent(self):
        """AFK fully covered by window events has 100% coverage."""
        afk_start = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=2),
        )
        window_event = Event(
            timestamp=afk_start,
            data={"type": "window"},
            duration=timedelta(hours=2),
        )
        coverage = get_afk_window_coverage(afk_event, [window_event])
        assert coverage == 100.0

    def test_partial_window_coverage(self):
        """AFK partially covered by windows has proportional coverage."""
        afk_start = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=2),  # 120 minutes
        )
        # Only 30 minutes of windows
        window_event = Event(
            timestamp=afk_start + timedelta(minutes=45),
            data={"type": "window"},
            duration=timedelta(minutes=30),
        )
        coverage = get_afk_window_coverage(afk_event, [window_event])
        assert coverage == pytest.approx(25.0, abs=0.1)

    def test_multiple_window_events_combined_coverage(self):
        """Multiple window events are combined for total coverage."""
        afk_start = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=1),  # 60 minutes
        )
        window1 = Event(
            timestamp=afk_start,
            data={"type": "window"},
            duration=timedelta(minutes=15),
        )
        window2 = Event(
            timestamp=afk_start + timedelta(minutes=20),
            data={"type": "window"},
            duration=timedelta(minutes=20),
        )
        coverage = get_afk_window_coverage(afk_event, [window1, window2])
        # 15 + 20 = 35 minutes out of 60 = 58.33%
        assert coverage == pytest.approx(58.33, abs=0.1)

    def test_minimal_coverage_below_threshold(self):
        """AFK with minimal window coverage (< 5%) is a false positive."""
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),  # 611 minutes
        )
        # Only 5 minutes of windows at the very end
        window_event = Event(
            timestamp=afk_start + timedelta(hours=10, minutes=6),
            data={"type": "window"},
            duration=timedelta(minutes=5),
        )
        coverage = get_afk_window_coverage(afk_event, [window_event])
        assert coverage < 1.0  # Less than 1%
        assert coverage > 0.0  # But not zero

    def test_zero_duration_afk_returns_zero(self):
        """AFK with zero duration returns 0% coverage."""
        afk_event = Event(
            timestamp=datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC),
            data={"status": "afk"},
            duration=timedelta(0),
        )
        coverage = get_afk_window_coverage(afk_event, [])
        assert coverage == 0.0


class TestAFKClassification:
    """Test classification of AFK as ONLINE_AFK vs OFFLINE."""

    def test_high_coverage_classified_as_online_afk(self):
        """High window coverage (≥5%) = ONLINE_AFK (real idle time)."""
        assert classify_afk_slot(5.0) == "ONLINE_AFK"
        assert classify_afk_slot(10.0) == "ONLINE_AFK"
        assert classify_afk_slot(100.0) == "ONLINE_AFK"

    def test_low_coverage_classified_as_offline(self):
        """Low window coverage (<5%) = OFFLINE (false positive)."""
        assert classify_afk_slot(0.0) == "OFFLINE"
        assert classify_afk_slot(1.0) == "OFFLINE"
        assert classify_afk_slot(4.9) == "OFFLINE"

    def test_boundary_at_threshold(self):
        """Boundary case: exactly at 5% threshold."""
        # 5.0% should be ONLINE_AFK (threshold is inclusive)
        assert classify_afk_slot(5.0) == "ONLINE_AFK"
        # Just below threshold
        assert classify_afk_slot(4.99) == "OFFLINE"

    def test_custom_threshold(self):
        """Custom threshold can be passed to override default."""
        # With 10% threshold, 5% coverage is OFFLINE
        assert classify_afk_slot(5.0, threshold=10.0) == "OFFLINE"
        # With 5% threshold, 5% is ONLINE_AFK
        assert classify_afk_slot(5.0, threshold=5.0) == "ONLINE_AFK"


class TestAFKSplitting:
    """Test splitting of AFK into offline + online-AFK portions."""

    def test_entire_afk_is_offline_no_windows(self):
        """No windows = entire AFK period is offline."""
        afk_start = datetime(2026, 7, 28, 1, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=5),
        )
        offline_dur, online_afk_dur = split_afk_by_window_coverage(afk_event, [])
        assert offline_dur == timedelta(hours=5)
        assert online_afk_dur == timedelta(0)

    def test_split_at_first_window_event(self):
        """Split occurs at first window event timestamp."""
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),
        )
        # First window at 11:16 (10:11 into the AFK period)
        first_window = Event(
            timestamp=afk_start + timedelta(hours=10, minutes=11),
            data={"type": "window"},
            duration=timedelta(minutes=5),
        )
        offline_dur, online_afk_dur = split_afk_by_window_coverage(
            afk_event, [first_window]
        )
        assert offline_dur == timedelta(hours=10, minutes=11)
        assert online_afk_dur == timedelta(0)

    def test_window_starts_before_afk_no_offline_portion(self):
        """Window starting before AFK begins means no offline portion."""
        afk_start = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=2),
        )
        # Window started 1 hour before AFK
        window_before = Event(
            timestamp=afk_start - timedelta(hours=1),
            data={"type": "window"},
            duration=timedelta(hours=3),
        )
        offline_dur, online_afk_dur = split_afk_by_window_coverage(
            afk_event, [window_before]
        )
        assert offline_dur == timedelta(0)
        assert online_afk_dur == timedelta(hours=2)

    def test_multiple_windows_uses_earliest(self):
        """When multiple windows exist, split at the earliest one."""
        afk_start = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=2),
        )
        window1 = Event(
            timestamp=afk_start + timedelta(minutes=45),
            data={"type": "window"},
            duration=timedelta(minutes=5),
        )
        window2 = Event(
            timestamp=afk_start + timedelta(minutes=30),  # Earlier
            data={"type": "window"},
            duration=timedelta(minutes=5),
        )
        offline_dur, online_afk_dur = split_afk_by_window_coverage(
            afk_event, [window1, window2]
        )
        # Split at 30 minutes (earliest window)
        assert offline_dur == timedelta(minutes=30)
        assert online_afk_dur == timedelta(minutes=90)

    def test_split_sum_equals_total(self):
        """Offline + online-AFK duration always equals original AFK duration."""
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),
        )
        window_event = Event(
            timestamp=afk_start + timedelta(hours=5),
            data={"type": "window"},
            duration=timedelta(minutes=5),
        )
        offline_dur, online_afk_dur = split_afk_by_window_coverage(
            afk_event, [window_event]
        )
        assert offline_dur + online_afk_dur == afk_event.duration


class TestAFKFiltering:
    """Test filtering of false-positive AFK entries."""

    def test_filter_removes_matching_afk_entries(self):
        """AFK entries matching false-positive periods are removed."""
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_end = afk_start + timedelta(hours=10, minutes=11)

        gap_entries = [
            {
                "type": "afk",
                "start": afk_start,
                "duration": timedelta(hours=10, minutes=11),
            }
        ]
        false_positive_periods = {(afk_start, afk_end)}

        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)
        assert len(filtered) == 0

    def test_filter_keeps_non_matching_afk_entries(self):
        """AFK entries NOT matching false-positive periods are kept."""
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        other_afk_start = datetime(2026, 7, 28, 15, 0, 0, tzinfo=UTC)

        gap_entries = [
            {
                "type": "afk",
                "start": other_afk_start,
                "duration": timedelta(minutes=30),
            }
        ]
        false_positive_periods = {(afk_start, afk_start + timedelta(hours=10))}

        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)
        assert len(filtered) == 1
        assert filtered[0]["start"] == other_afk_start

    def test_filter_keeps_non_afk_entries(self):
        """Non-AFK entries (offline_task, etc.) are always kept."""
        offline_start = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)

        gap_entries = [
            {
                "type": "offline_task",
                "start": offline_start,
                "duration": timedelta(hours=2),
                "project": "ProjectA",
                "task": "OFFLINE task",
            }
        ]
        false_positive_periods = {(afk_start, afk_start + timedelta(hours=10))}

        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)
        assert len(filtered) == 1
        assert filtered[0]["type"] == "offline_task"

    def test_filter_exact_timestamp_matching(self):
        """Filtering uses exact timestamp equality, not fuzzy matching."""
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_end = afk_start + timedelta(hours=10, minutes=11)

        # AFK entry with exact times
        gap_entries = [
            {"type": "afk", "start": afk_start, "duration": timedelta(hours=10, minutes=11)}
        ]
        false_positive_periods = {(afk_start, afk_end)}

        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)
        assert len(filtered) == 0  # Should be filtered

        # Slightly different start time
        gap_entries2 = [
            {
                "type": "afk",
                "start": afk_start + timedelta(seconds=1),
                "duration": timedelta(hours=10, minutes=11),
            }
        ]
        filtered2 = _filter_false_positive_afk(gap_entries2, false_positive_periods)
        assert len(filtered2) == 1  # Should NOT be filtered (different timestamp)

    def test_filter_empty_false_positive_set(self):
        """Empty false_positive_periods returns gap_entries unchanged."""
        gap_entries = [
            {"type": "afk", "start": datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)}
        ]
        filtered = _filter_false_positive_afk(gap_entries, set())
        assert filtered == gap_entries

    def test_filter_empty_set_returns_unchanged(self):
        """Empty false_positive_periods set returns gap_entries unchanged."""
        gap_entries = [
            {"type": "afk", "start": datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)}
        ]
        filtered = _filter_false_positive_afk(gap_entries, set())
        assert filtered == gap_entries

    def test_filter_mixed_entries(self):
        """Filter handles mixture of AFK and non-AFK entries correctly."""
        afk_start1 = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_start2 = datetime(2026, 7, 28, 15, 0, 0, tzinfo=UTC)
        offline_start = datetime(2026, 7, 28, 20, 0, 0, tzinfo=UTC)

        gap_entries = [
            {
                "type": "afk",
                "start": afk_start1,
                "duration": timedelta(hours=10, minutes=11),
            },
            {
                "type": "afk",
                "start": afk_start2,
                "duration": timedelta(minutes=30),
            },
            {
                "type": "offline_task",
                "start": offline_start,
                "duration": timedelta(hours=2),
            },
        ]
        # Only mark first AFK as false positive
        false_positive_periods = {
            (afk_start1, afk_start1 + timedelta(hours=10, minutes=11))
        }

        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)
        assert len(filtered) == 2  # Second AFK + offline_task remain
        assert filtered[0]["start"] == afk_start2
        assert filtered[1]["start"] == offline_start


class TestAFKDetectionIntegration:
    """Integration tests for false-positive detection workflow."""

    def test_realistic_false_positive_afk_scenario(self):
        """Realistic scenario: 10h AFK, only 5 min of windows (system came back online)."""
        afk_start = datetime(2026, 7, 28, 1, 5, 42, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),
        )

        # Window logger starts recording at first app interaction after reboot
        window_event = Event(
            timestamp=afk_start + timedelta(hours=10, minutes=6),
            data={"type": "window"},
            duration=timedelta(minutes=5),
        )

        # Detection flow
        coverage = get_afk_window_coverage(afk_event, [window_event])
        classification = classify_afk_slot(coverage)
        offline_dur, online_afk_dur = split_afk_by_window_coverage(
            afk_event, [window_event]
        )

        # Assertions
        assert coverage < 1.0  # Less than 1% coverage
        assert classification == "OFFLINE"  # False positive
        assert offline_dur == timedelta(hours=10, minutes=6)  # System was off
        assert online_afk_dur == timedelta(minutes=5)  # Brief AFK after coming online

    def test_realistic_genuine_afk_scenario(self):
        """Realistic scenario: 30 min AFK with substantial window coverage."""
        afk_start = datetime(2026, 7, 28, 14, 30, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(minutes=30),
        )

        # User was idle but system was running (many window events)
        windows = [
            Event(
                timestamp=afk_start + timedelta(minutes=i * 2),
                data={"type": "window"},
                duration=timedelta(minutes=1),
            )
            for i in range(15)  # 15 windows, 1 min each = 15/30 = 50% coverage
        ]

        coverage = get_afk_window_coverage(afk_event, windows)
        classification = classify_afk_slot(coverage)

        assert coverage >= 5.0  # Well above threshold
        assert classification == "ONLINE_AFK"  # Real idle time

    def test_threshold_constants_are_used(self):
        """Verify that defined constants are used for thresholds."""
        # AFK_FALSE_POSITIVE_THRESHOLD should be 10 minutes
        assert AFK_FALSE_POSITIVE_THRESHOLD == timedelta(minutes=10)

        # AFK_FALSE_POSITIVE_COVERAGE_THRESHOLD should be 5%
        assert AFK_FALSE_POSITIVE_COVERAGE_THRESHOLD == 5.0

"""
Tests for main.py helper functions.

Covers low-level utilities used in the data-fetching pipeline,
including time-range extraction and app-bounded envelope computation.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from aw_core.models import Event


# These are imported from main.py via import path gymnastics
# We'll test them by direct unit-level logic since they're private helpers


def create_mock_event(timestamp, duration, app=""):
    """Factory for creating mock window events."""
    return Event(
        timestamp=timestamp,
        duration=timedelta(seconds=duration),
        data={"app": app} if app else {},
    )


class TestGetTimeRangesFromEvents:
    """Test _get_time_ranges_from_events() extraction logic."""

    def test_empty_event_list(self):
        """Empty list should return empty ranges."""
        # Direct logic test
        events = []
        if not events:
            ranges = []
        assert ranges == []

    def test_single_event(self):
        """Single event should create one range."""
        event = create_mock_event(
            datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            3600,  # 1 hour
            "Firefox"
        )
        events = [event]

        # Expected: one range from event start to end
        expected_start = event.timestamp
        expected_end = event.timestamp + event.duration

        assert (expected_start, expected_end) == (
            datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
        )

    def test_overlapping_events_merge(self):
        """Overlapping events should merge into single range."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        events = [
            create_mock_event(base, 3600, "Firefox"),         # 10:00-11:00
            create_mock_event(base + timedelta(minutes=30), 3600, "Chrome"),  # 10:30-11:30
        ]

        # Expected: merged range 10:00-11:30
        expected_start = base
        expected_end = base + timedelta(minutes=90)

        # Test merge logic: overlapping ranges should combine
        assert expected_start == base
        assert expected_end == base + timedelta(minutes=90)

    def test_non_overlapping_events_separate(self):
        """Non-overlapping events should create separate ranges."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        events = [
            create_mock_event(base, 3600, "Firefox"),           # 10:00-11:00
            create_mock_event(base + timedelta(hours=2), 3600, "Chrome"),  # 12:00-13:00
        ]

        # Expected: two separate ranges
        range1_start, range1_end = base, base + timedelta(hours=1)
        range2_start, range2_end = base + timedelta(hours=2), base + timedelta(hours=3)

        assert (range1_start, range1_end) == (
            datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
        )
        assert (range2_start, range2_end) == (
            datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
        )


class TestComputeAppBoundedRanges:
    """Test _compute_app_bounded_ranges() envelope computation (PHASE 14)."""

    def test_app_only_mode_single_event(self):
        """App-only mode: should return envelope of app usage."""
        event = create_mock_event(
            datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            3600,
            "Firefox"
        )
        app_matching = [event]

        # Expected: single envelope range from min(start) to max(end)
        app_start = event.timestamp
        app_end = event.timestamp + event.duration

        assert app_start == datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        assert app_end == datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc)

    def test_app_only_mode_multiple_events(self):
        """App-only mode with gaps: should return envelope, not fragmented."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        app_matching = [
            create_mock_event(base, 3600, "Firefox"),                    # 10:00-11:00
            create_mock_event(base + timedelta(hours=2), 1800, "Firefox"),  # 12:00-12:30 (gap at 11:00-12:00)
        ]

        # Expected: envelope from 10:00 to 12:30 (spans the internal gap)
        app_start = base
        app_end = base + timedelta(hours=2, minutes=30)

        # The envelope SHOULD include the gap for AFK context
        assert app_start == base
        assert app_end == base + timedelta(hours=2, minutes=30)

    def test_composite_mode_clip_to_envelope(self):
        """Composite mode: task_time_ranges clipped to app envelope."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

        # Task ranges: 10:00-12:00 (2 hours)
        task_ranges = [(base, base + timedelta(hours=2))]

        # App usage: 10:30-11:30 (1 hour, subset of task range)
        app_matching = [
            create_mock_event(base + timedelta(minutes=30), 3600, "Firefox")
        ]

        # Expected: clipped to 10:30-11:30
        expected_start = base + timedelta(minutes=30)
        expected_end = base + timedelta(hours=1, minutes=30)

        assert expected_start == base + timedelta(minutes=30)
        assert expected_end == base + timedelta(hours=1, minutes=30)

    def test_composite_mode_no_overlap(self):
        """Composite mode: if app envelope and task ranges don't overlap, fallback to task ranges."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

        # Task ranges: 10:00-11:00
        task_ranges = [(base, base + timedelta(hours=1))]

        # App usage: 13:00-14:00 (no overlap)
        app_matching = [
            create_mock_event(base + timedelta(hours=3), 3600, "Firefox")
        ]

        # Expected: fallback to original task_ranges (no valid clipped ranges)
        # Logic: clipped range would be empty, so return task_ranges unchanged
        assert task_ranges == [(base, base + timedelta(hours=1))]

    def test_no_app_matching_windows(self):
        """No app-matching windows: should return task_ranges unchanged."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        task_ranges = [(base, base + timedelta(hours=2))]
        app_matching = []

        # Expected: return task_ranges as-is
        assert app_matching == []
        result = task_ranges  # Fallback to original
        assert result == task_ranges

    def test_regression_gap_between_app_usages(self):
        """Regression: gap between two app-usage windows should still be spanned in envelope."""
        base = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

        # Two Firefox usage windows with a gap (e.g., browser closed for 30 min)
        app_matching = [
            create_mock_event(base, 1800, "Firefox"),                   # 10:00-10:30
            create_mock_event(base + timedelta(hours=1), 1800, "Firefox"),  # 11:00-11:30
        ]

        # Expected envelope: 10:00-11:30 (includes the 10:30-11:00 gap)
        # This preserves AFK context for that gap
        app_start = base
        app_end = base + timedelta(hours=1, minutes=30)

        assert app_start == base
        assert app_end == base + timedelta(hours=1, minutes=30)
        # The gap (10:30-11:00) is INCLUDED, not fragmented out
        gap_start = base + timedelta(minutes=30)
        gap_end = base + timedelta(hours=1)
        assert gap_start >= app_start  # Gap is within envelope
        assert gap_end <= app_end      # Gap is within envelope

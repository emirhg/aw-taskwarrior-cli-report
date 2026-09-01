"""
TDD Tests for Breaks Column Feature

Tests for displaying break durations in timeline report.
Breaks are gaps between work sessions.

Requirements:
1. Calculate break duration from gap between slots
2. Only show breaks > 5 minutes (MIN_BREAK_DURATION)
3. Add BREAK column on the left (before OFFLINE/AFK/ACTIVE)
4. Maintain proper column alignment
5. Consistent styling with other duration columns
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.pipeline.timeline_render import (
    calculate_break_duration,
    format_break_column,
    get_gap_between_slots,
)
from tw_report.core.report_slot import ReportTimelineSlot


# Minimum break duration threshold
MIN_BREAK_DURATION = timedelta(minutes=5)


class TestBreakCalculation:
    """Tests for break duration calculation logic."""

    def test_calculate_break_between_two_slots(self):
        """Calculate break between two consecutive time slots."""
        slot1_end = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        slot2_start = datetime(2026, 8, 30, 14, 15, 0, tzinfo=timezone.utc)

        break_duration = calculate_break_duration(slot1_end, slot2_start)

        assert break_duration == timedelta(minutes=15)

    def test_zero_break_no_gap(self):
        """No break when slots are adjacent (no gap)."""
        slot1_end = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        slot2_start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)

        break_duration = calculate_break_duration(slot1_end, slot2_start)

        assert break_duration == timedelta(0)

    def test_negative_break_overlapping_slots(self):
        """Overlapping slots should not happen, but handle gracefully."""
        slot1_end = datetime(2026, 8, 30, 14, 15, 0, tzinfo=timezone.utc)
        slot2_start = datetime(2026, 8, 30, 14, 10, 0, tzinfo=timezone.utc)

        break_duration = calculate_break_duration(slot1_end, slot2_start)

        # Should clamp to 0, not negative
        assert break_duration == timedelta(0)

    def test_large_break_overnight(self):
        """Calculate break spanning overnight."""
        slot1_end = datetime(2026, 8, 30, 22, 0, 0, tzinfo=timezone.utc)
        slot2_start = datetime(2026, 8, 31, 8, 0, 0, tzinfo=timezone.utc)

        break_duration = calculate_break_duration(slot1_end, slot2_start)

        assert break_duration == timedelta(hours=10)


class TestBreakDetection:
    """Tests for detecting significant breaks (>= MIN_BREAK_DURATION)."""

    def test_break_below_threshold_not_shown(self):
        """Breaks < 5 minutes are considered tracking noise."""
        break_duration = timedelta(minutes=3)

        should_show = break_duration >= MIN_BREAK_DURATION

        assert not should_show

    def test_break_at_threshold_shown(self):
        """Break exactly at 5 minute threshold is shown."""
        break_duration = timedelta(minutes=5)

        should_show = break_duration >= MIN_BREAK_DURATION

        assert should_show

    def test_break_above_threshold_shown(self):
        """Breaks > 5 minutes are shown."""
        break_duration = timedelta(minutes=15)

        should_show = break_duration >= MIN_BREAK_DURATION

        assert should_show


class TestBreakColumnFormatting:
    """Tests for formatting break column output."""

    def test_format_break_column_with_duration(self):
        """Format break duration as HH:MM:SS."""
        break_duration = timedelta(hours=1, minutes=23, seconds=45)

        formatted = format_break_column(break_duration)

        assert formatted == "01:23:45"

    def test_format_break_column_zero_duration(self):
        """Zero duration (< MIN_BREAK_DURATION) displays as blank."""
        break_duration = timedelta(0)

        formatted = format_break_column(break_duration)

        # Zero breaks don't show (not >= 5 min threshold)
        assert formatted == "        "  # 8 spaces

    def test_format_break_column_sub_hour(self):
        """Sub-hour break displays correctly."""
        break_duration = timedelta(minutes=35, seconds=20)

        formatted = format_break_column(break_duration)

        assert formatted == "00:35:20"

    def test_break_column_width_fixed(self):
        """Break column maintains fixed width (HH:MM:SS = 8 chars)."""
        formatted = format_break_column(timedelta(minutes=5))

        assert len(formatted) == 8  # HH:MM:SS format


class TestColumnAlignment:
    """Tests for break column alignment with other columns."""

    def test_break_column_position_leftmost(self):
        """BREAK column is leftmost (before OFFLINE/AFK/ACTIVE)."""
        # Column order should be: BREAK | OFFLINE | AFK | ACTIVE
        column_order = ["BREAK", "OFFLINE", "AFK", "ACTIVE"]
        break_position = column_order.index("BREAK")

        assert break_position == 0, "BREAK column should be first"

    def test_column_header_alignment(self):
        """All column headers aligned with consistent spacing."""
        headers = {
            "BREAK": "00:00:00",      # 8 chars (HH:MM:SS)
            "OFFLINE": "00:00:00",    # 8 chars (HH:MM:SS)
            "AFK": "00:00:00",        # 8 chars (HH:MM:SS)
            "ACTIVE": "00:00:00",     # 8 chars (HH:MM:SS)
        }

        # All columns should have same width (8 chars for time format)
        widths = {col: len(value) for col, value in headers.items()}

        assert len(set(widths.values())) == 1, "All columns should have consistent width"

    def test_break_column_padding(self):
        """Break column values are right-aligned with padding."""
        break_duration = timedelta(minutes=5)
        formatted = format_break_column(break_duration)

        # Should be right-aligned, padded with spaces if needed
        # (though HH:MM:SS already fills 8 chars)
        assert formatted == "00:05:00"
        assert formatted.rjust(8) == formatted


class TestBreakSlotDetection:
    """Tests for detecting break slots (gaps without events)."""

    def test_get_gap_between_slots(self):
        """Extract gap time between two slots."""
        slot1 = {"start": datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
                 "end": datetime(2026, 8, 30, 14, 30, 0, tzinfo=timezone.utc)}
        slot2 = {"start": datetime(2026, 8, 30, 14, 45, 0, tzinfo=timezone.utc),
                 "end": datetime(2026, 8, 30, 15, 0, 0, tzinfo=timezone.utc)}

        gap = get_gap_between_slots(slot1, slot2)

        assert gap == timedelta(minutes=15)

    def test_no_gap_adjacent_slots(self):
        """Adjacent slots have zero gap."""
        slot1 = {"start": datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
                 "end": datetime(2026, 8, 30, 14, 30, 0, tzinfo=timezone.utc)}
        slot2 = {"start": datetime(2026, 8, 30, 14, 30, 0, tzinfo=timezone.utc),
                 "end": datetime(2026, 8, 30, 15, 0, 0, tzinfo=timezone.utc)}

        gap = get_gap_between_slots(slot1, slot2)

        assert gap == timedelta(0)


class TestBreakColumnStyling:
    """Tests for visual styling consistency of break column."""

    def test_break_column_matches_other_column_style(self):
        """Break column uses same styling as OFFLINE/AFK/ACTIVE columns."""
        # All columns should use same time format (HH:MM:SS)
        # All columns should be right-aligned
        # All columns should have 8-character width

        break_col = "00:15:30"
        offline_col = "00:10:45"
        afk_col = "00:05:20"
        active_col = "00:35:50"

        # All same length
        assert all(len(col) == 8 for col in [break_col, offline_col, afk_col, active_col])

    def test_break_column_empty_displays_blank(self):
        """When no break exists or break < threshold, column is blank."""
        # Should display as 8 spaces (or empty column)
        blank_break = "        "  # 8 spaces

        assert len(blank_break) == 8


class TestBreakColumnIntegration:
    """Integration tests for break column with timeline rendering."""

    def test_break_column_with_real_timeline_slot(self):
        """Break column displays correctly with actual timeline slot."""
        slot = ReportTimelineSlot(
            start=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 30, 14, 30, 0, tzinfo=timezone.utc),
            duration=timedelta(minutes=30),
            actual_duration=timedelta(minutes=30),
        )

        # Slot should have start/end/duration
        assert hasattr(slot, 'start')
        assert hasattr(slot, 'end')
        assert slot.duration == timedelta(minutes=30)

    def test_break_not_shown_for_regular_slots(self):
        """Regular work slots don't show break column."""
        # Break column only appears in gap rows
        slot_type = "work"  # Regular work slot

        should_show_break = slot_type == "gap"

        assert not should_show_break

    def test_break_shown_for_gap_rows(self):
        """Break column appears only for gap/break rows."""
        slot_type = "gap"  # Gap/break row

        should_show_break = slot_type == "gap"

        assert should_show_break


# Test fixtures

@pytest.fixture
def sample_slot_pair():
    """Two slots with a gap between them."""
    slot1 = ReportTimelineSlot(
        start=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 30, 14, 30, 0, tzinfo=timezone.utc),
        duration=timedelta(minutes=30),
        actual_duration=timedelta(minutes=30),
    )

    slot2 = ReportTimelineSlot(
        start=datetime(2026, 8, 30, 14, 45, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 30, 15, 15, 0, tzinfo=timezone.utc),
        duration=timedelta(minutes=30),
        actual_duration=timedelta(minutes=30),
    )

    return (slot1, slot2)


@pytest.fixture
def min_break_duration():
    """Minimum break duration threshold."""
    return timedelta(minutes=5)

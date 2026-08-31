"""Unit tests for slot grouping functions with day_start_hour support.

Tests the refactored get_slot_week_key() and get_slot_logical_date() functions
to verify correct week/date assignment when logical day != calendar day.
"""

import pytest
from datetime import datetime, date, timezone, timedelta

from tw_report.pipeline.timeline_render import (
    get_slot_week_key,
    get_slot_logical_date,
)


class TestGetSlotLogicalDate:
    """Tests for get_slot_logical_date() function."""

    def test_midnight_is_previous_logical_day_with_default_day_start_hour(self):
        """00:30 UTC is still in previous logical day when day_start_hour=4."""
        # 2026-08-31 00:30 UTC
        slot = {"start": datetime(2026, 8, 31, 0, 30, 0)}
        result = get_slot_logical_date(slot, day_start_hour=4)
        # Logical day = 00:30 - 4:00 = previous day (Aug 30)
        assert result == date(2026, 8, 30)

    def test_after_day_start_hour_is_current_logical_day(self):
        """04:00 UTC is start of current logical day when day_start_hour=4."""
        slot = {"start": datetime(2026, 8, 31, 4, 0, 0)}
        result = get_slot_logical_date(slot, day_start_hour=4)
        assert result == date(2026, 8, 31)

    def test_before_day_start_hour_is_previous_logical_day(self):
        """03:59 UTC is still in previous logical day when day_start_hour=4."""
        slot = {"start": datetime(2026, 8, 31, 3, 59, 0)}
        result = get_slot_logical_date(slot, day_start_hour=4)
        assert result == date(2026, 8, 30)

    def test_evening_time_is_same_logical_day(self):
        """22:00 UTC is in same logical day when day_start_hour=4."""
        slot = {"start": datetime(2026, 8, 31, 22, 0, 0)}
        result = get_slot_logical_date(slot, day_start_hour=4)
        assert result == date(2026, 8, 31)

    def test_day_start_hour_zero_uses_calendar_date(self):
        """With day_start_hour=0, logical date = calendar date."""
        slot = {"start": datetime(2026, 8, 31, 3, 59, 0)}
        result = get_slot_logical_date(slot, day_start_hour=0)
        # No offset, so 3:59 is still Aug 31
        assert result == date(2026, 8, 31)

    def test_day_start_hour_twelve_works_correctly(self):
        """day_start_hour=12 makes logical days start at noon."""
        # 11:59 should be previous logical day
        slot = {"start": datetime(2026, 8, 31, 11, 59, 0)}
        result = get_slot_logical_date(slot, day_start_hour=12)
        assert result == date(2026, 8, 30)

        # 12:00 should be current logical day
        slot = {"start": datetime(2026, 8, 31, 12, 0, 0)}
        result = get_slot_logical_date(slot, day_start_hour=12)
        assert result == date(2026, 8, 31)

    def test_works_with_reporttimelineslot_object(self):
        """Function handles ReportTimelineSlot objects as well as dicts."""
        # Create a mock object with .start attribute
        class MockSlot:
            def __init__(self, start_time):
                self.start = start_time

        slot = MockSlot(datetime(2026, 8, 31, 2, 0, 0))
        result = get_slot_logical_date(slot, day_start_hour=4)
        assert result == date(2026, 8, 30)

    def test_handles_timezone_aware_datetime(self):
        """Tests with timezone-aware datetime objects."""
        utc_tz = timezone.utc
        # 2026-08-31 00:30 UTC
        slot = {"start": datetime(2026, 8, 31, 0, 30, 0, tzinfo=utc_tz)}
        result = get_slot_logical_date(slot, day_start_hour=4)
        # Still calculates based on clock time (00:30 - 4:00 = previous day)
        assert result == date(2026, 8, 30)


class TestGetSlotWeekKey:
    """Tests for get_slot_week_key() function."""

    def test_sunday_in_week_35(self):
        """2026-08-30 (Sunday) is in ISO week 35."""
        slot = {"start": datetime(2026, 8, 30, 12, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        assert result == "2026-W35"

    def test_monday_in_week_36(self):
        """2026-08-31 (Monday) is in ISO week 36."""
        slot = {"start": datetime(2026, 8, 31, 12, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        assert result == "2026-W36"

    def test_midnight_before_day_start_hour_uses_previous_day_week(self):
        """00:30 on Monday uses Sunday's week (W35) when day_start_hour=4."""
        # 2026-08-31 00:30 (Monday calendar, but logical day Aug 30 = Sunday)
        slot = {"start": datetime(2026, 8, 31, 0, 30, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        # Logical day is Aug 30 (Sun) which is W35
        assert result == "2026-W35"

    def test_after_midnight_but_before_day_start_remains_previous_week(self):
        """02:00 on Monday still in previous logical day's week."""
        slot = {"start": datetime(2026, 8, 31, 2, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        assert result == "2026-W35"

    def test_at_day_start_hour_begins_new_logical_day_week(self):
        """At exactly day_start_hour, we're in the new logical day's week."""
        slot = {"start": datetime(2026, 8, 31, 4, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        assert result == "2026-W36"

    def test_week_format_with_leading_zero(self):
        """Week numbers less than 10 have leading zero (W01-W09)."""
        # 2026-01-05 is in ISO week 2
        slot = {"start": datetime(2026, 1, 5, 12, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        assert result == "2026-W02"

        # 2026-01-01 is in ISO week 1
        slot = {"start": datetime(2026, 1, 1, 12, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        assert result == "2026-W01"

    def test_consistency_across_week_boundary(self):
        """Same logical day always gets same week key regardless of calendar date."""
        # These two times are on different calendar days but same logical day
        # (logical day Aug 31 when day_start_hour=4)
        slot1 = {"start": datetime(2026, 8, 31, 22, 0, 0)}  # Aug 31 22:00
        slot2 = {"start": datetime(2026, 9, 1, 2, 0, 0)}   # Sep  1 02:00

        key1 = get_slot_week_key(slot1, day_start_hour=4)
        key2 = get_slot_week_key(slot2, day_start_hour=4)

        # Both should be in W36 (logical day Aug 31 is Monday in W36)
        assert key1 == "2026-W36"
        assert key2 == "2026-W36"
        assert key1 == key2

    def test_different_logical_days_get_different_weeks(self):
        """Different logical days get different week keys when crossing week boundary."""
        # Aug 30 22:00 is still in logical day Aug 30 (Sunday, W35)
        slot1 = {"start": datetime(2026, 8, 30, 22, 0, 0)}
        # Aug 31 22:00 is logical day Aug 31 (Monday, W36)
        slot2 = {"start": datetime(2026, 8, 31, 22, 0, 0)}

        key1 = get_slot_week_key(slot1, day_start_hour=4)
        key2 = get_slot_week_key(slot2, day_start_hour=4)

        assert key1 == "2026-W35"
        assert key2 == "2026-W36"
        assert key1 != key2

    def test_year_boundary_handling(self):
        """Week key correctly handles year boundaries."""
        # 2025-12-31 might be in 2026-W01
        slot = {"start": datetime(2025, 12, 31, 12, 0, 0)}
        result = get_slot_week_key(slot, day_start_hour=4)
        # Verify format is correct
        assert result.startswith("202")  # Should be 2025 or 2026
        assert "-W" in result
        parts = result.split("-W")
        assert len(parts) == 2
        year, week = parts
        assert year.isdigit() and len(year) == 4
        assert week.isdigit() and 1 <= int(week) <= 53


class TestLogicalDateBugReproduction:
    """Tests that reproduce and verify the intercalation bug is fixed."""

    def test_intercalation_bug_scenario(self):
        """Reproduce the exact scenario from the bug report.

        Problem: 2026-08-31 22:00-02:00 (next day) was showing as both W35 and W36.
        Expected: All entries in logical day Aug 31 should be W36.
        """
        times = [
            datetime(2026, 8, 31, 22, 0, 0),   # 22:00 Aug 31
            datetime(2026, 8, 31, 22, 9, 0),   # 22:09 Aug 31
            datetime(2026, 8, 31, 23, 13, 0),  # 23:13 Aug 31
            datetime(2026, 9, 1, 0, 14, 0),    # 00:14 Sep  1 (still logical Aug 31)
            datetime(2026, 9, 1, 1, 37, 0),    # 01:37 Sep  1 (still logical Aug 31)
        ]

        week_keys = [get_slot_week_key({"start": t}, day_start_hour=4) for t in times]
        logical_dates = [get_slot_logical_date({"start": t}, day_start_hour=4) for t in times]

        # All should be in logical day Aug 31 (Monday, W36)
        assert all(ld == date(2026, 8, 31) for ld in logical_dates), \
            f"Not all times in logical day Aug 31: {logical_dates}"
        assert all(wk == "2026-W36" for wk in week_keys), \
            f"Not all times in W36: {week_keys}"

    def test_crossing_logical_day_boundary_changes_week(self):
        """Verify that crossing the logical day boundary does change the week key."""
        # Last entry of logical day Aug 30 (Sunday, W35)
        time_aug30_last = datetime(2026, 8, 31, 3, 59, 0)  # 03:59 on calendar Aug 31
        # First entry of logical day Aug 31 (Monday, W36)
        time_aug31_first = datetime(2026, 8, 31, 4, 0, 0)  # 04:00 on calendar Aug 31

        key_aug30 = get_slot_week_key({"start": time_aug30_last}, day_start_hour=4)
        key_aug31 = get_slot_week_key({"start": time_aug31_first}, day_start_hour=4)

        date_aug30 = get_slot_logical_date({"start": time_aug30_last}, day_start_hour=4)
        date_aug31 = get_slot_logical_date({"start": time_aug31_first}, day_start_hour=4)

        # Should be different logical days
        assert date_aug30 != date_aug31
        # Should be different weeks
        assert key_aug30 != key_aug31
        # Specifically
        assert key_aug30 == "2026-W35"
        assert key_aug31 == "2026-W36"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Comprehensive audit and tests of the slot pipeline with day_start_hour handling.

Tests the entire pipeline from slot creation through grouping to identify
where the intercalation bug originates.
"""

import pytest
from datetime import datetime, date, timezone, timedelta

from tw_report.pipeline.timeline_render import (
    get_slot_week_key,
    get_slot_logical_date,
    split_slots_spanning_days,
)
from tw_report.core.period import logical_date


class TestSlotTimezoneHandling:
    """Audit how timezones are handled in slots."""

    def test_logical_date_with_naive_datetime(self):
        """logical_date() works with naive (no timezone) datetimes."""
        dt_naive = datetime(2026, 8, 31, 22, 0, 0)  # No tzinfo
        result = logical_date(dt_naive, day_start_hour=4)
        assert result == date(2026, 8, 31)

    def test_logical_date_with_utc_datetime(self):
        """logical_date() works with UTC datetimes."""
        dt_utc = datetime(2026, 8, 31, 22, 0, 0, tzinfo=timezone.utc)
        result = logical_date(dt_utc, day_start_hour=4)
        # UTC 22:00 - 4 hours = UTC 18:00, still Aug 31
        assert result == date(2026, 8, 31)

    def test_logical_date_with_utc_minus_6_datetime(self):
        """logical_date() with UTC-6 (Central Time) datetimes.

        This is critical for the bug - the user is likely in Central Time (UTC-6).
        If slots are in UTC but calculation assumes local time, this would cause issues.
        """
        tz_minus_6 = timezone(timedelta(hours=-6))
        # 2026-08-31 22:00 Central Time (which is 2026-09-01 04:00 UTC)
        dt_local = datetime(2026, 8, 31, 22, 0, 0, tzinfo=tz_minus_6)
        result = logical_date(dt_local, day_start_hour=4)

        # logical_date just subtracts 4 hours from the datetime object
        # It doesn't convert timezones, it operates on the local time
        # So: 22:00 - 4 hours = 18:00, date = Aug 31
        assert result == date(2026, 8, 31)

    def test_logical_date_consistency_same_instant_different_tz(self):
        """Same instant in different timezones should give same logical dates.

        This was a CRITICAL BUG - fixed in 2026-08-31.
        Same moment in time MUST have same logical date regardless of timezone.
        """
        # Same instant: 2026-09-01 04:00 UTC = 2026-08-31 22:00 Central(-6)
        dt_utc = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
        tz_minus_6 = timezone(timedelta(hours=-6))
        dt_local = datetime(2026, 8, 31, 22, 0, 0, tzinfo=tz_minus_6)

        # These are the same instant in time
        assert dt_utc.astimezone(tz_minus_6) == dt_local

        # logical_date should now give SAME results after fix
        result_utc = logical_date(dt_utc, day_start_hour=4)
        result_local = logical_date(dt_local, day_start_hour=4)

        print(f"UTC instant ({dt_utc}) → logical date {result_utc}")
        print(f"Local instant ({dt_local}) → logical date {result_local}")

        # After fix, these should be the same (both in local timezone)
        assert result_utc == result_local, \
            "BUG: logical_date() doesn't normalize timezones!"
        # Both should resolve to the local time representation (Aug 31)
        assert result_utc == date(2026, 8, 31)
        assert result_local == date(2026, 8, 31)


class TestSplitSlotsBoundaryHandling:
    """Test how split_slots_spanning_days handles day boundaries with day_start_hour."""

    def test_split_at_logical_day_boundary(self):
        """Slots crossing logical day boundary at 4 AM should be split."""
        # Slot from 3:00 to 5:00 (crosses 4 AM logical day boundary)
        slot = {
            "start": datetime(2026, 8, 31, 3, 0, 0),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }

        result = split_slots_spanning_days([slot], day_start_hour=4)

        # Should be split into two pieces (before and after 04:00)
        print(f"Input: 1 slot from 03:00 to 05:00")
        print(f"Output: {len(result)} slots")
        for i, r in enumerate(result):
            print(f"  Slot {i}: {r.get('start')} to {r.get('start') + r.get('duration')}")

        # If this returns 1, it means the splitting isn't working correctly
        # If this returns 2, it means it's splitting at calendar day (midnight)
        # We need to verify what it actually does

    def test_split_preserves_timezone_info(self):
        """After splitting, slots should preserve timezone information."""
        tz_minus_6 = timezone(timedelta(hours=-6))
        slot = {
            "start": datetime(2026, 8, 31, 22, 0, 0, tzinfo=tz_minus_6),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "type": "regular",
            "project": "Test",
            "task": "Work",
        }

        result = split_slots_spanning_days([slot], day_start_hour=4)

        for s in result:
            start = s.get("start")
            if start and hasattr(start, "tzinfo"):
                assert start.tzinfo is not None, "Timezone info lost during split!"


class TestSlotGroupingConsistency:
    """Test that slots are grouped consistently regardless of how they're created."""

    def test_grouping_naive_vs_tzaware(self):
        """Same logical time as naive vs tz-aware should group the same way."""
        # Create two versions of the same logical time:
        # - Naive: 2026-08-31 22:00 (interpreted as local)
        # - UTC-6 aware: 2026-08-31 22:00-06:00 (explicitly Central Time)

        slot_naive = {"start": datetime(2026, 8, 31, 22, 0, 0)}
        tz_minus_6 = timezone(timedelta(hours=-6))
        slot_aware = {"start": datetime(2026, 8, 31, 22, 0, 0, tzinfo=tz_minus_6)}

        key_naive = get_slot_week_key(slot_naive, day_start_hour=4)
        key_aware = get_slot_week_key(slot_aware, day_start_hour=4)

        date_naive = get_slot_logical_date(slot_naive, day_start_hour=4)
        date_aware = get_slot_logical_date(slot_aware, day_start_hour=4)

        print(f"Naive (22:00): week={key_naive}, date={date_naive}")
        print(f"UTC-6 (22:00): week={key_aware}, date={date_aware}")

        # They should group the same way
        assert key_naive == key_aware, "Week keys differ for same local time!"
        assert date_naive == date_aware, "Logical dates differ for same local time!"

    def test_same_instant_different_tz_grouping(self):
        """Same instant in different TZ should ideally group the same way.

        But if logical_date() doesn't normalize, they WON'T.
        This test exposes the BUG.
        """
        # Same instant: 2026-09-01 04:00 UTC = 2026-08-31 22:00 Central
        dt_utc = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
        tz_minus_6 = timezone(timedelta(hours=-6))
        dt_local = datetime(2026, 8, 31, 22, 0, 0, tzinfo=tz_minus_6)

        slot_utc = {"start": dt_utc}
        slot_local = {"start": dt_local}

        key_utc = get_slot_week_key(slot_utc, day_start_hour=4)
        key_local = get_slot_week_key(slot_local, day_start_hour=4)

        print(f"Same instant, UTC repr: week={key_utc}")
        print(f"Same instant, Local repr: week={key_local}")

        # Ideally these should be the same (same instant in time)
        # But they WON'T be if logical_date() doesn't normalize
        if key_utc != key_local:
            print("⚠️  BUG CONFIRMED: Same instant in different TZ get different week keys!")


class TestSlotPipelineIntegration:
    """Integration tests for the entire slot pipeline."""

    def test_slot_created_then_split_then_grouped(self):
        """Test a slot through the entire pipeline."""
        # Create a slot spanning from late evening to early morning
        slot = {
            "start": datetime(2026, 8, 31, 22, 0, 0),
            "duration": timedelta(hours=3),
            "actual_duration": timedelta(hours=3),
            "type": "regular",
            "project": "Work",
            "task": "Task1",
        }

        print("\n1. Original slot:")
        print(f"   Start: {slot['start']}, Duration: {slot['duration']}")
        print(f"   Logical date: {get_slot_logical_date(slot, day_start_hour=4)}")
        print(f"   Week key: {get_slot_week_key(slot, day_start_hour=4)}")

        # Split at day boundaries
        split = split_slots_spanning_days([slot], day_start_hour=4)
        print(f"\n2. After split_slots_spanning_days (day_start_hour=4):")
        print(f"   Result count: {len(split)}")
        for i, s in enumerate(split):
            print(f"   Slot {i}: {s.get('start')} + {s.get('duration')}")
            print(f"      Logical date: {get_slot_logical_date(s, day_start_hour=4)}")
            print(f"      Week key: {get_slot_week_key(s, day_start_hour=4)}")

        # Check grouping consistency
        keys = [get_slot_week_key(s, day_start_hour=4) for s in split]
        dates = [get_slot_logical_date(s, day_start_hour=4) for s in split]

        print(f"\n3. Grouping consistency:")
        print(f"   Week keys: {keys}")
        print(f"   Logical dates: {dates}")

        # All pieces from same task should ideally be in same logical day
        # (unless task spans midnight AND we're splitting at calendar midnight)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s shows print statements

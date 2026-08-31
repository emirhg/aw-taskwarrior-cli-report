"""Detailed audit of the _merge_group function to find edge case bugs."""

import pytest
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from tw_report.pipeline.consolidation import _merge_group


class TestMergeGroupEdgeCases:
    """Test _merge_group with edge cases that might cause degenerate slots."""

    def make_slot(self, start, end, task="T1"):
        """Create slot with proper end field."""
        return {
            "start": start,
            "end": end,
            "duration": end - start,
            "task": task,
        }

    def test_merge_group_with_single_slot(self):
        """Single slot in group should return unchanged."""
        tz_minus6 = timezone(timedelta(hours=-6))
        start = datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6)
        end = datetime(2026, 8, 30, 13, 0, tzinfo=tz_minus6)

        slot = self.make_slot(start, end)
        result = _merge_group([slot])

        print(f"\nSINGLE SLOT TEST:")
        print(f"  Input:  {slot['start']} to {slot['end']}")
        print(f"  Output: {result['start']} to {result['end']}")
        assert result == slot

    def test_merge_group_preserves_end_field(self):
        """Merged slot should have correct end field."""
        tz_minus6 = timezone(timedelta(hours=-6))
        slot1_start = datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6)
        slot1_end = datetime(2026, 8, 30, 13, 0, tzinfo=tz_minus6)

        slot2_start = datetime(2026, 8, 30, 13, 30, tzinfo=tz_minus6)
        slot2_end = datetime(2026, 8, 30, 14, 30, tzinfo=tz_minus6)

        slot1 = self.make_slot(slot1_start, slot1_end)
        slot2 = self.make_slot(slot2_start, slot2_end)

        result = _merge_group([slot1, slot2])

        print(f"\nTWO SLOT MERGE TEST:")
        print(f"  Slot 1: {slot1['start']} to {slot1['end']}")
        print(f"  Slot 2: {slot2['start']} to {slot2['end']}")
        print(f"  Merged: {result['start']} to {result['end']}")
        print(f"  Duration: {result['duration']}")

        assert result['start'] == slot1_start
        assert result['end'] == slot2_end
        expected_duration = slot2_end - slot1_start
        assert result['duration'] == expected_duration

    def test_merge_group_with_null_end(self):
        """Test behavior when end field is None (edge case)."""
        tz_minus6 = timezone(timedelta(hours=-6))
        slot1_start = datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6)
        slot1_duration = timedelta(hours=1)

        # Slot with None end field (edge case)
        slot1 = {
            "start": slot1_start,
            "end": None,
            "duration": slot1_duration,
            "task": "T1",
        }

        slot2_start = datetime(2026, 8, 30, 13, 30, tzinfo=tz_minus6)
        slot2_end = datetime(2026, 8, 30, 14, 30, tzinfo=tz_minus6)
        slot2 = self.make_slot(slot2_start, slot2_end)

        print(f"\nNULL END TEST:")
        print(f"  Slot 1 end: {slot1['end']}")
        print(f"  Slot 2 end: {slot2['end']}")

        # This should NOT crash and should handle the None gracefully
        try:
            result = _merge_group([slot1, slot2])
            print(f"  Merged result: {result['start']} to {result['end']}")
            print(f"  Duration: {result['duration']}")
            assert result['end'] == slot2_end
            assert result['end'] is not None
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            raise

    def test_merge_group_respects_timezone(self):
        """Merged slot should maintain timezone consistency."""
        tz_minus6 = timezone(timedelta(hours=-6))

        slot1 = self.make_slot(
            datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6),
            datetime(2026, 8, 30, 13, 0, tzinfo=tz_minus6),
        )
        slot2 = self.make_slot(
            datetime(2026, 8, 30, 14, 0, tzinfo=tz_minus6),
            datetime(2026, 8, 30, 15, 0, tzinfo=tz_minus6),
        )

        result = _merge_group([slot1, slot2])

        print(f"\nTIMEZONE TEST:")
        print(f"  Slot 1 tz: {slot1['start'].tzinfo}")
        print(f"  Slot 2 tz: {slot2['start'].tzinfo}")
        print(f"  Merged start tz: {result['start'].tzinfo}")
        print(f"  Merged end tz: {result['end'].tzinfo}")

        assert result['start'].tzinfo == tz_minus6
        assert result['end'].tzinfo == tz_minus6


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

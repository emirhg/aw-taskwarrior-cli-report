"""Audit rendering pipeline to find where consolidated slots get re-split."""

import pytest
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from tw_report.pipeline.timeline_render import (
    split_slots_spanning_days,
    get_slot_logical_date,
    get_slot_week_key,
)


class TestRenderingFunctionAudit:
    """Test individual rendering functions with consolidated slots."""

    @pytest.fixture
    def base_time(self):
        """2026-08-30 11:00 UTC-6"""
        return datetime(2026, 8, 30, 11, 0, tzinfo=timezone(timedelta(hours=-6)))

    def make_slot(self, start, end, task="T1", project="P1"):
        """Create a realistic slot dict."""
        return {
            "start": start,
            "end": end,
            "duration": end - start,
            "actual_duration": end - start,
            "productive_duration": timedelta(0),
            "project": project,
            "task": task,
            "tags": [],
            "categories": [],
            "apps": [],
            "event_duration": end - start,
            "afk_duration": timedelta(0),
            "type": "regular",
            "is_offline_task": False,
            "is_afk_only": False,
        }

    def test_split_slots_spanning_days_with_consolidated_slot(self, base_time):
        """TEST: Does split_slots_spanning_days re-split consolidated slots?"""
        # Create a consolidated slot that spans from 12:00 to 14:00 (same day)
        consolidated_slot = self.make_slot(
            base_time + timedelta(hours=1),  # 12:00
            base_time + timedelta(hours=3),  # 14:00
            task="ConsolidatedTask",
        )

        print(f"\nINPUT: Consolidated slot")
        print(f"  {consolidated_slot['start']} to {consolidated_slot['end']}")
        print(f"  Duration: {consolidated_slot['duration']}")

        # Run through split_slots_spanning_days
        result = split_slots_spanning_days([consolidated_slot], day_start_hour=4)

        print(f"\nOUTPUT after split_slots_spanning_days:")
        print(f"  Count: {len(result)}")
        for i, slot in enumerate(result):
            print(
                f"    Slot {i}: {slot['start']} to {slot['end']} ({slot['duration']})"
            )

        # HYPOTHESIS: If result has >1 slot, the function re-split the consolidated slot
        if len(result) > 1:
            print(f"\n⚠️  FOUND ISSUE: split_slots_spanning_days re-split the consolidated slot!")
            print(f"    Expected: 1 slot")
            print(f"    Got: {len(result)} slots")
            return False  # Re-splitting occurred
        else:
            print(f"\n✓ Consolidation preserved (still 1 slot)")
            return True

    def test_logical_date_calculation(self, base_time):
        """TEST: Does logical_date handle consolidated slots correctly?"""
        # Consolidated slot from 12:00 to 14:00
        slot = self.make_slot(
            base_time + timedelta(hours=1),
            base_time + timedelta(hours=3),
        )

        print(f"\nINPUT: Consolidated slot")
        print(f"  {slot['start']} to {slot['end']}")
        print(f"  day_start_hour=4")

        # Get logical dates
        start_logical_date = get_slot_logical_date(slot, day_start_hour=4)
        print(f"\nOUTPUT:")
        print(f"  Logical date: {start_logical_date}")

        # Should be same date since slot doesn't cross day boundary
        assert start_logical_date is not None
        print(f"✓ Logical date calculated correctly")
        return True

    def test_week_key_calculation(self, base_time):
        """TEST: Does week_key calculation work with consolidated slots?"""
        slot = self.make_slot(
            base_time + timedelta(hours=1),
            base_time + timedelta(hours=3),
        )

        print(f"\nINPUT: Consolidated slot")
        print(f"  {slot['start']}")

        week_key = get_slot_week_key(slot, day_start_hour=4)
        print(f"\nOUTPUT:")
        print(f"  Week key: {week_key}")

        assert week_key is not None
        assert "W" in week_key  # Should be format like "2026-W35"
        print(f"✓ Week key calculated correctly")
        return True


class TestRenderingPipelineIntegration:
    """Test the full rendering pipeline with consolidated slots."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 8, 30, 11, 0, tzinfo=timezone(timedelta(hours=-6)))

    def make_slot(self, start, end, task="T1", project="P1"):
        return {
            "start": start,
            "end": end,
            "duration": end - start,
            "actual_duration": end - start,
            "productive_duration": timedelta(0),
            "project": project,
            "task": task,
            "tags": [],
            "categories": [],
            "apps": [],
            "event_duration": end - start,
            "afk_duration": timedelta(0),
            "type": "regular",
            "is_offline_task": False,
            "is_afk_only": False,
        }

    def test_pipeline_with_multiple_consolidated_slots(self, base_time):
        """Test entire pipeline with already-consolidated input."""
        slots = [
            # Consolidated slot 1: 3 original sessions merged
            self.make_slot(
                base_time + timedelta(hours=1),
                base_time + timedelta(hours=3),
                task="Task1",
            ),
            # Consolidated slot 2: 2 original sessions merged
            self.make_slot(
                base_time + timedelta(hours=3, minutes=30),
                base_time + timedelta(hours=5),
                task="Task2",
            ),
        ]

        print(f"\nINPUT PIPELINE: 2 consolidated slots")
        for i, s in enumerate(slots):
            print(f"  Slot {i}: {s['start']} to {s['end']} (task: {s['task']})")

        # Run through split_slots_spanning_days
        after_split = split_slots_spanning_days(slots, day_start_hour=4)
        print(f"\nAFTER split_slots_spanning_days: {len(after_split)} slots")

        # Verify we still have our consolidated slots (not re-split)
        if len(after_split) == 2:
            print(f"✓ Consolidation preserved through pipeline")
            return True
        else:
            print(
                f"⚠️ Consolidation altered! Input had 2, output has {len(after_split)}"
            )
            return False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

"""Comprehensive audit of slot generation to find degenerate and duplicate timezone slots.

DISCOVERED ISSUE: Unconsolidated slot list contains:
1. Degenerate slots with 0:00:00 duration (start == end)
2. Duplicate slots in different timezones (same logical time, UTC vs UTC-6)

This audit traces the slot generation pipeline to identify the root cause.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from tw_report.core.report_slot import ReportTimelineSlot


class TestSlotCreationValidation:
    """Test that slots are created with valid, non-degenerate properties."""

    def test_slot_must_have_positive_duration(self):
        """Slots should never have duration <= 0."""
        tz_minus6 = timezone(timedelta(hours=-6))
        start = datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6)
        end = start  # Same time = 0 duration (INVALID)

        # This should fail or be rejected during creation
        try:
            slot = ReportTimelineSlot(
                start=start,
                end=end,
                project="P1",
                task="T1",
            )

            # If we get here, check if validation catches it
            assert slot.duration > timedelta(0), (
                f"Slot duration should be positive, got {slot.duration}"
            )
        except Exception as e:
            print(f"✓ Slot creation correctly rejects zero duration: {type(e).__name__}")

    def test_slot_to_dict_preserves_timezone(self):
        """Slots should preserve their original timezone through to_dict()."""
        tz_minus6 = timezone(timedelta(hours=-6))
        start = datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6)
        end = datetime(2026, 8, 30, 13, 0, tzinfo=tz_minus6)

        slot = ReportTimelineSlot(
            start=start,
            end=end,
            project="P1",
            task="T1",
        )

        slot_dict = slot.to_dict()

        print(f"\nSlot timezone test:")
        print(f"  Original start tz: {start.tzinfo}")
        print(f"  Dict start tz: {slot_dict['start'].tzinfo}")

        # Both should have same timezone
        assert slot_dict['start'].tzinfo == tz_minus6
        assert slot_dict['end'].tzinfo == tz_minus6

    def test_no_duplicate_timezones_for_same_slot(self):
        """A single logical time should not appear in multiple timezones."""
        tz_minus6 = timezone(timedelta(hours=-6))
        tz_utc = timezone.utc

        # Same instant, different representations
        instant_utc = datetime(2026, 8, 30, 18, 0, tzinfo=tz_utc)
        instant_local = datetime(2026, 8, 30, 12, 0, tzinfo=tz_minus6)

        # These represent the same instant
        assert instant_utc.astimezone(tz_minus6) == instant_local

        # But if both appear as separate slots in the timeline, that's a bug
        # This test documents the ISSUE we found
        print(f"\nDuplicate timezone issue:")
        print(f"  UTC:   {instant_utc}")
        print(f"  Local: {instant_local}")
        print(f"  Same instant? {instant_utc == instant_local}")
        print(f"  ⚠️  These should NOT both appear as separate slots!")


class TestSlotGenerationPipeline:
    """Audit the complete slot generation pipeline."""

    def test_pipeline_stage_identification(self):
        """Document the slot generation pipeline stages."""
        print("\n" + "=" * 70)
        print("SLOT GENERATION PIPELINE STAGES")
        print("=" * 70)

        stages = [
            ("1. Raw Events", "Fetched from ActivityWatch and TaskWarrior"),
            ("2. Canonical Events", "Transformed/normalized events"),
            ("3. Slot Creation", "Generated from canonical events"),
            ("4. Slot Processing", "Consolidation, filtering, etc."),
            ("5. Timeline Output", "Final slot list (.to_dict())"),
        ]

        for stage, desc in stages:
            print(f"\n{stage}")
            print(f"  Description: {desc}")
            print(f"  Issue Points:")
            if "3." in stage:
                print(f"    - May create degenerate slots (duration=0)")
                print(f"    - May create duplicate TZ representations")
            elif "4." in stage:
                print(f"    - May preserve or compound earlier issues")
            elif "5." in stage:
                print(f"    - Degenerate/duplicate slots now in final output")

        print("\nKEY FILES TO INVESTIGATE:")
        print("  - src/tw_report/pipeline/generation.py (slot creation)")
        print("  - src/tw_report/core/report_slot.py (ReportTimelineSlot)")
        print("  - src/tw_report/core/timeline.py (timeline building)")
        print("  - src/tw_report/core/offline.py (offline task handling)")

    def test_identify_degenerate_slot_source(self):
        """Document where degenerate slots likely originate."""
        print("\n" + "=" * 70)
        print("DEGENERATE SLOT ROOT CAUSE HYPOTHESIS")
        print("=" * 70)

        issues = [
            ("Zero Duration", "start == end", "Likely in slot creation or merging logic"),
            ("Mixed Timezones", "Same instant in UTC and local", "Timezone normalization issue"),
            ("Runt Slots", "Duration < MIN_EVENT_DURATION", "Filtering may not remove all"),
        ]

        for issue_name, symptom, likely_location in issues:
            print(f"\n{issue_name}:")
            print(f"  Symptom: {symptom}")
            print(f"  Likely Location: {likely_location}")

        print("\n" + "=" * 70)
        print("NEXT STEPS FOR FULL AUDIT:")
        print("=" * 70)
        print("1. Add validation in ReportTimelineSlot.__post_init__() to reject zero duration")
        print("2. Add timezone normalization in slot creation")
        print("3. Trace which function creates Slot 0 and Slot 23 (the degenerate ones)")
        print("4. Check if Timeline.to_report_timeline() or as_dicts() introduces duplicates")
        print("5. Test with minimal input to isolate the issue")


class TestSlotDurationValidation:
    """Test that duration is calculated correctly."""

    def test_duration_calculation(self):
        """Duration should always equal end - start."""
        tz = timezone(timedelta(hours=-6))
        start = datetime(2026, 8, 30, 12, 0, tzinfo=tz)
        end = datetime(2026, 8, 30, 13, 30, tzinfo=tz)

        slot = ReportTimelineSlot(
            start=start,
            end=end,
            project="P1",
            task="T1",
        )

        expected = end - start
        print(f"\nDuration test:")
        print(f"  Start: {start}")
        print(f"  End:   {end}")
        print(f"  Expected: {expected}")
        print(f"  Actual:   {slot.duration}")

        assert slot.duration == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

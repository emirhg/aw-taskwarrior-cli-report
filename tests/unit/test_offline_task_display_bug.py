"""Test to reproduce and catch the offline_task display double-counting bug."""
import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.timeline import TimelineSlot
from tw_report.core.report_slot import ReportTimelineSlot, ReportEntries, DisplayColumns


class TestOfflineTaskDisplayBug:
    """Reproduce the bug where offline_task slots show 2x the actual offline time."""

    def test_offline_task_slot_display_correct(self):
        """A single offline_task slot should display correct OFFLINE time (not double-counted)."""
        # Create offline_task like generate_partitioned_task_slots does
        # Task period: 08:34 with ZERO windows (completely offline)
        ts = TimelineSlot(
            type="offline_task",
            start=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 24, 18, 34, 0, tzinfo=timezone.utc),
            duration=timedelta(hours=8, minutes=34),
            actual_duration=timedelta(0),  # No online activity
            productive_duration=timedelta(0),
            project="TestProject",
            task="TestTask",
            event_duration=timedelta(0),  # System completely offline
            offline_extension_duration=timedelta(hours=8, minutes=34),  # Full duration offline
        )

        # Convert to ReportTimelineSlot
        report_slot = ReportTimelineSlot.from_timeline_slot(ts)

        # Get DisplayColumns (what's shown in the report)
        display = DisplayColumns.from_slot_dict(
            report_slot.to_dict(),
            datetime(2026, 8, 24, 4, 0, 0),
            datetime(2026, 8, 24, 12, 34, 0),
        )

        # Assertions
        assert display.offline_time == "08:34:00", f"Expected OFFLINE 08:34:00, got {display.offline_time}"
        assert display.active_time == "", f"Expected no ACTIVE time, got {display.active_time}"
        assert display.afk_time == "", f"Expected no AFK time, got {display.afk_time}"

    def test_consolidated_offline_task_display_correct(self):
        """After consolidation, offline_task should still show correct OFFLINE time."""
        # Single offline_task slot
        ts = TimelineSlot(
            type="offline_task",
            start=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 24, 18, 34, 0, tzinfo=timezone.utc),
            duration=timedelta(hours=8, minutes=34),
            actual_duration=timedelta(0),
            productive_duration=timedelta(0),
            project="TestProject",
            task="TestTask",
            event_duration=timedelta(0),
            offline_extension_duration=timedelta(hours=8, minutes=34),
        )

        report_slot = ReportTimelineSlot.from_timeline_slot(ts)
        entries = ReportEntries(slots_list=[report_slot])

        # Consolidate
        consolidated = entries.consolidate_by_task()

        # Get consolidated slot
        assert len(consolidated.slots()) == 1
        consolidated_slot = consolidated.slots()[0]

        # Display the consolidated slot
        display = DisplayColumns.from_slot_dict(
            consolidated_slot.to_dict(),
            datetime(2026, 8, 24, 4, 0, 0),
            datetime(2026, 8, 24, 12, 34, 0),
        )

        # Should still show correct values after consolidation
        assert display.offline_time == "08:34:00", (
            f"After consolidation: expected OFFLINE 08:34:00, got {display.offline_time}"
        )
        assert display.active_time == "", f"After consolidation: expected no ACTIVE, got {display.active_time}"

    def test_offline_task_field_accumulation_in_consolidation(self):
        """Verify that consolidation doesn't double-count offline_extension_duration."""
        # Single offline_task slot
        ts = TimelineSlot(
            type="offline_task",
            start=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 24, 18, 34, 0, tzinfo=timezone.utc),
            duration=timedelta(hours=8, minutes=34),
            actual_duration=timedelta(0),
            productive_duration=timedelta(0),
            project="TestProject",
            task="TestTask",
            event_duration=timedelta(0),
            offline_extension_duration=timedelta(hours=8, minutes=34),
        )

        report_slot = ReportTimelineSlot.from_timeline_slot(ts)
        entries = ReportEntries(slots_list=[report_slot])
        consolidated = entries.consolidate_by_task()

        # Check fields
        slot = consolidated.slots()[0]
        assert slot.offline_extension_duration == timedelta(
            hours=8, minutes=34
        ), f"Expected offline_extension_duration=08:34:00, got {slot.offline_extension_duration}"
        assert slot.actual_duration == timedelta(0), f"Expected actual_duration=0, got {slot.actual_duration}"
        assert slot.event_duration == timedelta(0), f"Expected event_duration=0, got {slot.event_duration}"

        # The OFFLINE display value should be the offline_extension_duration, not more
        # Formula: OFFLINE = offline_extension_duration (since that's set)
        # OR: OFFLINE = duration - event_duration = 08:34 - 0 = 08:34
        # Either way, should be 08:34, NOT 17:09
        assert slot.offline_extension_duration.total_seconds() == (
            8 * 3600 + 34 * 60
        ), "offline_extension_duration should be 08:34:00"

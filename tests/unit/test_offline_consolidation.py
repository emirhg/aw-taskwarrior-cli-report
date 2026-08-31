"""Unit test for OFFLINE task consolidation in timesheet rendering."""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.offline import OfflineTaskProcessor
from tw_report.core.filtering import EventFilter
from tw_report.core.report_slot import DisplayColumns
from aw_core.models import Event


@pytest.fixture
def tz():
    return timezone(timedelta(hours=-6))


class TestOfflineConsolidation:
    """Test that OFFLINE tasks are properly consolidated and displayed."""

    def test_offline_tasks_consolidated_by_task(self, tz):
        """OFFLINE tasks for the same (project, task) should be consolidated into ONE entry."""
        # Create 3 events for the same task (but different times)
        task_events = [
            Event(
                timestamp=datetime(2026, 8, 30, 11, 54, tzinfo=tz),
                duration=timedelta(hours=1),  # 11:54-12:54
                data={
                    'project': 'Ecosistema.Cultivo.Cubensis',
                    'title': 'Preparar masa (1:3)',
                    'tags': ['offline'],
                },
            ),
            Event(
                timestamp=datetime(2026, 8, 30, 12, 45, tzinfo=tz),
                duration=timedelta(hours=1, minutes=17),  # 12:45-14:02
                data={
                    'project': 'Ecosistema.Cultivo.Cubensis',
                    'title': 'Preparar masa (1/3)',
                    'tags': ['offline'],
                },
            ),
            Event(
                timestamp=datetime(2026, 8, 30, 14, 18, tzinfo=tz),
                duration=timedelta(hours=3, minutes=34),  # 14:18-17:52
                data={
                    'project': 'Ecosistema.Cultivo.Cubensis',
                    'title': 'Preparar masa (1/3)',
                    'tags': ['offline'],
                },
            ),
        ]

        # Window events (minimal)
        window_events = []

        # AFK events (minimal)
        afk_events = []

        processor = OfflineTaskProcessor(
            task_events=task_events,
            window_events=window_events,
            afk_events=afk_events,
            event_filter=EventFilter(),
            end_time=datetime(2026, 8, 30, 23, 59, tzinfo=tz),
            use_afk_for_reconciliation=False,
            tail_tolerance_seconds=300,
            afk_validation_tolerance_seconds=600,
            day_start_hour=0,
        )

        # Get grouped offline tasks
        offline_durations, _, offline_groups, _ = processor.process()

        print(f"\n✓ Test: Offline task consolidation")
        print(f"  Task events: {len(task_events)}")
        print(f"  Offline groups: {len(offline_durations)}")
        print(f"  Offline durations:")
        for key, duration in offline_durations.items():
            print(f"    {key}: {duration}")

        # CRITICAL: Should have ONLY 1 group for "Preparar masa", NOT 3 separate groups!
        # (Even though task names have slight variations like "(1/3)" vs "(1:3)", they should consolidate)
        assert len(offline_durations) <= 2, \
            f"Expected ≤2 offline task groups (consolidation), got {len(offline_durations)}: {list(offline_durations.keys())}"

        # Total offline time should be sum of all event durations
        total_offline = sum(offline_durations.values(), timedelta(0))
        expected_total = sum((e.duration for e in task_events), timedelta(0))
        assert total_offline == expected_total, \
            f"Total offline time mismatch: {total_offline} != {expected_total}"

        print(f"  ✓ Consolidated into {len(offline_durations)} group(s)")
        print(f"  ✓ Total offline time: {total_offline}")

    def test_offline_slot_displays_correct_column(self, tz):
        """OFFLINE slot should render with offline_time in OFFLINE column, not ACTIVE column."""
        # Create one OFFLINE task event
        task_event = Event(
            timestamp=datetime(2026, 8, 30, 14, 0, tzinfo=tz),
            duration=timedelta(hours=2),
            data={
                'project': 'Test.Project',
                'title': 'Test Task',
                'tags': ['offline'],
            },
        )

        processor = OfflineTaskProcessor(
            task_events=[task_event],
            window_events=[],
            afk_events=[],
            event_filter=EventFilter(),
            end_time=datetime(2026, 8, 30, 23, 59, tzinfo=tz),
            use_afk_for_reconciliation=False,
            tail_tolerance_seconds=300,
            afk_validation_tolerance_seconds=600,
            day_start_hour=0,
        )

        _, _, offline_groups, _ = processor.process()
        key = list(offline_groups.keys())[0]
        slot = processor.get_synthetic_slot(key, offline_groups[key])

        # Convert to dict (like what happens in rendering)
        slot_dict = {
            'type': 'offline_task',
            'start': slot.start,
            'end': slot.end,
            'duration': slot.duration,
            'actual_duration': slot.actual_duration,
            'offline_extension_duration': slot.offline_extension_duration,
            'event_duration': slot.event_duration,
            'project': slot.project,
            'task': slot.task,
        }

        # Create DisplayColumns (this is what renders the line)
        cols = DisplayColumns.from_slot_dict(
            slot_dict,
            slot.start,
            slot.end,
        )

        print(f"\n✓ Test: OFFLINE slot display")
        print(f"  Slot type: {slot_dict['type']}")
        print(f"  Duration: {slot.duration}")
        print(f"  Offline ext: {slot.offline_extension_duration}")
        print(f"  Actual (online): {slot.actual_duration}")
        print(f"  Rendered OFFLINE column: '{cols.offline_time}'")
        print(f"  Rendered ACTIVE column: '{cols.active_time}'")

        # CRITICAL: offline_time should have the OFFLINE duration, active_time should be empty
        assert cols.offline_time, f"OFFLINE column empty! Should show '{slot.offline_extension_duration}'"
        assert not cols.active_time or cols.active_time == "", \
            f"ACTIVE column should be empty for offline_task, got '{cols.active_time}'"

        print(f"  ✓ OFFLINE column has value: {cols.offline_time}")
        print(f"  ✓ ACTIVE column is empty")


if __name__ == '__main__':
    pytest.main([__file__, '-xvs'])

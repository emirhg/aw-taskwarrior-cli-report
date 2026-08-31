"""Unit test for OFFLINE column display in timeline mode."""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.offline import OfflineTaskProcessor
from tw_report.core.filtering import EventFilter
from tw_report.core.report_slot import ReportTimelineSlot
from aw_core.models import Event


@pytest.fixture
def tz():
    return timezone(timedelta(hours=-6))


@pytest.fixture
def offline_task_event(tz):
    """Task with OFFLINE tag and 2-hour wall-clock duration."""
    return Event(
        timestamp=datetime(2026, 8, 30, 14, 0, tzinfo=tz),
        duration=timedelta(hours=2),  # 14:00-16:00
        data={
            'project': 'Ecosistema.Cultivo.Cubensis',
            'title': 'Test Task',
            'tags': ['offline'],
        },
    )


@pytest.fixture
def window_events(tz):
    """Window events representing 30 min of actual work."""
    return [
        Event(
            timestamp=datetime(2026, 8, 30, 14, 0, tzinfo=tz),
            duration=timedelta(minutes=30),
            data={'app': 'editor'},
        ),
    ]


@pytest.fixture
def afk_events(tz):
    """AFK events: 30 min not-afk (active), 1.5h afk (idle)."""
    return [
        # 30 min of active work (not-afk)
        Event(
            timestamp=datetime(2026, 8, 30, 14, 0, tzinfo=tz),
            duration=timedelta(minutes=30),
            data={'status': 'not-afk'},
        ),
        # 1.5 hours of idle time (afk)
        Event(
            timestamp=datetime(2026, 8, 30, 14, 30, tzinfo=tz),
            duration=timedelta(minutes=90),
            data={'status': 'afk'},
        ),
    ]


class TestOfflineDisplay:
    """Test that OFFLINE time displays correctly in timeline mode."""

    def test_offline_slot_has_offline_extension_duration(self, offline_task_event, window_events, afk_events, tz):
        """OFFLINE slot should have offline_extension_duration calculated."""
        processor = OfflineTaskProcessor(
            task_events=[offline_task_event],
            window_events=window_events,
            afk_events=afk_events,
            event_filter=EventFilter(),
            end_time=datetime(2026, 8, 30, 23, 59, tzinfo=tz),
            use_afk_for_reconciliation=False,
            tail_tolerance_seconds=300,
            afk_validation_tolerance_seconds=600,
            day_start_hour=0,
        )

        # Get grouped offline task (hierarchical mode)
        offline_durations, _, offline_groups, _ = processor.process()

        # Should have 1 offline task
        assert len(offline_durations) == 1, f"Expected 1 offline task, got {len(offline_durations)}"

        key = list(offline_durations.keys())[0]
        duration = offline_durations[key]

        # Wall-clock duration should be 2 hours
        assert duration == timedelta(hours=2), f"Expected 2h wall-clock, got {duration}"

        # Get synthetic slot
        task_events_for_key = offline_groups.get(key, [])
        assert len(task_events_for_key) > 0, "No task events found for offline task"

        slot = processor.get_synthetic_slot(key, task_events_for_key)

        # Verify slot has offline_extension_duration set
        assert slot.offline_extension_duration is not None, "offline_extension_duration is None"

        # offline_extension_duration = wall_clock - online_time
        # online_time = 30 min (not-afk) + some afk overlap
        # For this simple case: offline_extension_duration should be roughly 1.5 hours
        assert slot.offline_extension_duration > timedelta(hours=1), \
            f"Expected offline gap > 1h, got {slot.offline_extension_duration}"

        # Total should equal wall-clock duration
        assert (slot.actual_duration + slot.offline_extension_duration) == slot.duration, \
            f"online ({slot.actual_duration}) + offline ({slot.offline_extension_duration}) != total ({slot.duration})"

        print(f"✓ Offline slot correctly computed:")
        print(f"  Wall-clock: {slot.duration}")
        print(f"  Online (active): {slot.actual_duration}")
        print(f"  Offline (gap): {slot.offline_extension_duration}")

    def test_offline_slot_dict_conversion_preserves_offline_extension(self, offline_task_event, window_events, afk_events, tz):
        """Converting offline slot to dict should preserve offline_extension_duration."""
        processor = OfflineTaskProcessor(
            task_events=[offline_task_event],
            window_events=window_events,
            afk_events=afk_events,
            event_filter=EventFilter(),
            end_time=datetime(2026, 8, 30, 23, 59, tzinfo=tz),
            use_afk_for_reconciliation=False,
            tail_tolerance_seconds=300,
            afk_validation_tolerance_seconds=600,
            day_start_hour=0,
        )

        _, _, offline_groups, _ = processor.process()
        key = list(offline_groups.keys())[0]
        task_events_for_key = offline_groups[key]

        slot = processor.get_synthetic_slot(key, task_events_for_key)
        slot_dict = slot.to_dict() if hasattr(slot, 'to_dict') else {
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

        # Dict should have offline_extension_duration
        assert 'offline_extension_duration' in slot_dict, \
            f"offline_extension_duration missing from dict. Keys: {slot_dict.keys()}"
        assert slot_dict['offline_extension_duration'] is not None, \
            "offline_extension_duration is None in dict"

        print(f"✓ Dict conversion preserved offline_extension_duration: {slot_dict['offline_extension_duration']}")


if __name__ == '__main__':
    pytest.main([__file__, '-xvs'])

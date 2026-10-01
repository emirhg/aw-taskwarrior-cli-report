"""
Unit tests for Timeline and TimelineSlot classes.

Tests cover:
- TimelineSlot creation and validation
- Timeline operations (add, query, aggregation)
- Dict conversion for backward compatibility
- Edge cases and time-based operations
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.timeline import TimelineSlot, Timeline


# Fixtures
@pytest.fixture
def tz_aware_dt():
    """Create timezone-aware datetime factory."""
    def _create(hour=10, minute=0, second=0):
        return datetime(2026, 6, 30, hour, minute, second, tzinfo=timezone.utc)
    return _create


@pytest.fixture
def sample_slot(tz_aware_dt):
    """Create a sample TimelineSlot."""
    return TimelineSlot(
        type="regular",
        start=tz_aware_dt(10),
        end=tz_aware_dt(12),
        project="TestProject",
        task="TestTask",
        duration=timedelta(hours=2),
        actual_duration=timedelta(hours=2),
    )


@pytest.fixture
def timeline():
    """Create an empty Timeline."""
    return Timeline()


# TimelineSlot Tests
class TestTimelineSlot:
    """Test TimelineSlot dataclass."""

    def test_creation_basic(self, tz_aware_dt):
        """Test basic slot creation."""
        slot = TimelineSlot(
            type="regular",
            start=tz_aware_dt(10),
            end=tz_aware_dt(12),
            project="ProjectA",
            task="TaskA",
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=2),
        )
        assert slot.type == "regular"
        assert slot.project == "ProjectA"
        assert slot.task == "TaskA"
        assert slot.duration == timedelta(hours=2)
        assert slot.actual_duration == timedelta(hours=2)

    def test_missing_actual_duration_raises(self, tz_aware_dt):
        """Test that actual_duration must be explicitly provided."""
        from tw_report.core.timeline import TimelineSlotValidationError
        with pytest.raises(TimelineSlotValidationError, match="missing required 'actual_duration'"):
            TimelineSlot(
                type="regular",
                start=tz_aware_dt(10),
                end=tz_aware_dt(12),
                project="ProjectA",
                task="TaskA",
                duration=timedelta(hours=2),
            )

    def test_actual_duration_explicit(self, tz_aware_dt):
        """Test explicit actual_duration is accepted."""
        slot = TimelineSlot(
            type="regular",
            start=tz_aware_dt(10),
            end=tz_aware_dt(12),
            project="ProjectA",
            task="TaskA",
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=1, minutes=30),
        )
        assert slot.actual_duration == timedelta(hours=1, minutes=30)

    def test_optional_fields(self, sample_slot):
        """Test optional fields default to None or empty."""
        assert sample_slot.afk_duration is None
        assert sample_slot.event_duration is None
        assert sample_slot.offline_extension_duration is None
        assert sample_slot.tags == []
        assert sample_slot.categories == []

    def test_overlaps_true(self, tz_aware_dt):
        """Test overlaps() returns True for overlapping slots."""
        slot1 = TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        slot2 = TimelineSlot(
            type="task", start=tz_aware_dt(11), end=tz_aware_dt(13),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        assert slot1.overlaps(slot2)
        assert slot2.overlaps(slot1)

    def test_overlaps_false(self, tz_aware_dt):
        """Test overlaps() returns False for non-overlapping slots."""
        slot1 = TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        slot2 = TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(15),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        assert not slot1.overlaps(slot2)
        assert not slot2.overlaps(slot1)

    def test_overlaps_adjacent(self, tz_aware_dt):
        """Test overlaps() returns False for adjacent slots."""
        slot1 = TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        slot2 = TimelineSlot(
            type="task", start=tz_aware_dt(12), end=tz_aware_dt(14),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        assert not slot1.overlaps(slot2)
        assert not slot2.overlaps(slot1)

    def test_contains_true(self, tz_aware_dt):
        """Test contains() returns True for times within slot."""
        slot = TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        assert slot.contains(tz_aware_dt(10))
        assert slot.contains(tz_aware_dt(11))
        assert slot.contains(tz_aware_dt(11, 59))

    def test_contains_false(self, tz_aware_dt):
        """Test contains() returns False for times outside slot."""
        slot = TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        assert not slot.contains(tz_aware_dt(9))
        assert not slot.contains(tz_aware_dt(12))
        assert not slot.contains(tz_aware_dt(13))

    def test_to_dict(self, sample_slot):
        """Test conversion to dict."""
        d = sample_slot.to_dict()
        assert d["type"] == "regular"
        assert d["project"] == "TestProject"
        assert d["task"] == "TestTask"
        assert d["duration"] == timedelta(hours=2)
        assert d["actual_duration"] == timedelta(hours=2)

    def test_to_dict_with_optional_fields(self, tz_aware_dt):
        """Test dict conversion includes optional fields."""
        slot = TimelineSlot(
            type="offline_task",
            start=tz_aware_dt(10),
            end=tz_aware_dt(14),
            project="P",
            task="T",
            duration=timedelta(hours=4),
            actual_duration=timedelta(hours=2),
            afk_duration=timedelta(hours=1),
            event_duration=timedelta(hours=2),
            tags=["offline", "important"],
        )
        d = slot.to_dict()
        assert d["afk_duration"] == timedelta(hours=1)
        assert d["event_duration"] == timedelta(hours=2)
        assert d["tags"] == ["offline", "important"]

    def test_from_dict(self, tz_aware_dt):
        """Test creation from dict."""
        d = {
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "project": "ProjectA",
            "task": "TaskA",
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=1, minutes=30),
        }
        slot = TimelineSlot.from_dict(d)
        assert slot.type == "task"
        assert slot.project == "ProjectA"
        assert slot.actual_duration == timedelta(hours=1, minutes=30)

    def test_from_dict_missing_actual_duration_raises(self, tz_aware_dt):
        """Test from_dict raises when actual_duration is missing."""
        from tw_report.core.timeline import TimelineSlotValidationError
        d = {
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "duration": timedelta(hours=2),
        }
        with pytest.raises(TimelineSlotValidationError, match="missing required key 'actual_duration'"):
            TimelineSlot.from_dict(d)

    def test_from_dict_derives_end_when_missing(self, tz_aware_dt):
        """Test from_dict derives end from start+duration when not provided."""
        d = {
            "type": "regular",
            "start": tz_aware_dt(10),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=1, minutes=30),
        }
        slot = TimelineSlot.from_dict(d)
        assert slot.end == tz_aware_dt(12)
        assert slot.type == "regular"
        assert slot.project == ""
        assert slot.task == ""

    def test_roundtrip_dict_conversion(self, tz_aware_dt):
        """Test slot -> dict -> slot roundtrip."""
        original = TimelineSlot(
            type="offline_task",
            start=tz_aware_dt(10),
            end=tz_aware_dt(14),
            project="P",
            task="T",
            duration=timedelta(hours=4),
            actual_duration=timedelta(hours=3),
            productive_duration=timedelta(hours=3),
            event_duration=timedelta(hours=3),
            tags=["offline"],
        )
        d = original.to_dict()
        restored = TimelineSlot.from_dict(d)
        assert restored.type == original.type
        assert restored.project == original.project
        assert restored.duration == original.duration
        assert restored.actual_duration == original.actual_duration
        assert restored.event_duration == original.event_duration
        assert restored.tags == original.tags

    def test_end_duration_mismatch_raises(self, tz_aware_dt):
        """Test that mismatched end and start+duration raises an error."""
        from tw_report.core.timeline import TimelineSlotValidationError
        with pytest.raises(TimelineSlotValidationError, match="inconsistent with"):
            TimelineSlot(
                type="regular",
                start=tz_aware_dt(10),
                end=tz_aware_dt(15),  # Should be 12:00, not 15:00
                project="P",
                task="T",
                duration=timedelta(hours=2),
                actual_duration=timedelta(hours=2),
            )

    def test_end_within_tolerance_accepted(self, tz_aware_dt):
        """Test that minor end/start+duration differences within tolerance are accepted."""
        # Create a slot with end 0.5 seconds off from start+duration
        start = tz_aware_dt(10)
        slot = TimelineSlot(
            type="regular",
            start=start,
            end=start + timedelta(hours=2, milliseconds=500),  # 0.5s tolerance
            project="P",
            task="T",
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=2),
        )
        assert slot.end > start + timedelta(hours=2)

    def test_offline_task_missing_event_duration_raises(self, tz_aware_dt):
        """Test that offline_task slots must have event_duration."""
        from tw_report.core.timeline import TimelineSlotValidationError
        with pytest.raises(TimelineSlotValidationError, match="missing required 'event_duration'"):
            TimelineSlot(
                type="offline_task",
                start=tz_aware_dt(10),
                end=tz_aware_dt(12),
                project="P",
                task="T",
                duration=timedelta(hours=2),
                actual_duration=timedelta(hours=1),
                # Missing event_duration
            )

    def test_offline_task_with_event_duration_ok(self, tz_aware_dt):
        """Test that offline_task slots with event_duration construct fine."""
        slot = TimelineSlot(
            type="offline_task",
            start=tz_aware_dt(10),
            end=tz_aware_dt(12),
            project="P",
            task="T",
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=1),
            event_duration=timedelta(hours=1),
        )
        assert slot.event_duration == timedelta(hours=1)

    def test_from_dict_missing_type_raises(self, tz_aware_dt):
        """Test from_dict raises when type is missing."""
        from tw_report.core.timeline import TimelineSlotValidationError
        d = {
            "start": tz_aware_dt(10),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
        }
        with pytest.raises(TimelineSlotValidationError, match="missing required key 'type'"):
            TimelineSlot.from_dict(d)

    def test_from_dict_missing_duration_raises(self, tz_aware_dt):
        """Test from_dict raises when duration is missing."""
        from tw_report.core.timeline import TimelineSlotValidationError
        d = {
            "type": "regular",
            "start": tz_aware_dt(10),
            "actual_duration": timedelta(hours=2),
        }
        with pytest.raises(TimelineSlotValidationError, match="missing required key 'duration'"):
            TimelineSlot.from_dict(d)

    def test_from_dict_project_task_defaults_empty(self, tz_aware_dt):
        """Test that project/task remain optional with empty string defaults."""
        d = {
            "type": "regular",
            "start": tz_aware_dt(10),
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
        }
        slot = TimelineSlot.from_dict(d)
        assert slot.project == ""
        assert slot.task == ""


# Timeline Tests
class TestTimeline:
    """Test Timeline class."""

    def test_creation_empty(self, timeline):
        """Test creating empty timeline."""
        assert timeline.count() == 0
        assert len(timeline) == 0
        assert timeline.get_slots() == []

    def test_add_single_slot(self, timeline, sample_slot):
        """Test adding a single slot."""
        timeline.add_slot(sample_slot)
        assert timeline.count() == 1
        assert timeline.get_slots()[0] == sample_slot

    def test_add_multiple_slots(self, timeline, tz_aware_dt):
        """Test adding multiple slots."""
        slots = [
            TimelineSlot(
                type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
                project="P", task="T1", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
            ),
            TimelineSlot(
                type="task", start=tz_aware_dt(13), end=tz_aware_dt(15),
                project="P", task="T2", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
            ),
        ]
        timeline.add_slots(slots)
        assert timeline.count() == 2

    def test_slots_auto_sorted_on_add(self, timeline, tz_aware_dt):
        """Test slots are auto-sorted when added out of order."""
        slot1 = TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(15),
            project="P", task="T1", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        slot2 = TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T2", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        )
        timeline.add_slot(slot1)
        timeline.add_slot(slot2)

        slots = timeline.get_slots()
        assert slots[0].start < slots[1].start

    def test_get_slots_as_dicts(self, timeline, sample_slot):
        """Test retrieving slots as dicts."""
        timeline.add_slot(sample_slot)
        dicts = timeline.get_slots_as_dicts()
        assert len(dicts) == 1
        assert dicts[0]["type"] == "regular"
        assert dicts[0]["project"] == "TestProject"

    def test_add_from_dict(self, timeline, tz_aware_dt):
        """Test adding slot from dict."""
        slot_dict = {
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "project": "P",
            "task": "T",
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
        }
        timeline.add_from_dict(slot_dict)
        assert timeline.count() == 1
        assert timeline.get_slots()[0].project == "P"

    def test_get_slots_by_project(self, timeline, tz_aware_dt):
        """Test querying slots by project."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="ProjectA", task="T1", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(15),
            project="ProjectB", task="T2", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))

        slots_a = timeline.get_slots_by_project("ProjectA")
        assert len(slots_a) == 1
        assert slots_a[0].project == "ProjectA"

    def test_get_slots_by_task(self, timeline, tz_aware_dt):
        """Test querying slots by task."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="TaskA", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(15),
            project="P", task="TaskB", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))

        slots = timeline.get_slots_by_task("P", "TaskA")
        assert len(slots) == 1
        assert slots[0].task == "TaskA"

    def test_get_slots_by_type(self, timeline, tz_aware_dt):
        """Test querying slots by type."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))
        timeline.add_slot(TimelineSlot(
            type="afk", start=tz_aware_dt(12), end=tz_aware_dt(13),
            project="", task="", duration=timedelta(hours=1), actual_duration=timedelta(hours=1)
        ))

        task_slots = timeline.get_slots_by_type("task")
        afk_slots = timeline.get_slots_by_type("afk")
        assert len(task_slots) == 1
        assert len(afk_slots) == 1

    def test_get_slots_in_range(self, timeline, tz_aware_dt):
        """Test querying slots in time range."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T1", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(14), end=tz_aware_dt(16),
            project="P", task="T2", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))

        # Range that overlaps first slot
        slots = timeline.get_slots_in_range(tz_aware_dt(11), tz_aware_dt(12, 30))
        assert len(slots) == 1
        assert slots[0].task == "T1"

    def test_total_duration(self, timeline, tz_aware_dt):
        """Test total duration aggregation."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T1", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(16),
            project="P", task="T2", duration=timedelta(hours=3), actual_duration=timedelta(hours=3)
        ))

        assert timeline.total_duration() == timedelta(hours=5)

    def test_total_actual_duration(self, timeline, tz_aware_dt):
        """Test total actual duration aggregation."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T1", duration=timedelta(hours=2),
            actual_duration=timedelta(hours=1, minutes=30)
        ))
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(16),
            project="P", task="T2", duration=timedelta(hours=3),
            actual_duration=timedelta(hours=2, minutes=45)
        ))

        assert timeline.total_actual_duration() == timedelta(hours=4, minutes=15)

    def test_total_productive_duration(self, timeline, tz_aware_dt):
        """Test total productive duration aggregation."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T1", duration=timedelta(hours=2),
            actual_duration=timedelta(hours=2), productive_duration=timedelta(hours=1, minutes=45)
        ))
        timeline.add_slot(TimelineSlot(
            type="afk", start=tz_aware_dt(12), end=tz_aware_dt(13),
            project="", task="", duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1), productive_duration=timedelta(0)
        ))

        assert timeline.total_productive_duration() == timedelta(hours=1, minutes=45)

    def test_iteration(self, timeline, tz_aware_dt):
        """Test iterating over timeline."""
        slots = [
            TimelineSlot(
                type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
                project="P", task="T1", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
            ),
            TimelineSlot(
                type="task", start=tz_aware_dt(13), end=tz_aware_dt(15),
                project="P", task="T2", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
            ),
        ]
        timeline.add_slots(slots)

        count = 0
        for slot in timeline:
            count += 1
        assert count == 2

    def test_len(self, timeline, sample_slot):
        """Test len() operator."""
        assert len(timeline) == 0
        timeline.add_slot(sample_slot)
        assert len(timeline) == 1

    def test_repr(self, timeline, tz_aware_dt):
        """Test string representation."""
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(10), end=tz_aware_dt(12),
            project="P", task="T", duration=timedelta(hours=2), actual_duration=timedelta(hours=2)
        ))
        repr_str = repr(timeline)
        assert "Timeline" in repr_str
        assert "1 slots" in repr_str


# Integration Tests
class TestTimelineIntegration:
    """Integration tests for Timeline workflow."""

    def test_realistic_day_workflow(self, timeline, tz_aware_dt):
        """Test realistic day of work with multiple tasks."""
        # Morning: focused work
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(9), end=tz_aware_dt(12),
            project="ProjectA", task="TaskA", duration=timedelta(hours=3),
            actual_duration=timedelta(hours=3), productive_duration=timedelta(hours=2, minutes=45)
        ))
        # Lunch break
        timeline.add_slot(TimelineSlot(
            type="afk", start=tz_aware_dt(12), end=tz_aware_dt(13),
            project="", task="", duration=timedelta(hours=1), actual_duration=timedelta(hours=1)
        ))
        # Afternoon: different task
        timeline.add_slot(TimelineSlot(
            type="task", start=tz_aware_dt(13), end=tz_aware_dt(17),
            project="ProjectB", task="TaskB", duration=timedelta(hours=4),
            actual_duration=timedelta(hours=4), productive_duration=timedelta(hours=3, minutes=30)
        ))

        assert timeline.count() == 3
        assert timeline.total_duration() == timedelta(hours=8)
        assert timeline.total_productive_duration() == timedelta(hours=6, minutes=15)

        # Query by project
        project_a_slots = timeline.get_slots_by_project("ProjectA")
        assert len(project_a_slots) == 1

        # Query by type
        work_slots = timeline.get_slots_by_type("task")
        assert len(work_slots) == 2

    def test_offline_task_workflow(self, timeline, tz_aware_dt):
        """Test offline task with special fields."""
        # Session 1: afternoon offline work
        timeline.add_slot(TimelineSlot(
            type="offline_task",
            start=tz_aware_dt(13),
            end=tz_aware_dt(17),
            project="ProjectA",
            task="OfflineTaskA",
            duration=timedelta(hours=4),
            actual_duration=timedelta(hours=4),
            productive_duration=timedelta(hours=4),
            event_duration=timedelta(hours=1, minutes=52),
            tags=["offline", "focus"],
        ))
        # Gap with other task
        timeline.add_slot(TimelineSlot(
            type="task",
            start=tz_aware_dt(18),
            end=tz_aware_dt(19),
            project="ProjectB",
            task="TaskB",
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
        ))
        # Session 2: evening offline work
        timeline.add_slot(TimelineSlot(
            type="offline_task",
            start=tz_aware_dt(20),
            end=tz_aware_dt(20) + timedelta(hours=3, minutes=24),
            project="ProjectA",
            task="OfflineTaskA",
            duration=timedelta(hours=3, minutes=24),
            actual_duration=timedelta(hours=3, minutes=24),
            productive_duration=timedelta(hours=3, minutes=24),
            event_duration=timedelta(0),
            tags=["offline"],
        ))

        # Query offline tasks for project
        offline = timeline.get_slots_by_type("offline_task")
        assert len(offline) == 2
        assert offline[0].event_duration == timedelta(hours=1, minutes=52)
        assert offline[1].event_duration == timedelta(0)

    def test_backward_compatibility(self, tz_aware_dt):
        """Test that dict-based workflow still works."""
        timeline = Timeline()

        # Old code might pass dicts
        old_format_slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(12),
                "project": "P",
                "task": "T1",
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
            },
            {
                "type": "task",
                "start": tz_aware_dt(13),
                "end": tz_aware_dt(15),
                "project": "P",
                "task": "T2",
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "afk_duration": timedelta(minutes=30),
            },
        ]

        for slot_dict in old_format_slots:
            timeline.add_from_dict(slot_dict)

        # Get them back as dicts
        retrieved = timeline.get_slots_as_dicts()
        assert len(retrieved) == 2
        assert retrieved[0]["project"] == "P"
        assert retrieved[1]["afk_duration"] == timedelta(minutes=30)

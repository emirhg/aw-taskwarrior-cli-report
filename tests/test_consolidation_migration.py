"""
Unit tests for TimelineSlotManager backward compatibility after Timeline migration.

These tests ensure that TimelineSlotManager continues to work exactly the same
way after being refactored to use Timeline internally.
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.consolidation import TimelineSlotManager
from unittest.mock import Mock


@pytest.fixture
def tz_aware_dt():
    """Create timezone-aware datetime factory."""
    def _create(hour=10, minute=0, second=0):
        return datetime(2026, 6, 30, hour, minute, second, tzinfo=timezone.utc)
    return _create


@pytest.fixture
def mock_dependencies():
    """Create mock category manager and event filter."""
    category_manager = Mock()
    event_filter = Mock()
    event_filter.should_include_entry.return_value = True
    return category_manager, event_filter


@pytest.fixture
def manager(mock_dependencies):
    """Create a TimelineSlotManager instance."""
    category_manager, event_filter = mock_dependencies
    return TimelineSlotManager(category_manager, event_filter)


class TestTimelineSlotManagerBackwardCompatibility:
    """Test that TimelineSlotManager still works the same after Timeline migration."""

    def test_add_slots_basic(self, manager, tz_aware_dt):
        """Test adding slots works as before."""
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(12),
                "project": "ProjectA",
                "task": "TaskA",
                "duration": timedelta(hours=2),
            },
            {
                "type": "task",
                "start": tz_aware_dt(13),
                "end": tz_aware_dt(15),
                "project": "ProjectB",
                "task": "TaskB",
                "duration": timedelta(hours=2),
            },
        ]
        manager.add_slots(slots)
        assert len(manager.get_slots()) == 2

    def test_get_slots_returns_dicts(self, manager, tz_aware_dt):
        """Test that get_slots() returns dicts, not TimelineSlot objects."""
        slots = [{
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "project": "P",
            "task": "T",
            "duration": timedelta(hours=2),
        }]
        manager.add_slots(slots)
        result = manager.get_slots()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)
        assert result[0]["project"] == "P"

    def test_slots_property_getter(self, manager, tz_aware_dt):
        """Test slots property getter returns dicts."""
        slots = [{
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "project": "P",
            "task": "T",
            "duration": timedelta(hours=2),
        }]
        manager.add_slots(slots)
        assert len(manager.slots) == 1
        assert isinstance(manager.slots[0], dict)

    def test_slots_property_setter(self, manager, tz_aware_dt):
        """Test slots property setter recreates timeline."""
        original_slots = [{
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "project": "P",
            "task": "T",
            "duration": timedelta(hours=2),
        }]
        manager.slots = original_slots
        assert len(manager.get_slots()) == 1
        assert manager.get_slots()[0]["project"] == "P"

    def test_consolidate_basic(self, manager, tz_aware_dt):
        """Test consolidate() works as before."""
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(11),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
                "categories": [],
            },
            {
                "type": "task",
                "start": tz_aware_dt(11),
                "end": tz_aware_dt(12),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
                "categories": [],
            },
        ]
        manager.add_slots(slots)
        consolidated = manager.consolidate()
        # Should consolidate 2 slots into 1
        assert len(consolidated) == 1
        assert consolidated[0]["project"] == "P"
        assert consolidated[0]["task"] == "T"
        assert consolidated[0]["duration"] == timedelta(hours=2)

    def test_consolidate_with_different_tasks(self, manager, tz_aware_dt):
        """Test consolidate() doesn't merge different tasks."""
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(11),
                "project": "P",
                "task": "T1",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
                "categories": [],
            },
            {
                "type": "task",
                "start": tz_aware_dt(11),
                "end": tz_aware_dt(12),
                "project": "P",
                "task": "T2",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
                "categories": [],
            },
        ]
        manager.add_slots(slots)
        consolidated = manager.consolidate()
        # Should keep as 2 slots
        assert len(consolidated) == 2

    def test_consolidate_with_offline_gaps(self, manager, tz_aware_dt):
        """Test consolidate() handles offline gaps correctly (same task resumes)."""
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(11),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
                "categories": [],
            },
            {
                "type": "offline",
                "start": tz_aware_dt(11),
                "end": tz_aware_dt(12),
                "project": "",
                "task": "",
                "duration": timedelta(hours=1),
                "categories": [],
            },
            {
                "type": "task",
                "start": tz_aware_dt(12),
                "end": tz_aware_dt(13),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
                "categories": [],
            },
        ]
        manager.add_slots(slots)
        consolidated = manager.consolidate()
        # When same task resumes after offline gap, gap is not emitted
        # and everything is merged together
        assert len(consolidated) == 1
        assert consolidated[0]["project"] == "P"
        assert consolidated[0]["task"] == "T"

    def test_apply_filters(self, manager, tz_aware_dt):
        """Test apply_filters() modifies slots in place."""
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(11),
                "project": "ProjectA",
                "task": "T",
                "duration": timedelta(hours=1),
            },
            {
                "type": "task",
                "start": tz_aware_dt(11),
                "end": tz_aware_dt(12),
                "project": "ProjectB",
                "task": "T",
                "duration": timedelta(hours=1),
            },
        ]
        manager.add_slots(slots)
        assert len(manager.get_slots()) == 2

        # Filter to only include ProjectA
        def filter_func(entry, entry_type):
            return entry.get("project") == "ProjectA"

        manager.event_filter.should_include_entry.side_effect = filter_func
        manager.apply_filters()

        assert len(manager.get_slots()) == 1
        assert manager.get_slots()[0]["project"] == "ProjectA"

    def test_merge_by_project_date(self, manager, tz_aware_dt):
        """Test merge_by_project_date() works as before."""
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(11),
                "project": "P",
                "task": "T1",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
            },
            {
                "type": "task",
                "start": tz_aware_dt(11),
                "end": tz_aware_dt(12),
                "project": "P",
                "task": "T2",
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(hours=1),
            },
        ]
        manager.add_slots(slots)
        merged = manager.merge_by_project_date()
        # Should merge both into one (same date, same project)
        assert len(merged) == 1
        assert merged[0]["project"] == "P"
        assert merged[0]["duration"] == timedelta(hours=2)

    def test_slots_auto_sorted(self, manager, tz_aware_dt):
        """Test that slots are auto-sorted when added."""
        # Add slots out of order
        slots = [
            {
                "type": "task",
                "start": tz_aware_dt(13),
                "end": tz_aware_dt(14),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
            },
            {
                "type": "task",
                "start": tz_aware_dt(10),
                "end": tz_aware_dt(11),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
            },
            {
                "type": "task",
                "start": tz_aware_dt(11),
                "end": tz_aware_dt(12),
                "project": "P",
                "task": "T",
                "duration": timedelta(hours=1),
            },
        ]
        manager.add_slots(slots)
        result = manager.get_slots()
        # Should be sorted by start time
        assert result[0]["start"] < result[1]["start"] < result[2]["start"]

    def test_empty_slots_consolidate(self, manager):
        """Test consolidate() on empty slots."""
        consolidated = manager.consolidate()
        assert consolidated == []

    def test_empty_slots_merge_by_project_date(self, manager):
        """Test merge_by_project_date() on empty slots."""
        merged = manager.merge_by_project_date()
        assert merged == []

    def test_roundtrip_slots_property(self, manager, tz_aware_dt):
        """Test setting and getting slots through property."""
        original_slots = [{
            "type": "task",
            "start": tz_aware_dt(10),
            "end": tz_aware_dt(12),
            "project": "P",
            "task": "T",
            "duration": timedelta(hours=2),
            "actual_duration": timedelta(hours=2),
            "productive_duration": timedelta(hours=1, minutes=30),
            "afk_duration": timedelta(minutes=30),
        }]

        manager.slots = original_slots
        retrieved = manager.slots

        assert len(retrieved) == 1
        assert retrieved[0]["project"] == "P"
        assert retrieved[0]["duration"] == timedelta(hours=2)
        assert retrieved[0].get("afk_duration") == timedelta(minutes=30)

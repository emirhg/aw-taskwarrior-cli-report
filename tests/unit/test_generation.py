"""
Unit tests for timeline data generation (tw_report.pipeline.generation).

These characterization tests capture the current behavior of generate_timeline_data
and generate_afk_and_offline_slots for later extraction and testing.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest
from aw_core.models import Event

from tw_report.core.aw_events import AFKEvent
from tw_report.core.filtering import NO_PROJECT, NO_TASK

UTC = timezone.utc


def make_datetime(year: int, month: int, day: int,
                  hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Helper to create UTC datetime objects."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def make_event(timestamp: datetime, duration: timedelta, data: Dict) -> Event:
    """Helper to create ActivityWatch Event objects."""
    return Event(timestamp=timestamp, duration=duration, data=data)


def make_afk_event(timestamp: datetime, duration: timedelta, status: str = "afk") -> AFKEvent:
    """Helper to create AFKEvent objects."""
    return AFKEvent(timestamp=timestamp, duration=duration, data={"status": status})


class TestMergeOverlappingEvents:
    """Test _merge_overlapping_events helper function."""

    @pytest.fixture
    def base_time(self):
        return make_datetime(2026, 6, 27, 10, 0)

    def test_empty_list(self):
        """Empty event list should return empty."""
        from tw_report.pipeline.generation import _merge_overlapping_events
        result = _merge_overlapping_events([])
        assert result == []

    def test_single_event(self, base_time):
        """Single event should pass through unchanged."""
        from tw_report.pipeline.generation import _merge_overlapping_events
        event = make_event(base_time, timedelta(hours=1), {"status": "afk"})
        result = _merge_overlapping_events([event])
        assert len(result) == 1
        assert result[0].timestamp == event.timestamp
        assert result[0].duration == event.duration

    def test_non_overlapping_events(self, base_time):
        """Non-overlapping events should remain separate."""
        from tw_report.pipeline.generation import _merge_overlapping_events
        event1 = make_event(base_time, timedelta(hours=1), {"status": "afk"})
        event2 = make_event(base_time + timedelta(hours=2), timedelta(hours=1), {"status": "afk"})
        result = _merge_overlapping_events([event1, event2])
        assert len(result) == 2

    def test_overlapping_events_merge(self, base_time):
        """Overlapping events should be merged into single event."""
        from tw_report.pipeline.generation import _merge_overlapping_events
        # Event 1: 10:00-11:00
        event1 = make_event(base_time, timedelta(hours=1), {"status": "afk"})
        # Event 2: 10:30-11:30 (overlaps with event 1)
        event2 = make_event(base_time + timedelta(minutes=30), timedelta(hours=1), {"status": "afk"})
        result = _merge_overlapping_events([event1, event2])
        assert len(result) == 1
        # Merged event should span from start of first to end of last
        assert result[0].timestamp == base_time
        assert result[0].duration == timedelta(hours=1, minutes=30)

    def test_adjacent_events_merge(self, base_time):
        """Adjacent events should be merged."""
        from tw_report.pipeline.generation import _merge_overlapping_events
        # Event 1: 10:00-11:00
        event1 = make_event(base_time, timedelta(hours=1), {"status": "afk"})
        # Event 2: 11:00-12:00 (adjacent, same start as event1's end)
        event2 = make_event(base_time + timedelta(hours=1), timedelta(hours=1), {"status": "afk"})
        result = _merge_overlapping_events([event1, event2])
        assert len(result) == 1
        assert result[0].timestamp == base_time
        assert result[0].duration == timedelta(hours=2)

    def test_multiple_merges(self, base_time):
        """Multiple overlapping sequences should be handled correctly."""
        from tw_report.pipeline.generation import _merge_overlapping_events
        # Three events that form two overlapping sequences
        event1 = make_event(base_time, timedelta(hours=1), {"status": "afk"})  # 10:00-11:00
        event2 = make_event(base_time + timedelta(minutes=30), timedelta(hours=1), {"status": "afk"})  # 10:30-11:30
        event3 = make_event(base_time + timedelta(hours=3), timedelta(hours=1), {"status": "afk"})  # 13:00-14:00
        result = _merge_overlapping_events([event1, event2, event3])
        assert len(result) == 2
        assert result[0].timestamp == base_time
        assert result[0].duration == timedelta(hours=1, minutes=30)
        assert result[1].timestamp == base_time + timedelta(hours=3)


class TestGenerateAfkAndOfflineSlots:
    """Test generate_afk_and_offline_slots function."""

    @pytest.fixture
    def base_time(self):
        return make_datetime(2026, 6, 27, 10, 0)

    def test_empty_afk_events(self):
        """Empty AFK events should return empty slots."""
        from tw_report.pipeline.generation import generate_afk_and_offline_slots
        result = generate_afk_and_offline_slots([], None)
        assert result == []

    def test_afk_slot_basic(self, base_time):
        """Basic AFK slot creation from AFKEvent."""
        from tw_report.pipeline.generation import generate_afk_and_offline_slots
        afk_events = [
            make_afk_event(base_time, timedelta(minutes=10), "afk"),
            make_afk_event(base_time + timedelta(hours=1), timedelta(hours=1), "not-afk"),
        ]
        result = generate_afk_and_offline_slots(afk_events, None)
        assert len(result) == 1
        assert result[0]["type"] == "afk"
        assert result[0]["project"] == NO_PROJECT
        assert result[0]["task"] == NO_TASK
        assert result[0]["duration"] == timedelta(minutes=10)

    def test_afk_slot_with_task_overlap(self, base_time):
        """AFK slot should be skipped if it overlaps with a task (handled by partitioned_task_slots)."""
        from tw_report.pipeline.generation import generate_afk_and_offline_slots
        afk_events = [
            make_afk_event(base_time, timedelta(minutes=10), "afk"),
            make_afk_event(base_time + timedelta(hours=1), timedelta(hours=1), "not-afk"),
        ]
        task_events = [
            make_event(base_time - timedelta(minutes=5), timedelta(minutes=20),
                      {"project": "TestProj", "task": "TestTask"}),
        ]
        # AFK overlaps with task, so it should be skipped by generate_afk_and_offline_slots
        # (it will be handled by generate_partitioned_task_slots instead)
        result = generate_afk_and_offline_slots(afk_events, task_events)
        assert len(result) == 0  # Task-covered AFK is filtered out

    def test_multiple_afk_slots(self, base_time):
        """Multiple non-overlapping AFK events should create multiple slots."""
        from tw_report.pipeline.generation import generate_afk_and_offline_slots
        afk_events = [
            make_afk_event(base_time, timedelta(minutes=5), "afk"),
            make_afk_event(base_time + timedelta(minutes=10), timedelta(minutes=5), "afk"),
            make_afk_event(base_time + timedelta(hours=1), timedelta(hours=1), "not-afk"),
        ]
        result = generate_afk_and_offline_slots(afk_events, None)
        assert len(result) == 2

    def test_overlapping_afk_merged(self, base_time):
        """Overlapping AFK events should be merged before creating slots."""
        from tw_report.pipeline.generation import generate_afk_and_offline_slots
        afk_events = [
            make_afk_event(base_time, timedelta(minutes=10), "afk"),
            make_afk_event(base_time + timedelta(minutes=5), timedelta(minutes=10), "afk"),  # overlaps
            make_afk_event(base_time + timedelta(hours=1), timedelta(hours=1), "not-afk"),
        ]
        result = generate_afk_and_offline_slots(afk_events, None)
        # Should be merged into one slot instead of two
        assert len(result) == 1


class TestGenerateTimelineData:
    """Test generate_timeline_data function."""

    @pytest.fixture
    def base_time(self):
        return make_datetime(2026, 6, 27, 10, 0)

    @pytest.fixture
    def cat_score_map(self):
        return {
            "Coding": 100,
            "Email": 50,
            "Video": -50,
            "Unknown": 0,
        }

    def test_empty_report_events(self, cat_score_map):
        """Empty report events should return empty slots."""
        from tw_report.pipeline.generation import generate_timeline_data
        result = generate_timeline_data([], [], cat_score_map)
        assert result == []

    def test_single_window_event_basic(self, base_time, cat_score_map):
        """Single window event in not-afk period should create one slot."""
        from tw_report.pipeline.generation import generate_timeline_data
        from tw_report.core.categories import get_category_score

        window_event = make_event(
            base_time,
            timedelta(hours=1),
            {"app": "VSCode", "title": "code.py", "$category": ["Coding"]}
        )
        not_afk_event = make_event(
            base_time,
            timedelta(hours=1),
            {"status": "not-afk"}
        )
        task_event = make_event(
            base_time,
            timedelta(hours=1),
            {"project": "MyProject", "task": "MyTask"}
        )

        report_events = [
            {
                "event": window_event,
                "project": "MyProject",
                "task": "MyTask",
                "active_task": task_event,
            }
        ]

        result = generate_timeline_data(report_events, [not_afk_event], cat_score_map, get_category_score=get_category_score)
        assert len(result) == 1
        assert result[0]["type"] == "regular"
        assert result[0]["project"] == "MyProject"
        assert result[0]["task"] == "MyTask"
        assert result[0]["duration"] == timedelta(hours=1)

    def test_detail_level_1_no_categories(self, base_time, cat_score_map):
        """detail_level=1 should not include categories."""
        from tw_report.pipeline.generation import generate_timeline_data
        from tw_report.core.categories import get_category_score

        window_event = make_event(
            base_time,
            timedelta(hours=1),
            {"app": "VSCode", "$category": ["Coding"]}
        )
        not_afk_event = make_event(base_time, timedelta(hours=1), {"status": "not-afk"})
        task_event = make_event(base_time, timedelta(hours=1), {"project": "P", "task": "T"})

        report_events = [{
            "event": window_event,
            "project": "P",
            "task": "T",
            "active_task": task_event,
        }]

        result = generate_timeline_data(report_events, [not_afk_event], cat_score_map, detail_level=1, get_category_score=get_category_score)
        assert len(result) == 1
        assert "categories" not in result[0]

    def test_detail_level_3_with_categories(self, base_time, cat_score_map):
        """detail_level=3 should include categories."""
        from tw_report.pipeline.generation import generate_timeline_data
        from tw_report.core.categories import get_category_score

        window_event = make_event(
            base_time,
            timedelta(hours=1),
            {"app": "VSCode", "title": "code.py", "$category": ["Coding"]}
        )
        not_afk_event = make_event(base_time, timedelta(hours=1), {"status": "not-afk"})
        task_event = make_event(base_time, timedelta(hours=1), {"project": "P", "task": "T"})

        report_events = [{
            "event": window_event,
            "project": "P",
            "task": "T",
            "active_task": task_event,
        }]

        result = generate_timeline_data(report_events, [not_afk_event], cat_score_map, detail_level=3, get_category_score=get_category_score)
        assert len(result) == 1
        assert "categories" in result[0]
        assert len(result[0]["categories"]) > 0
        assert result[0]["categories"][0]["category"] == "Coding"

    def test_project_task_continuity_break(self, base_time, cat_score_map):
        """Project/task change should create new slots."""
        from tw_report.pipeline.generation import generate_timeline_data
        from tw_report.core.categories import get_category_score

        # Two window events in same not-afk period but different tasks
        window_event1 = make_event(
            base_time,
            timedelta(hours=1),
            {"app": "VSCode", "$category": ["Coding"]}
        )
        window_event2 = make_event(
            base_time + timedelta(hours=1),
            timedelta(hours=1),
            {"app": "Firefox", "$category": ["Email"]}
        )
        not_afk_event = make_event(
            base_time,
            timedelta(hours=2),
            {"status": "not-afk"}
        )
        task_event1 = make_event(base_time, timedelta(hours=1), {"project": "P1", "task": "T1"})
        task_event2 = make_event(base_time + timedelta(hours=1), timedelta(hours=1), {"project": "P2", "task": "T2"})

        report_events = [
            {"event": window_event1, "project": "P1", "task": "T1", "active_task": task_event1},
            {"event": window_event2, "project": "P2", "task": "T2", "active_task": task_event2},
        ]

        result = generate_timeline_data(report_events, [not_afk_event], cat_score_map, detail_level=1, get_category_score=get_category_score)
        # Should create two slots because project/task changed
        assert len(result) == 2
        assert result[0]["project"] == "P1"
        assert result[1]["project"] == "P2"

    def test_zero_duration_event_skipped(self, base_time, cat_score_map):
        """Zero-duration events should be skipped."""
        from tw_report.pipeline.generation import generate_timeline_data

        # Zero-duration window event (noise)
        window_event = make_event(
            base_time,
            timedelta(0),
            {"app": "VSCode"}
        )
        not_afk_event = make_event(base_time, timedelta(hours=1), {"status": "not-afk"})
        task_event = make_event(base_time, timedelta(hours=1), {"project": "P", "task": "T"})

        report_events = [{
            "event": window_event,
            "project": "P",
            "task": "T",
            "active_task": task_event,
        }]

        result = generate_timeline_data(report_events, [not_afk_event], cat_score_map)
        # Should return empty because zero-duration event is skipped
        assert len(result) == 0

    def test_no_task_mode(self, base_time, cat_score_map):
        """--no-taskwarrior mode with active_task=None should work."""
        from tw_report.pipeline.generation import generate_timeline_data
        from tw_report.core.categories import get_category_score

        window_event = make_event(
            base_time,
            timedelta(hours=1),
            {"app": "VSCode"}
        )
        not_afk_event = make_event(base_time, timedelta(hours=1), {"status": "not-afk"})

        report_events = [{
            "event": window_event,
            "project": NO_PROJECT,
            "task": NO_TASK,
            "active_task": None,  # No task tracking
        }]

        result = generate_timeline_data(report_events, [not_afk_event], cat_score_map, get_category_score=get_category_score)
        assert len(result) == 1
        assert result[0]["project"] == NO_PROJECT

    def test_multiple_not_afk_periods(self, base_time, cat_score_map):
        """Multiple not-afk periods should create separate slot groups."""
        from tw_report.pipeline.generation import generate_timeline_data
        from tw_report.core.categories import get_category_score

        window_event1 = make_event(base_time, timedelta(hours=1), {"app": "VSCode"})
        window_event2 = make_event(base_time + timedelta(hours=2), timedelta(hours=1), {"app": "Firefox"})

        not_afk_event1 = make_event(base_time, timedelta(hours=1), {"status": "not-afk"})
        not_afk_event2 = make_event(base_time + timedelta(hours=2), timedelta(hours=1), {"status": "not-afk"})

        task_event = make_event(base_time, timedelta(hours=3), {"project": "P", "task": "T"})

        report_events = [
            {"event": window_event1, "project": "P", "task": "T", "active_task": task_event},
            {"event": window_event2, "project": "P", "task": "T", "active_task": task_event},
        ]

        result = generate_timeline_data(report_events, [not_afk_event1, not_afk_event2], cat_score_map, get_category_score=get_category_score)
        # Should have 2 slots (one per not-afk period)
        assert len(result) == 2

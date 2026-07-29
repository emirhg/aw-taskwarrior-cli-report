"""
Unit tests to reproduce and isolate the 40-minute slot duration inflation bug.

The bug manifests when:
- :yesterday has TaskWarrior events + window events
- Day total shows 09:50:54 ACTIVE time
- But TOTALS section shows 10:34:24 Active Time (40 minutes difference)

This test suite traces through generate_timeline_data to identify the root cause.
"""
import pytest
from datetime import datetime, timedelta, timezone
from aw_core.models import Event

from tw_report.pipeline.generation import generate_timeline_data
from tw_report.core.categories import get_category_score


class TestSlotDurationInflation:
    """Test cases for identifying slot duration inflation."""

    @staticmethod
    def create_afk_event(start, duration, status="not-afk"):
        """Helper to create AFk events."""
        return Event(
            timestamp=start,
            duration=duration,
            data={"status": status}
        )

    @staticmethod
    def create_window_event(start, duration, app="TestApp", project=None):
        """Helper to create window events."""
        return Event(
            timestamp=start,
            duration=duration,
            data={
                "app": app,
                "title": "Test Window",
                "$category": ["Work"] if project is None else [project],
            }
        )

    def test_non_overlapping_slots_should_not_inflate(self):
        """
        Test baseline: Non-overlapping window events should produce
        slots with total duration equal to sum of window durations.
        """
        tz = timezone(timedelta(hours=-6))  # CST
        base_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=tz)

        # AFK period: 2 hours (10:00-12:00)
        afk_event = self.create_afk_event(base_time, timedelta(hours=2))

        # Three non-overlapping window events: 1h + 1h + 0h (gap between them)
        # Total: 2 hours of activity
        report_events = [
            {
                "event": self.create_window_event(base_time + timedelta(minutes=0), timedelta(hours=1)),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
            {
                "event": self.create_window_event(base_time + timedelta(minutes=90), timedelta(minutes=30)),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=[afk_event],
            cat_score_map={"Work": 1.0},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=get_category_score,
        )

        # Should have 1 slot (both events are same project/task)
        assert len(slots) == 1, f"Expected 1 slot, got {len(slots)}"
        slot = slots[0]

        # Check actual_duration (sum of window events)
        expected_actual_duration = timedelta(hours=1, minutes=30)  # 1h + 30m
        assert slot["actual_duration"] == expected_actual_duration, \
            f"Expected actual_duration={expected_actual_duration}, got {slot['actual_duration']}"

    def test_overlapping_window_events_same_slot(self):
        """
        Test: When window events overlap within same (project, task),
        they should be merged with duration = sum of overlapping portions
        (measured by earliest start and latest end).
        """
        tz = timezone(timedelta(hours=-6))
        base_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=tz)

        # AFK period: 2 hours
        afk_event = self.create_afk_event(base_time, timedelta(hours=2))

        # Two overlapping window events:
        # Event1: 10:00-10:45 (45m)
        # Event2: 10:30-11:00 (30m)
        # Overlap: 10:30-10:45 (15m)
        # Actual window time covered: 10:00-11:00 (60m)
        report_events = [
            {
                "event": self.create_window_event(
                    base_time,
                    timedelta(minutes=45)
                ),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
            {
                "event": self.create_window_event(
                    base_time + timedelta(minutes=30),
                    timedelta(minutes=30)
                ),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=[afk_event],
            cat_score_map={"Work": 1.0},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=get_category_score,
        )

        assert len(slots) == 1
        slot = slots[0]

        # The slot should span 10:00-11:00 (60 minutes)
        # actual_duration should be sum of event durations: 45m + 30m = 75m
        # This is INCORRECT behavior if actual_duration > wall-clock span
        # But that's what the code does: sum all window_event_durations

        print(f"\nSlot details:")
        print(f"  Start: {slot['start']}")
        print(f"  End: {slot['end']}")
        print(f"  duration (wall-clock): {slot['duration']}")
        print(f"  actual_duration (sum): {slot['actual_duration']}")

        # Wall-clock span is 60 minutes (10:00-11:00)
        expected_wall_clock = timedelta(minutes=60)
        assert slot["duration"] == expected_wall_clock, \
            f"Expected wall-clock duration={expected_wall_clock}, got {slot['duration']}"

        # actual_duration is sum: 45m + 30m = 75m
        # This is where the bug manifests!
        expected_sum = timedelta(minutes=75)
        assert slot["actual_duration"] == expected_sum, \
            f"Expected actual_duration={expected_sum}, got {slot['actual_duration']}"

        # Inflation check
        inflation = slot["actual_duration"] - slot["duration"]
        print(f"  Inflation: {inflation} (actual - wall-clock)")
        assert inflation == timedelta(minutes=15), \
            f"Expected 15m inflation from overlap, got {inflation}"

    def test_multiple_gaps_same_not_afk_period(self):
        """
        Test: When window events have gaps within the same not-afk period,
        slots should be created for each continuous window group.
        No inflation should occur.
        """
        tz = timezone(timedelta(hours=-6))
        base_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=tz)

        # AFK period: 4 hours (10:00-14:00)
        afk_event = self.create_afk_event(base_time, timedelta(hours=4))

        # Window events with gaps:
        # 10:00-11:00 (60m) - gap of 30m - 11:30-12:30 (60m)
        # Total window time: 120 minutes, Total AFK time: 240 minutes
        report_events = [
            {
                "event": self.create_window_event(
                    base_time,
                    timedelta(hours=1)
                ),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
            {
                "event": self.create_window_event(
                    base_time + timedelta(hours=1, minutes=30),
                    timedelta(hours=1)
                ),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=[afk_event],
            cat_score_map={"Work": 1.0},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=get_category_score,
        )

        # Should have 1 slot (same project/task continuity, but with internal gap)
        # The slot represents the time span from first event to last event
        assert len(slots) == 1
        slot = slots[0]

        # Wall-clock: 10:00-12:30 = 150 minutes
        expected_wall_clock = timedelta(minutes=150)
        assert slot["duration"] == expected_wall_clock, \
            f"Expected wall-clock duration={expected_wall_clock}, got {slot['duration']}"

        # actual_duration: sum of window events = 60m + 60m = 120m
        expected_sum = timedelta(minutes=120)
        assert slot["actual_duration"] == expected_sum, \
            f"Expected actual_duration={expected_sum}, got {slot['actual_duration']}"

    def test_slot_inflation_with_task_switching(self):
        """
        Test: Window events with task switches should create multiple slots.
        Each slot should not inflate (actual_duration should match wall-clock).
        """
        tz = timezone(timedelta(hours=-6))
        base_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=tz)

        # AFK period: 3 hours
        afk_event = self.create_afk_event(base_time, timedelta(hours=3))

        # Task switching: Project1/Task1 -> Project1/Task2 -> Project1/Task1
        report_events = [
            {
                "event": self.create_window_event(base_time + timedelta(0), timedelta(minutes=60)),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
            {
                "event": self.create_window_event(base_time + timedelta(minutes=60), timedelta(minutes=30)),
                "project": "Project1",
                "task": "Task2",
                "active_task": None,
            },
            {
                "event": self.create_window_event(base_time + timedelta(minutes=90), timedelta(minutes=60)),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=[afk_event],
            cat_score_map={"Work": 1.0},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=get_category_score,
        )

        print(f"\nTask switch test:")
        print(f"  Total slots: {len(slots)}")

        # Should have 3 slots: Task1 (60m), Task2 (30m), Task1 (60m)
        assert len(slots) == 3

        total_actual_duration = sum((s["actual_duration"] for s in slots), timedelta(0))
        expected_total = timedelta(minutes=150)  # 60 + 30 + 60

        assert total_actual_duration == expected_total, \
            f"Expected total actual_duration={expected_total}, got {total_actual_duration}"

        print(f"  Total actual_duration: {total_actual_duration}")
        print(f"  Expected: {expected_total}")
        print(f"  Match: {total_actual_duration == expected_total}")

    def test_multiple_not_afk_periods_with_overlapping_windows(self):
        """
        Test: When window events span multiple not-afk periods (with brief AFK in between),
        slots might be deduplicated. Check that deduplication doesn't cause inflation.
        """
        tz = timezone(timedelta(hours=-6))
        base_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=tz)

        # Two not-afk periods with a 5-minute AFK gap:
        # Period 1: 10:00-10:30
        # AFK gap: 10:30-10:35 (5 minutes of AFK)
        # Period 2: 10:35-11:00
        afk_events = [
            self.create_afk_event(base_time, timedelta(minutes=30), "not-afk"),
            self.create_afk_event(base_time + timedelta(minutes=30), timedelta(minutes=5), "afk"),
            self.create_afk_event(base_time + timedelta(minutes=35), timedelta(minutes=25), "not-afk"),
        ]

        # Window event that spans both not-afk periods: 10:00-11:00 (60m)
        # This should appear in both not-afk period slot arrays, then be deduplicated
        report_events = [
            {
                "event": self.create_window_event(base_time, timedelta(minutes=60)),
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            },
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=afk_events,
            cat_score_map={"Work": 1.0},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=get_category_score,
        )

        print(f"\nMultiple not-afk periods test:")
        print(f"  Total slots: {len(slots)}")
        for i, s in enumerate(slots):
            print(f"  Slot {i}: {s['start']} - {s['end']}, actual_duration={s['actual_duration']}")

        # Should have 1 slot (deduplicated) with actual_duration = 60m
        assert len(slots) == 1
        assert slots[0]["actual_duration"] == timedelta(minutes=60), \
            f"Expected 60m, got {slots[0]['actual_duration']}"


class TestSourceOfTruthComparison:
    """
    Test that slot durations can be compared against source-of-truth metrics.
    """

    def test_slot_totals_vs_not_afk_sum(self):
        """
        Verify that when all window events are accounted for in a single not-afk period,
        the total actual_duration of all slots equals the sum of window event durations.
        """
        tz = timezone(timedelta(hours=-6))
        base_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=tz)

        # Single 2-hour not-afk period
        afk_event = Event(
            timestamp=base_time,
            duration=timedelta(hours=2),
            data={"status": "not-afk"}
        )

        # 3 window events totaling 1.5 hours
        window_events = [
            Event(timestamp=base_time + timedelta(0), duration=timedelta(minutes=30), data={"app": "App1", "title": "Win1", "$category": ["Work"]}),
            Event(timestamp=base_time + timedelta(minutes=35), duration=timedelta(minutes=40), data={"app": "App2", "title": "Win2", "$category": ["Work"]}),
            Event(timestamp=base_time + timedelta(minutes=80), duration=timedelta(minutes=40), data={"app": "App1", "title": "Win3", "$category": ["Work"]}),
        ]

        window_sum = sum((e.duration for e in window_events), timedelta(0))

        report_events = [
            {
                "event": e,
                "project": "Project1",
                "task": "Task1",
                "active_task": None,
            }
            for e in window_events
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=[afk_event],
            cat_score_map={"Work": 1.0},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=get_category_score,
        )

        # All events are same project/task within same not-afk period
        # Should result in 1 slot
        assert len(slots) == 1

        slot = slots[0]
        slot_actual_duration = slot["actual_duration"]

        print(f"\nSource of truth test:")
        print(f"  Window events sum: {window_sum}")
        print(f"  Slot actual_duration: {slot_actual_duration}")
        print(f"  Match: {window_sum == slot_actual_duration}")

        assert window_sum == slot_actual_duration, \
            f"Expected slot actual_duration={window_sum}, got {slot_actual_duration}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

"""
Tests for the unified sweep-line timeslot builder (timeslot_builder.py).

Verifies that build_timeslot_timeline() produces guaranteed non-overlapping,
properly-classified slots with correct duration breakdowns (actual/afk/offline).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

from tw_report.core.aw_events import AFKEvent, WindowEvent, TaskWarriorEvent
from tw_report.core.report_slot import ReportTimelineSlot
from tw_report.core.timeslot_builder import build_timeslot_timeline


# ============================================================================
# Test Fixtures: Event Construction Helpers
# ============================================================================

def make_datetime(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    """Create a UTC datetime for testing."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def make_afk_event(timestamp: datetime, duration: timedelta, status: str = "afk") -> AFKEvent:
    """Create an AFKEvent for testing."""
    event = AFKEvent(timestamp=timestamp, duration=duration)
    event.data["status"] = status
    return event


def make_window_event(
    timestamp: datetime,
    duration: timedelta,
    app: str = "test_app",
    title: str = "Test Window",
    category: Optional[List[str]] = None,
) -> WindowEvent:
    """Create a WindowEvent for testing."""
    if category is None:
        category = ["Test"]
    event = WindowEvent(timestamp=timestamp, duration=duration)
    event.data["app"] = app
    event.data["title"] = title
    event.data["$category"] = category
    return event


def make_task_event(
    timestamp: datetime,
    duration: timedelta,
    project: str = "TestProject",
    task: str = "TestTask",
    uuid: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> TaskWarriorEvent:
    """Create a TaskWarriorEvent for testing."""
    if tags is None:
        tags = []
    event = TaskWarriorEvent(timestamp=timestamp, duration=duration)
    event.data["project"] = project
    event.data["task"] = task
    if uuid:
        event.data["uuid"] = uuid
    event.data["tags"] = tags
    return event


# ============================================================================
# Invariant Tests: Generic, Run Against All Scenarios
# ============================================================================

def assert_no_overlaps(slots: List[ReportTimelineSlot]) -> None:
    """Verify no two slots in output ever overlap in [start, end) time."""
    if not slots:
        return
    ordered = sorted(slots, key=lambda s: s.start)
    for i, (a, b) in enumerate(zip(ordered, ordered[1:])):
        assert a.end <= b.start, (
            f"Overlap detected at slot {i}/{len(ordered)}: "
            f"slot[{i}] ({a.start} to {a.end}) overlaps slot[{i+1}] ({b.start} to {b.end})"
        )


def assert_full_span_coverage(
    slots: List[ReportTimelineSlot],
    afk_events: List[AFKEvent],
    window_events: List[WindowEvent],
    task_events: List[TaskWarriorEvent],
) -> None:
    """Verify total output duration equals full wall-clock span of input events."""
    if not (afk_events + window_events + task_events):
        return

    all_events = afk_events + window_events + task_events
    span_start = min(e.timestamp for e in all_events)
    span_end = max(e.timestamp + e.duration for e in all_events)
    expected_span = span_end - span_start

    total_output = sum((s.duration for s in slots), timedelta(0)) if slots else timedelta(0)
    assert total_output == expected_span, (
        f"Full-span-coverage violated: total output {total_output} != expected span {expected_span}"
    )


def assert_task_time_conserved(slots: List[ReportTimelineSlot], task_event: TaskWarriorEvent) -> None:
    """Verify task event's duration is fully represented in output (not silently dropped)."""
    # Find all slots attributed to this task
    matching = [
        s for s in slots
        if s.task_event is task_event or (
            s.task_event
            and s.task_event.uuid
            and task_event.uuid
            and s.task_event.uuid == task_event.uuid
        )
    ]

    if not matching:
        pytest.fail(f"Task event {task_event.task} not found in any output slot")

    total = timedelta(0)
    for s in matching:
        total += s.actual_duration + (s.afk_duration or timedelta(0)) + (s.offline_extension_duration or timedelta(0))

    assert total == task_event.duration, (
        f"Task time not conserved for {task_event.task}: "
        f"expected {task_event.duration}, got {total} from {len(matching)} matching slots"
    )


# ============================================================================
# Primary Regression Test: Audited Scenario
# ============================================================================

class TestRegressionAuditedScenario:
    """Test the exact scenario from the 2026-08-30 audit."""

    def test_afk_no_project_overlapping_task_preparar_masa(self):
        """
        Regression test for the audited bug: AFK (No project) 17:48-18:20 overlapping
        task (Ecosistema, Preparar masa) 17:54-18:45.

        Expected output:
        - One AFK slot: 17:48-17:54 (the non-overlapping remainder)
        - One task slot: 17:54-18:45 with:
            - actual_duration: time with keyboard activity
            - afk_duration: embedded AFK (17:54-18:20)
            - (no offline, since AFK coverage exists)
        """
        # AFK event: 17:48-18:20, status "afk"
        afk_event = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 17, 48),
            duration=timedelta(minutes=32),
            status="afk",
        )

        # Task event: 17:54-18:45 (overlaps with AFK 17:54-18:20)
        task_event = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 17, 54),
            duration=timedelta(minutes=51),
            project="Ecosistema",
            task="Preparar masa",
            uuid="task-uuid-123",
        )

        # not-afk AFK event covering the end of the task (18:20-18:45)
        # This ensures the task's tail is marked "online" (user active)
        not_afk_event = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 18, 20),
            duration=timedelta(minutes=25),
            status="not-afk",
        )

        slots = build_timeslot_timeline(
            afk_events=[afk_event, not_afk_event],
            window_events=[],
            task_events=[task_event],
        )

        # Verify no overlaps
        assert_no_overlaps(slots)

        # Verify full span coverage
        assert_full_span_coverage(
            slots,
            afk_events=[afk_event, not_afk_event],
            window_events=[],
            task_events=[task_event],
        )

        # Verify task time is conserved
        assert_task_time_conserved(slots, task_event)

        # Verify structure
        assert len(slots) >= 2, f"Expected at least 2 slots (AFK + task), got {len(slots)}"

        # Find the AFK-only slot (17:48-17:54)
        afk_only = [s for s in slots if s.task_event is None and s.afk_duration is not None]
        assert len(afk_only) >= 1, "Expected at least one AFK-only slot"
        afk_slot = afk_only[0]
        assert afk_slot.start == make_datetime(2026, 6, 27, 17, 48)
        assert afk_slot.end == make_datetime(2026, 6, 27, 17, 54)

        # Find the task slot (17:54-18:45)
        task_slots = [s for s in slots if s.task_event is not None]
        assert len(task_slots) >= 1, "Expected at least one task slot"
        task_slot = task_slots[0]
        assert task_slot.start == make_datetime(2026, 6, 27, 17, 54)
        assert task_slot.end == make_datetime(2026, 6, 27, 18, 45)

        # Verify embedded AFK within the task slot (17:54-18:20 = 26 min)
        assert task_slot.afk_duration is not None
        assert task_slot.afk_duration == timedelta(minutes=26), (
            f"Task slot should have 26min embedded AFK (17:54-18:20), got {task_slot.afk_duration}"
        )

        # Verify active time (18:20-18:45 = 25 min)
        assert task_slot.actual_duration == timedelta(minutes=25), (
            f"Task slot should have 25min active (18:20-18:45), got {task_slot.actual_duration}"
        )


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_task_starting_exactly_at_afk_boundary(self):
        """Task event starting exactly when AFK event ends."""
        afk_event = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            status="afk",
        )
        task_event = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 30),  # Exactly at AFK end
            duration=timedelta(minutes=20),
            uuid="task-1",
        )
        not_afk_event = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 30),
            duration=timedelta(minutes=20),
            status="not-afk",
        )

        slots = build_timeslot_timeline(
            afk_events=[afk_event, not_afk_event],
            window_events=[],
            task_events=[task_event],
        )

        assert_no_overlaps(slots)
        assert_full_span_coverage(
            slots,
            afk_events=[afk_event, not_afk_event],
            window_events=[],
            task_events=[task_event],
        )

    def test_zero_gap_adjacent_tasks_same_uuid(self):
        """Two task events with same UUID, zero gap between them (should merge)."""
        task1 = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            uuid="task-shared",
            project="Proj",
            task="Task",
        )
        task2 = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 30),
            duration=timedelta(minutes=20),
            uuid="task-shared",
            project="Proj",
            task="Task",
        )
        not_afk = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=50),
            status="not-afk",
        )

        slots = build_timeslot_timeline(
            afk_events=[not_afk],
            window_events=[],
            task_events=[task1, task2],
        )

        assert_no_overlaps(slots)
        # When tasks with same UUID are adjacent, they merge into one slot
        # spanning the full 50 minutes (30 + 20)
        task_slots = [s for s in slots if s.task_event is not None]
        assert len(task_slots) == 1, f"Expected 1 merged slot, got {len(task_slots)}"
        assert task_slots[0].actual_duration == timedelta(minutes=50)
        assert task_slots[0].start == make_datetime(2026, 6, 27, 10, 0)
        assert task_slots[0].end == make_datetime(2026, 6, 27, 10, 50)

    def test_empty_input_lists(self):
        """Builder should handle empty inputs gracefully."""
        slots = build_timeslot_timeline(
            afk_events=[],
            window_events=[],
            task_events=[],
        )
        assert slots == []

    def test_only_zero_duration_events(self):
        """Builder should skip zero-duration events and return empty."""
        afk_event = AFKEvent(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(0),  # Zero duration
        )
        task_event = TaskWarriorEvent(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(0),  # Zero duration
        )

        slots = build_timeslot_timeline(
            afk_events=[afk_event],
            window_events=[],
            task_events=[task_event],
        )
        assert slots == []

    def test_two_overlapping_different_tasks_tie_break(self):
        """Two different tasks overlapping — verify deterministic tie-break."""
        # Both tasks cover the same time period; earlier start should win
        task1 = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            uuid="task-1",
            project="Proj",
            task="Task1",
        )
        task2 = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 5),  # Starts 5 min later
            duration=timedelta(minutes=20),
            uuid="task-2",
            project="Proj",
            task="Task2",
        )
        not_afk = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            status="not-afk",
        )

        slots = build_timeslot_timeline(
            afk_events=[not_afk],
            window_events=[],
            task_events=[task1, task2],
        )

        assert_no_overlaps(slots)
        # task1 should win (earlier start), so its duration should be fully represented
        assert_task_time_conserved(slots, task1)


# ============================================================================
# Task-Only Mode (No Window Events)
# ============================================================================

class TestTaskOnlyMode:
    """Test builder with empty window_events (e.g., --task-id mode)."""

    def test_task_only_with_afk_offline_classification(self):
        """Task-only mode should classify offline/online based on AFK bucket only."""
        task = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=60),
            uuid="task-1",
        )
        # AFK: 10:00-10:30 (offline period)
        # No AFK: 10:30-11:00 (online period)
        afk_offline = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            status="afk",
        )
        afk_online = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 30),
            duration=timedelta(minutes=30),
            status="not-afk",
        )

        slots = build_timeslot_timeline(
            afk_events=[afk_offline, afk_online],
            window_events=[],  # Empty!
            task_events=[task],
        )

        assert_no_overlaps(slots)
        task_slots = [s for s in slots if s.task_event is not None]
        assert len(task_slots) == 1

        slot = task_slots[0]
        # Should have 30min embedded AFK + 30min active
        assert slot.afk_duration == timedelta(minutes=30)
        assert slot.actual_duration == timedelta(minutes=30)
        assert slot.offline_extension_duration is None  # Has AFK coverage throughout


# ============================================================================
# Integration: Multiple Event Sources
# ============================================================================

class TestMultipleEventSources:
    """Test builder with complex combinations of all three event types."""

    def test_task_with_window_and_afk_events(self):
        """Complete scenario: task + windows + AFK."""
        task = make_task_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=60),
            uuid="task-1",
            project="WebDev",
            task="Fix bug",
        )
        # Window events showing app activity
        window1 = make_window_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            app="vim",
            category=["Development"],
        )
        window2 = make_window_event(
            timestamp=make_datetime(2026, 6, 27, 10, 35),
            duration=timedelta(minutes=25),
            app="Chrome",
            category=["Communication"],
        )
        # AFK: idle 10:30-10:35
        afk_idle = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 30),
            duration=timedelta(minutes=5),
            status="afk",
        )
        # Not-afk for the rest
        afk_active1 = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 0),
            duration=timedelta(minutes=30),
            status="not-afk",
        )
        afk_active2 = make_afk_event(
            timestamp=make_datetime(2026, 6, 27, 10, 35),
            duration=timedelta(minutes=25),
            status="not-afk",
        )

        slots = build_timeslot_timeline(
            afk_events=[afk_idle, afk_active1, afk_active2],
            window_events=[window1, window2],
            task_events=[task],
        )

        assert_no_overlaps(slots)
        assert_full_span_coverage(
            slots,
            afk_events=[afk_idle, afk_active1, afk_active2],
            window_events=[window1, window2],
            task_events=[task],
        )
        assert_task_time_conserved(slots, task)

        # Verify the task slot has correct breakdown
        task_slots = [s for s in slots if s.task_event is not None]
        assert len(task_slots) >= 1
        slot = task_slots[0]
        assert slot.afk_duration == timedelta(minutes=5)  # Idle period
        assert slot.actual_duration == timedelta(minutes=55)  # Active portions
        # Verify categories were attached
        assert len(slot.categories) > 0


# ============================================================================
# State Continuity Micro-Slot Merging Tests (2026-09-02)
# ============================================================================

def test_state_continuity_merging_active_to_offline_micro_slot():
    """Micro-slot with offline gap after active slot inherits active state."""
    from tw_report.core.filtering import NO_PROJECT, NO_TASK
    from tw_report.core.aw_events import TaskWarriorEvent

    # Create minimal task event for "No project assigned"
    task_event = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 1),
        duration=timedelta(minutes=4, seconds=28),
        data={"project": NO_PROJECT, "title": NO_TASK}
    )

    # Active slot: 12:01-12:05 (4:28 active time)
    active_slot = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 1),
        end=make_datetime(2026, 9, 2, 12, 5),
        duration=timedelta(minutes=4, seconds=28),
        actual_duration=timedelta(minutes=4, seconds=28),  # Active
        productive_duration=timedelta(0),
        task_event=task_event,
    )

    # Micro-slot: 12:05-12:05 (0:01 marked as offline, should be reclassified)
    micro_slot = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 5),
        end=make_datetime(2026, 9, 2, 12, 5, 1),
        duration=timedelta(seconds=1),
        actual_duration=timedelta(0),
        productive_duration=timedelta(0),
        offline_extension_duration=timedelta(seconds=1),  # Marked as offline
        task_event=task_event,
    )

    # Build timeline (which calls the merge function internally)
    slots = [active_slot, micro_slot]
    from tw_report.core.timeslot_builder import _merge_adjacent_micro_slots_by_state_continuity
    result = _merge_adjacent_micro_slots_by_state_continuity(slots)

    # Should merge into one slot
    assert len(result) == 1, f"Expected 1 merged slot, got {len(result)}"
    merged = result[0]

    # Verify merged slot spans full time
    assert merged.start == active_slot.start, "Merged start time should match active slot start"
    assert merged.end == micro_slot.end, "Merged end time should match micro slot end"

    # Verify offline time was reclassified to active/afk (not kept as offline)
    assert merged.offline_extension_duration is None or merged.offline_extension_duration == timedelta(0), \
        "Offline time should be reclassified, not kept as offline_extension_duration"

    # Verify total active duration is preserved
    assert merged.actual_duration == active_slot.actual_duration, \
        "Active duration should be preserved from original active slot"


def test_state_continuity_merging_non_adjacent_slots():
    """Non-adjacent slots (gap > 1 sec) should NOT merge."""
    from tw_report.core.aw_events import TaskWarriorEvent

    task_event = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 1),
        duration=timedelta(minutes=10),
        data={"project": "P1", "title": "T1"}
    )

    slot1 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 1),
        end=make_datetime(2026, 9, 2, 12, 5),
        duration=timedelta(minutes=4),
        actual_duration=timedelta(minutes=4),
        productive_duration=timedelta(0),
        task_event=task_event,
    )

    # Large gap: 10 seconds
    slot2 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 5, 10),
        end=make_datetime(2026, 9, 2, 12, 6),
        duration=timedelta(minutes=1),
        actual_duration=timedelta(minutes=1),
        productive_duration=timedelta(0),
        task_event=task_event,
    )

    from tw_report.core.timeslot_builder import _merge_adjacent_micro_slots_by_state_continuity
    result = _merge_adjacent_micro_slots_by_state_continuity([slot1, slot2])

    # Should NOT merge (gap > 1 second)
    assert len(result) == 2, "Non-adjacent slots should NOT merge"


def test_state_continuity_merging_different_tasks():
    """Slots for different tasks should NOT merge."""
    from tw_report.core.aw_events import TaskWarriorEvent

    task_event1 = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 1),
        duration=timedelta(minutes=4),
        data={"project": "P1", "title": "T1"}
    )
    task_event2 = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 5),
        duration=timedelta(minutes=1),
        data={"project": "P1", "title": "T2"}
    )

    slot1 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 1),
        end=make_datetime(2026, 9, 2, 12, 5),
        duration=timedelta(minutes=4),
        actual_duration=timedelta(minutes=4),
        productive_duration=timedelta(0),
        task_event=task_event1,
    )

    slot2 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 5),
        end=make_datetime(2026, 9, 2, 12, 6),
        duration=timedelta(minutes=1),
        actual_duration=timedelta(0),
        productive_duration=timedelta(0),
        task_event=task_event2,
    )

    from tw_report.core.timeslot_builder import _merge_adjacent_micro_slots_by_state_continuity
    result = _merge_adjacent_micro_slots_by_state_continuity([slot1, slot2])

    # Should NOT merge (different tasks)
    assert len(result) == 2, "Slots with different tasks should NOT merge"


def test_state_continuity_merging_multiple_micro_slots():
    """Multiple consecutive micro-slots should merge into one."""
    from tw_report.core.filtering import NO_PROJECT, NO_TASK
    from tw_report.core.aw_events import TaskWarriorEvent

    task_event = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 1),
        duration=timedelta(minutes=4, seconds=30),
        data={"project": NO_PROJECT, "title": NO_TASK}
    )

    # Active slot: 12:01 to 12:05:28 (4:28 duration)
    slot1 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 1),
        end=make_datetime(2026, 9, 2, 12, 5, 28),
        duration=timedelta(minutes=4, seconds=28),
        actual_duration=timedelta(minutes=4, seconds=28),  # Active
        productive_duration=timedelta(0),
        task_event=task_event,
    )

    # First micro-slot: 12:05:28 to 12:05:29 (1 second, marked offline)
    slot2 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 5, 28),
        end=make_datetime(2026, 9, 2, 12, 5, 29),
        duration=timedelta(seconds=1),
        actual_duration=timedelta(0),
        productive_duration=timedelta(0),
        offline_extension_duration=timedelta(seconds=1),
        task_event=task_event,
    )

    # Second micro-slot: 12:05:29 to 12:05:30 (1 second, marked offline)
    slot3 = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 5, 29),
        end=make_datetime(2026, 9, 2, 12, 5, 30),
        duration=timedelta(seconds=1),
        actual_duration=timedelta(0),
        productive_duration=timedelta(0),
        offline_extension_duration=timedelta(seconds=1),
        task_event=task_event,
    )

    from tw_report.core.timeslot_builder import _merge_adjacent_micro_slots_by_state_continuity
    result = _merge_adjacent_micro_slots_by_state_continuity([slot1, slot2, slot3])

    # Should merge into one slot
    assert len(result) == 1, f"Expected 1 merged slot from 3 adjacent, got {len(result)}"
    merged = result[0]

    # Verify full span
    assert merged.start == slot1.start
    assert merged.end == slot3.end

    # Verify total duration (4:28 + 1s + 1s = 4:30)
    expected_total = timedelta(minutes=4, seconds=30)
    assert merged.duration == expected_total, \
        f"Merged duration should be {expected_total}, got {merged.duration}"


def test_state_continuity_empty_and_single_slot():
    """Edge cases: empty list and single slot should return unchanged."""
    from tw_report.core.timeslot_builder import _merge_adjacent_micro_slots_by_state_continuity
    from tw_report.core.aw_events import TaskWarriorEvent

    # Empty list
    result = _merge_adjacent_micro_slots_by_state_continuity([])
    assert result == [], "Empty list should return empty"

    # Single slot
    task_event = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 1),
        duration=timedelta(minutes=4),
        data={"project": "P1", "title": "T1"}
    )
    slot = ReportTimelineSlot(
        start=make_datetime(2026, 9, 2, 12, 1),
        end=make_datetime(2026, 9, 2, 12, 5),
        duration=timedelta(minutes=4),
        actual_duration=timedelta(minutes=4),
        productive_duration=timedelta(0),
        task_event=task_event,
    )
    result = _merge_adjacent_micro_slots_by_state_continuity([slot])
    assert len(result) == 1, "Single slot should return single"
    assert result[0] is slot, "Single slot should be unchanged"


# ============================================================================
# Window-Event Proof-of-Activity Tests (2026-09-02)
# ============================================================================

def test_window_activity_during_afk_bucket_gap_classification():
    """Window events prove system is on, even if AFK bucket gap exists.

    Regression test for the 2-second offline misclassification issue:
    When AFK bucket starts 2 seconds after window events, the gap was
    misclassified as offline time. Window activity is strong proof that
    the system is powered on (window events only fire when system is active).
    """
    # Scenario: Window event at 12:00, AFK event at 12:00:02 (2-second gap)
    window_event = make_window_event(
        timestamp=make_datetime(2026, 9, 2, 12, 0, 0),
        duration=timedelta(seconds=40),  # Covers the gap
        app="kitty",
        title="terminal",
    )

    afk_event = make_afk_event(
        timestamp=make_datetime(2026, 9, 2, 12, 0, 2),  # 2 seconds after window
        duration=timedelta(seconds=38),  # Covers 12:00:02 to 12:00:40
        status="not-afk",
    )

    task_event = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 0, 0),
        duration=timedelta(seconds=40),
        data={"project": "Work", "title": "coding"}
    )

    slots = build_timeslot_timeline(
        afk_events=[afk_event],
        window_events=[window_event],
        task_events=[task_event],
    )

    # Should have 1 slot covering the full 40 seconds
    assert len(slots) == 1, f"Expected 1 slot, got {len(slots)}"
    slot = slots[0]

    # Verify time span
    assert slot.start == make_datetime(2026, 9, 2, 12, 0, 0)
    assert slot.end == make_datetime(2026, 9, 2, 12, 0, 40)

    # CRITICAL: Window activity during gap means no offline time should be created
    # The 2-second gap should be classified as "online" (proven by window event)
    # not "offline" (unproven system poweroff)
    assert slot.offline_extension_duration is None or \
           slot.offline_extension_duration == timedelta(0), \
        f"Window activity proves system is on; no offline time should exist. Got: {slot.offline_extension_duration}"

    # All 40 seconds should be active time (window + AFK both present)
    assert slot.actual_duration == timedelta(seconds=40), \
        f"Window activity = active time; expected 40s, got {slot.actual_duration}"


def test_no_window_activity_during_gap_classified_as_offline():
    """Without window events, gaps with no AFK are legitimately offline.

    When task time spans a gap with no AFK or window coverage, that gap
    is classified as offline_extension_duration (system was powered off).
    """
    # Scenario: Only AFK events, no window events, gap in AFK coverage
    afk_event_1 = make_afk_event(
        timestamp=make_datetime(2026, 9, 2, 12, 0, 0),
        duration=timedelta(seconds=10),
        status="not-afk",
    )

    afk_event_2 = make_afk_event(
        timestamp=make_datetime(2026, 9, 2, 12, 0, 15),  # 5-second gap
        duration=timedelta(seconds=10),
        status="not-afk",
    )

    task_event = TaskWarriorEvent(
        timestamp=make_datetime(2026, 9, 2, 12, 0, 0),
        duration=timedelta(seconds=25),  # Spans both AFK events and gap
        data={"project": "Work", "title": "coding"}
    )

    slots = build_timeslot_timeline(
        afk_events=[afk_event_1, afk_event_2],
        window_events=[],  # NO window events
        task_events=[task_event],
    )

    # Builder creates 1 consolidated offline_task slot with embedded gap
    assert len(slots) == 1, f"Expected 1 consolidated slot, got {len(slots)}"

    slot = slots[0]
    # Verify the gap is classified as offline_extension_duration
    assert slot.offline_extension_duration == timedelta(seconds=5), \
        f"Gap without window/AFK coverage should be offline. Got: {slot.offline_extension_duration}"

    # Active time should only be the 20 seconds covered by AFK
    assert slot.actual_duration == timedelta(seconds=20), \
        f"Active time should be 20s (2x10s AFK coverage), got {slot.actual_duration}"

    # Offline gap should be the 5-second uncovered period
    offline_dur = slot.offline_extension_duration or timedelta(0)
    total_breakdown = slot.actual_duration + offline_dur
    assert total_breakdown == timedelta(seconds=25), \
        f"Breakdown should sum to 25s (active 20s + offline 5s), got {total_breakdown}"

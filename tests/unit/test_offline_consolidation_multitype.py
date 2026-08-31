"""Unit tests for OFFLINE task consolidation with multiple entry types.

Tests that when consolidating timeline entries, tasks appearing as multiple
entry types (OFFLINE, ACTIVE, AFK) for the same (project, task) should be
properly grouped and their durations accumulated correctly.

Current behavior: Shows 6 groups instead of 4 unique tasks
Expected behavior: 4 groups (one per unique project+task pair), with durations
                   from all entry types accumulated together
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.timeline import TimelineSlot, Timeline
from tw_report.core.filtering import NO_PROJECT


@pytest.fixture
def tz():
    return timezone(timedelta(hours=-6))


@pytest.fixture
def base_time(tz):
    """2026-08-30 11:00 UTC-6"""
    return datetime(2026, 8, 30, 11, 0, tzinfo=tz)


class TestOfflineConsolidationMultiType:
    """Test consolidation when same task has OFFLINE, ACTIVE, and AFK entries."""

    def test_same_task_appears_as_multiple_entry_types(self, base_time, tz):
        """Same task with different types should consolidate within each type.

        Scenario:
        - Task A has 1 ACTIVE entry (work time) - type: regular
        - Task A has 1 OFFLINE entry (system off time) - type: offline_task
        - Task A has 1 AFK entry (idle time) - type: afk (or regular with afk_duration)

        Expected: 3 entries (one per type, each consolidated within its type)
        This preserves type information needed for display (OFFLINE column, etc.)
        """
        timeline = Timeline()

        # ACTIVE entry for Task A (01:00 duration)
        active_slot = TimelineSlot(
            type="regular",
            start=base_time,
            end=base_time + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            project="Project1",
            task="Task A",
        )

        # OFFLINE entry for Task A (02:00 duration)
        offline_slot = TimelineSlot(
            type="offline_task",
            start=base_time + timedelta(hours=1),
            end=base_time + timedelta(hours=3),
            duration=timedelta(hours=2),
            actual_duration=timedelta(0),
            offline_extension_duration=timedelta(hours=2),
            event_duration=timedelta(0),
            project="Project1",
            task="Task A",
        )

        # AFK entry for Task A (00:30 duration)
        afk_slot = TimelineSlot(
            type="afk",
            start=base_time + timedelta(hours=3),
            end=base_time + timedelta(hours=3, minutes=30),
            duration=timedelta(minutes=30),
            actual_duration=timedelta(minutes=30),  # For AFK slots, entire duration is AFK
            afk_duration=timedelta(minutes=30),
            project="Project1",
            task="Task A",
        )

        timeline.add_slots([active_slot, offline_slot, afk_slot])

        # Get final timeline with consolidated entries
        report_timeline = timeline.to_report_timeline()
        # Apply consolidation by task (consolidates within each type)
        report_timeline = report_timeline.consolidate_by_task()
        final_slots = report_timeline.as_dicts()

        # Filter to Task A entries
        task_a_entries = [s for s in final_slots if s.get("task") == "Task A"]

        print(f"\n✓ Test: Multi-type consolidation for same task")
        print(f"  Entry types in timeline: ACTIVE, OFFLINE, AFK")
        print(f"  Task A entries found: {len(task_a_entries)}")
        for entry in task_a_entries:
            print(f"    Type: {entry.get('type')}, Duration: {entry.get('duration')}, OFFLINE Ext: {entry.get('offline_extension_duration')}")

        # EXPECTED: Should have 1 entry (all types consolidated into one)
        # A single task session can span ACTIVE, AFK, and OFFLINE time
        # All duration components are preserved and summed in one slot
        assert len(task_a_entries) == 1, \
            f"Expected 1 consolidated entry for Task A (all types merged), but got {len(task_a_entries)}. " \
            f"All duration components should be present in single entry."

        # The consolidated entry should have all three components summed
        consolidated_slot = task_a_entries[0]

        # Verify duration components
        actual_duration = consolidated_slot.get("actual_duration") or timedelta(0)
        afk_duration = consolidated_slot.get("afk_duration") or timedelta(0)
        offline_ext = consolidated_slot.get("offline_extension_duration") or timedelta(0)

        # ACTIVE (actual_duration) = 1h (from active_slot) + 30m (from afk_slot) = 1h30m
        expected_actual = timedelta(hours=1, minutes=30)
        # AFK (afk_duration) = 30m (from afk_slot) = 30m
        expected_afk = timedelta(minutes=30)
        # OFFLINE (offline_extension_duration) = 2h (from offline_slot) = 2h
        expected_offline = timedelta(hours=2)

        print(f"  Consolidated entry components:")
        print(f"    ACTIVE: {actual_duration} (expected {expected_actual})")
        print(f"    AFK: {afk_duration} (expected {expected_afk})")
        print(f"    OFFLINE: {offline_ext} (expected {expected_offline})")

        assert actual_duration == expected_actual, \
            f"ACTIVE mismatch: {actual_duration} != {expected_actual}"
        assert afk_duration == expected_afk, \
            f"AFK mismatch: {afk_duration} != {expected_afk}"
        assert offline_ext == expected_offline, \
            f"OFFLINE mismatch: {offline_ext} != {expected_offline}"

        # Total wall-clock span
        total_wall_clock = consolidated_slot.get("duration") or timedelta(0)
        expected_wall_clock = timedelta(hours=3, minutes=30)
        assert total_wall_clock == expected_wall_clock, \
            f"Wall-clock duration mismatch: {total_wall_clock} != {expected_wall_clock}"

    def test_consolidation_preserves_duration_components(self, base_time):
        """Consolidation should preserve and sum OFFLINE, AFK, ACTIVE components.

        When consolidating Task A that has:
        - 01:00 ACTIVE time
        - 02:00 OFFLINE time
        - 00:30 AFK time

        Result should show these durations preserved/accumulated.
        """
        timeline = Timeline()

        # Same slots as above
        active_slot = TimelineSlot(
            type="regular",
            start=base_time,
            end=base_time + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            project="Ecosistema",
            task="Preparar masa",
        )

        offline_slot = TimelineSlot(
            type="offline_task",
            start=base_time + timedelta(hours=1),
            end=base_time + timedelta(hours=3),
            duration=timedelta(hours=2),
            actual_duration=timedelta(0),
            offline_extension_duration=timedelta(hours=2),
            event_duration=timedelta(0),
            project="Ecosistema",
            task="Preparar masa",
        )

        timeline.add_slots([active_slot, offline_slot])
        report_timeline = timeline.to_report_timeline()
        # Apply consolidation by task
        report_timeline = report_timeline.consolidate_by_task()
        final_slots = report_timeline.as_dicts()

        task_entries = [s for s in final_slots if s.get("task") == "Preparar masa"]

        print(f"\n✓ Test: Duration components preservation")
        print(f"  Total entries after consolidation: {len(task_entries)}")
        for entry in task_entries:
            print(f"    Type: {entry.get('type')}, Duration: {entry.get('duration')}, Actual: {entry.get('actual_duration')}, OFFLINE Ext: {entry.get('offline_extension_duration')}")

        # After consolidation, should have 1 entry (all types merged)
        assert len(task_entries) == 1, \
            f"Expected 1 consolidated entry (all types merged), got {len(task_entries)}"

        consolidated_entry = task_entries[0]

        # Verify components are preserved and summed
        actual_duration = consolidated_entry.get("actual_duration") or timedelta(0)
        offline_duration = consolidated_entry.get("offline_extension_duration") or timedelta(0)

        print(f"  Consolidated entry - ACTIVE: {actual_duration}")
        print(f"  Consolidated entry - OFFLINE: {offline_duration}")

        assert actual_duration == timedelta(hours=1), \
            f"ACTIVE total mismatch: {actual_duration} != 01:00"
        assert offline_duration == timedelta(hours=2), \
            f"OFFLINE total mismatch: {offline_duration} != 02:00"

    def test_multiple_tasks_consolidated_separately(self, base_time):
        """Multiple different tasks should consolidate independently.

        Scenario:
        - Task A: 1 ACTIVE + 2 OFFLINE (3h total)
        - Task B: 1 ACTIVE + 1 OFFLINE (2h total)
        - Task C: 1 ACTIVE (1h total)

        Expected: 3 consolidated groups
        Current: Shows 6 separate entries (bug - each type gets own entry)
        """
        timeline = Timeline()

        # Task A entries
        timeline.add_slots([
            TimelineSlot(
                type="regular",
                start=base_time,
                end=base_time + timedelta(hours=1),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                project="Proj", task="Task A",
            ),
            TimelineSlot(
                type="offline_task",
                start=base_time + timedelta(hours=1),
                end=base_time + timedelta(hours=3),
                duration=timedelta(hours=2),
                actual_duration=timedelta(0),
                offline_extension_duration=timedelta(hours=2),
                event_duration=timedelta(0),
                project="Proj", task="Task A",
            ),
        ])

        # Task B entries
        timeline.add_slots([
            TimelineSlot(
                type="regular",
                start=base_time + timedelta(hours=3),
                end=base_time + timedelta(hours=4),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                project="Proj", task="Task B",
            ),
            TimelineSlot(
                type="offline_task",
                start=base_time + timedelta(hours=4),
                end=base_time + timedelta(hours=5),
                duration=timedelta(hours=1),
                actual_duration=timedelta(0),
                offline_extension_duration=timedelta(hours=1),
                event_duration=timedelta(0),
                project="Proj", task="Task B",
            ),
        ])

        # Task C entries
        timeline.add_slots([
            TimelineSlot(
                type="regular",
                start=base_time + timedelta(hours=5),
                end=base_time + timedelta(hours=6),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                project="Proj", task="Task C",
            ),
        ])

        report_timeline = timeline.to_report_timeline()
        # Apply consolidation by task
        report_timeline = report_timeline.consolidate_by_task()
        final_slots = report_timeline.as_dicts()

        # Group by task
        tasks = {}
        for slot in final_slots:
            task = slot.get("task")
            if task not in tasks:
                tasks[task] = []
            tasks[task].append(slot)

        print(f"\n✓ Test: Multiple tasks consolidated separately")
        print(f"  Total slots: {len(final_slots)}")
        print(f"  Unique tasks found: {len(tasks)}")
        for task, entries in sorted(tasks.items()):
            total = sum((e.get("duration") or timedelta(0) for e in entries), timedelta(0))
            print(f"    {task}: {len(entries)} entries, total {total}")

        # EXPECTED: All types consolidated into one entry per (project, task)
        # Task A: 1 entry (3h wall-clock: 1h regular + 2h offline_task)
        # Task B: 1 entry (2h wall-clock: 1h regular + 1h offline_task)
        # Task C: 1 entry (1h regular)

        assert len(tasks["Task A"]) == 1, \
            f"Task A should have 1 entry (all types merged), got {len(tasks['Task A'])}"
        assert len(tasks["Task B"]) == 1, \
            f"Task B should have 1 entry (all types merged), got {len(tasks['Task B'])}"
        assert len(tasks["Task C"]) == 1, \
            f"Task C should have 1 entry (all types merged), got {len(tasks['Task C'])}"

        # Totals (wall-clock spans) should be:
        # Task A: 3h (from 1h ACTIVE to 2h OFFLINE = full span)
        # Task B: 2h (from 1h ACTIVE to 1h OFFLINE = full span)
        # Task C: 1h (1h ACTIVE only)
        task_a_total = sum((e.get("duration") or timedelta(0) for e in tasks["Task A"]), timedelta(0))
        task_b_total = sum((e.get("duration") or timedelta(0) for e in tasks["Task B"]), timedelta(0))
        task_c_total = sum((e.get("duration") or timedelta(0) for e in tasks["Task C"]), timedelta(0))

        assert task_a_total == timedelta(hours=3), \
            f"Task A total: {task_a_total} != 3h"
        assert task_b_total == timedelta(hours=2), \
            f"Task B total: {task_b_total} != 2h"
        assert task_c_total == timedelta(hours=1), \
            f"Task C total: {task_c_total} != 1h"


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])

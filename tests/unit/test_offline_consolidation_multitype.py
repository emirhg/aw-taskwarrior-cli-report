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
        """Same task should appear once even if it has OFFLINE, ACTIVE, AFK entries.

        Scenario:
        - Task A has 1 ACTIVE entry (work time)
        - Task A has 1 OFFLINE entry (system off time)
        - Task A has 1 AFK entry (idle time)

        Expected: 1 consolidated entry for Task A with durations from all types
        Current: 3 separate entries (bug)
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
        # Apply consolidation by task to merge different entry types
        report_timeline = report_timeline.consolidate_by_task()
        final_slots = report_timeline.as_dicts()

        # Filter to Task A entries
        task_a_entries = [s for s in final_slots if s.get("task") == "Task A"]

        print(f"\n✓ Test: Multi-type consolidation for same task")
        print(f"  Entry types in timeline: ACTIVE, OFFLINE, AFK")
        print(f"  Task A entries found: {len(task_a_entries)}")
        for entry in task_a_entries:
            print(f"    Type: {entry.get('type')}, Duration: {entry.get('duration')}")

        # EXPECTED: Should have only 1 consolidated entry for Task A
        # CURRENT BUG: Has 3 separate entries (one per type: regular, offline_task, regular/afk)
        # This test should FAIL until consolidation is fixed
        print(f"  [EXPECTED TO FAIL] Consolidation should merge multiple types into 1 entry")
        assert len(task_a_entries) == 1, \
            f"CONSOLIDATION BUG: Expected 1 consolidated entry for Task A, but got {len(task_a_entries)} separate entries. " \
            f"This is the consolidation bug - same task appearing as multiple entries instead of merged."

        # Total duration should be: 1h (ACTIVE) + 2h (OFFLINE) + 30m (AFK) = 3h 30m
        total_duration = sum(
            (s.get("duration") or timedelta(0) for s in task_a_entries),
            timedelta(0)
        )
        expected_total = timedelta(hours=3, minutes=30)

        print(f"  Total duration across all entries: {total_duration}")
        print(f"  Expected total: {expected_total}")

        assert total_duration == expected_total, \
            f"Total duration mismatch: {total_duration} != {expected_total}"

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
            print(f"    Duration: {entry.get('duration')}, Actual: {entry.get('actual_duration')}, OFFLINE Ext: {entry.get('offline_extension_duration')}")

        # After consolidation, should have 1 entry with accumulated durations
        assert len(task_entries) == 1, \
            f"Expected 1 consolidated entry, got {len(task_entries)}"

        consolidated_entry = task_entries[0]

        # The consolidated entry should have:
        # - total duration: 1h (active) + 2h (offline) = 3h
        # - actual_duration (ACTIVE): 1h
        # - offline_extension_duration (OFFLINE): 2h
        total_duration = consolidated_entry.get("duration") or timedelta(0)
        actual_duration = consolidated_entry.get("actual_duration") or timedelta(0)
        offline_duration = consolidated_entry.get("offline_extension_duration") or timedelta(0)

        print(f"  Total Duration: {total_duration}")
        print(f"  ACTIVE (actual_duration): {actual_duration}")
        print(f"  OFFLINE (offline_extension_duration): {offline_duration}")

        assert total_duration == timedelta(hours=3), \
            f"Total duration mismatch: {total_duration} != 03:00"
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

        # EXPECTED: Each task should have exactly 1 entry (consolidated)
        # CURRENT BUG: Has multiple entries per task (one per type)
        for task, entries in tasks.items():
            assert len(entries) == 1, \
                f"CONSOLIDATION BUG: {task} has {len(entries)} entries instead of 1 consolidated entry"

        # Verify totals per task
        assert len(tasks["Task A"]) >= 1, "Task A should have at least 1 entry"
        assert len(tasks["Task B"]) >= 1, "Task B should have at least 1 entry"
        assert len(tasks["Task C"]) >= 1, "Task C should have at least 1 entry"

        # Totals should be:
        # Task A: 3h, Task B: 2h, Task C: 1h
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

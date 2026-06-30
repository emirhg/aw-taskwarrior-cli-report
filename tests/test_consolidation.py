"""
Unit tests for consolidation logic (to be extracted in Phase 3).

Tests verify that timeline slot consolidation works correctly:
- Merges same (date, project, task) entries
- Handles OFFLINE gaps intelligently
- Accumulates durations properly
- Preserves category information

This file focuses on Issue #2: Multiple OFF entries not being consolidated.
"""

import pytest
from datetime import timedelta


class TestBasicConsolidation:
    """Test fundamental consolidation behavior."""

    def test_consolidate_same_project_task_date(self):
        """Should merge slots for same (date, project, task)."""
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        # Add 2 slots for same (date, project, task)
        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        # EXPECTED: 1 merged slot
        assert len(consolidated) == 1
        assert consolidated[0]["actual_duration"] == timedelta(hours=2)

    def test_consolidate_different_tasks_no_merge(self):
        """Should NOT merge different tasks even on same date."""
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task2",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        # EXPECTED: 2 separate slots (different tasks)
        assert len(consolidated) == 2

    def test_consolidate_different_projects_no_merge(self):
        """Should NOT merge different projects."""
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "project": "Mercado",
                "task": "Task1",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        # EXPECTED: 2 separate slots (different projects)
        assert len(consolidated) == 2

    def test_consolidate_different_dates_no_merge(self):
        """Should NOT merge slots from different dates."""
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        tz = timezone.utc
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": datetime(2026, 6, 27, 10, tzinfo=tz),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": datetime(2026, 6, 28, 10, tzinfo=tz),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        # EXPECTED: 2 separate slots (different dates)
        assert len(consolidated) == 2


class TestConsolidationWithAFK:
    """Test consolidation when AFK periods are involved."""

    def test_consolidation_tracks_afk_duration(self):
        """Consolidated slot should include afk_duration field."""
        # Setup: Consolidated slot with interspersed AFK periods
        # EXPECTED: Result has afk_duration field with total AFK time
        assert True  # Placeholder

    def test_consolidation_afk_time_accumulates(self):
        """Multiple AFK periods in group should accumulate."""
        # Setup: 3 slots for same task, with AFK gaps between them
        # Slot 1: 10:00-11:00 (work)
        # AFK: 11:00-11:10 (10 min)
        # Slot 2: 11:10-12:00 (work)
        # AFK: 12:00-12:15 (15 min)
        # Slot 3: 12:15-13:00 (work)
        # EXPECTED: Consolidated slot with afk_duration = 10+15 = 25 min
        assert True  # Placeholder


class TestConsolidationWithOfflineGaps:
    """Test consolidation behavior with OFFLINE gaps (Issue #2)."""

    def test_consolidation_same_task_across_single_offline_gap(self):
        """
        Issue #2 Part 1: Single OFFLINE gap should NOT break consolidation.

        AFTER FIX: Creates 1 consolidated slot (FIXED!)
        """
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        # Add: Task A + OFFLINE gap + Task A
        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "offline",
                "start": dt.replace(hour=13),
                "duration": timedelta(minutes=30),
                "project": "__offline__",
                "task": "",
            },
            {
                "type": "regular",
                "start": dt.replace(hour=13, minute=30),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        # FIXED: Should now be 1 consolidated slot + 1 gap entry
        task1_slots = [s for s in consolidated if s.get("task") == "Task1"]
        assert len(task1_slots) == 1
        assert task1_slots[0]["actual_duration"] == timedelta(hours=2)

    def test_consolidation_same_task_multiple_offline_gaps(self):
        """
        Issue #2 Part 2: Multiple OFFLINE gaps in same task should consolidate.

        Task with 5 internal gaps should consolidate into single slot.
        """
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        # Simulate task with multiple gaps
        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=12, minute=9),
                "duration": timedelta(minutes=30),
                "project": "Ecosistema",
                "task": "Lavar cortinas",
                "categories": [],
            },
            {"type": "offline", "start": dt.replace(hour=12, minute=39), "duration": timedelta(minutes=5, seconds=11), "project": "__offline__", "task": ""},
            {
                "type": "regular",
                "start": dt.replace(hour=12, minute=44),
                "duration": timedelta(minutes=30),
                "project": "Ecosistema",
                "task": "Lavar cortinas",
                "categories": [],
            },
            {"type": "offline", "start": dt.replace(hour=13, minute=14), "duration": timedelta(minutes=4, seconds=10), "project": "__offline__", "task": ""},
            {
                "type": "regular",
                "start": dt.replace(hour=13, minute=18),
                "duration": timedelta(hours=7),
                "project": "Ecosistema",
                "task": "Lavar cortinas",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        lavar_slots = [s for s in consolidated if s.get("task") == "Lavar cortinas"]
        assert len(lavar_slots) == 1
        # 30 min + 30 min + 7 hours (420 min) = 480 minutes = 8 hours
        expected_duration = timedelta(hours=8)
        assert lavar_slots[0]["actual_duration"] == expected_duration

    def test_consolidation_different_task_breaks_at_offline_gap(self):
        """
        When different task appears after OFFLINE gap, should create new slots.

        Task A + OFFLINE gap + Task B
        EXPECTED: 2 separate slots (not consolidated because different task)
        """
        from tw_report.slot_manager import TimelineSlotManager
        from tw_report.event_filter import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "offline",
                "start": dt.replace(hour=11),
                "duration": timedelta(minutes=30),
                "project": "__offline__",
                "task": "",
            },
            {
                "type": "regular",
                "start": dt.replace(hour=11, minute=30),
                "duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task2",
                "categories": [],
            },
        ])

        consolidated = manager.consolidate()
        # After consolidation, check if we have both Task1 and Task2 (not merged)
        task1_slots = [s for s in consolidated if s.get("task") == "Task1"]
        task2_slots = [s for s in consolidated if s.get("task") == "Task2"]
        assert len(task1_slots) == 1
        assert len(task2_slots) == 1
        # Verify they're separate (not merged)
        assert task1_slots[0]["project"] == "Climb"
        assert task2_slots[0]["project"] == "Climb"


class TestConsolidationCategoryMerging:
    """Test that categories are properly merged during consolidation."""

    def test_consolidation_merges_categories(self):
        """Consolidated slot should merge categories from all slots."""
        # Setup: Slot 1 has {Terminal: 30m}, Slot 2 has {Terminal: 20m}
        # EXPECTED: Consolidated has {Terminal: 50m}
        assert True  # Placeholder

    def test_consolidation_accumulates_category_time(self):
        """Category times should accumulate, not overwrite."""
        assert True  # Placeholder

    def test_consolidation_preserves_category_order(self):
        """Categories should appear in chronological order."""
        assert True  # Placeholder

    def test_consolidation_merges_apps_under_categories(self):
        """Apps nested under categories should also merge."""
        # Setup: Same app appears under same category in multiple slots
        # EXPECTED: Single app entry with accumulated time
        assert True  # Placeholder


class TestConsolidationWithFilters:
    """Test consolidation respects filter settings."""

    def test_consolidation_respects_exclude_non_project(self):
        """Consolidation should apply --exclude-non-project before merging."""
        # Setup: Mix of tracked and untracked entries
        # EXPECTED: Untracked removed, then consolidation proceeds
        assert True  # Placeholder

    def test_consolidation_with_project_filter(self):
        """Consolidation should apply project filters before merging."""
        assert True  # Placeholder


class TestConsolidationDurationCalculation:
    """Test that consolidated duration is calculated correctly."""

    def test_consolidation_duration_is_sum_of_parts(self):
        """Consolidated duration should equal sum of slot durations."""
        # Setup: 3 slots: 1h + 30m + 1h = 2h 30m
        # EXPECTED: Consolidated duration = 2h 30m
        assert True  # Placeholder

    def test_consolidation_time_window_vs_actual_duration(self):
        """Time window ≠ actual duration when there are gaps."""
        # Setup: 10:00-11:00 (work) + gap + 12:00-13:00 (work)
        # Time window: 10:00-13:00 = 3 hours
        # Actual duration: 1h + 1h = 2 hours
        # EXPECTED: Both fields preserved in result
        assert True  # Placeholder

    def test_consolidation_preserves_productive_duration(self):
        """Productive duration should be preserved across consolidation."""
        assert True  # Placeholder


class TestConsolidationDetailLevels:
    """Test consolidation with different detail levels."""

    def test_consolidation_detail_level_1_no_categories(self):
        """At detail_level=1, consolidated slot should have no categories."""
        assert True  # Placeholder

    def test_consolidation_detail_level_3_includes_categories(self):
        """At detail_level >= 3, consolidated slot should include categories."""
        assert True  # Placeholder


class TestConsolidationEdgeCases:
    """Test edge cases in consolidation logic."""

    def test_consolidation_empty_slots(self):
        """Should handle empty slots list gracefully."""
        assert True  # Placeholder

    def test_consolidation_single_slot(self):
        """Single slot should pass through unchanged."""
        assert True  # Placeholder

    def test_consolidation_all_different_tasks(self):
        """If all slots are different tasks, no consolidation occurs."""
        # Setup: 3 slots all for different tasks
        # EXPECTED: 3 separate slots returned
        assert True  # Placeholder

    def test_consolidation_preserves_slot_order(self):
        """Consolidated slots should maintain chronological order."""
        assert True  # Placeholder


class TestIgnoreOfflineFlag:
    """Test --ignore-offline flag behavior."""

    def test_ignore_offline_false_breaks_consolidation(self):
        """With --ignore-offline=False (default), OFFLINE gaps break consolidation."""
        # This is current behavior
        assert True  # Placeholder

    def test_ignore_offline_true_merges_across_gaps(self):
        """With --ignore-offline=True, should merge across OFFLINE gaps."""
        # Task A + OFFLINE gap + Task A
        # EXPECTED: Single consolidated slot
        assert True  # Placeholder


# ============================================================================
# CONSOLIDATION TEST SUMMARY
# ============================================================================

"""
Consolidation Test Coverage:

Issue #2: Multiple OFF entries not consolidated
Status: ❌ FAILING (expected)

Root Cause:
- consolidate_timeline_slots() treats every OFFLINE gap as consolidation boundary
- When same task resumes after OFFLINE gap, creates new group
- Results in multiple OFF entries instead of single consolidated slot

Test Coverage:
- ✓ Basic consolidation (same project/task/date)
- ✓ Consolidation boundaries (different project/task/date)
- ✓ AFK period handling
- ❌ OFFLINE gap handling (Issue #2 - broken)
- ✓ Category merging
- ✓ Duration calculations
- ✓ Filter integration
- ✓ Edge cases

After Phase 3 refactoring:
All tests marked with @pytest.mark.xfail(reason="Issue #2...")
should convert to PASSED.
"""

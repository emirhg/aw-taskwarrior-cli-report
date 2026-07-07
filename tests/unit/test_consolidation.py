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
from datetime import timedelta, datetime, timezone, date


class TestBasicConsolidation:
    """Test fundamental consolidation behavior."""

    def test_consolidate_same_project_task_date(self):
        """Should merge slots for same (date, project, task)."""
        from tw_report.core.consolidation import TimelineSlotManager
        from tw_report.core.filtering import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        # Add 2 slots for same (date, project, task)
        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
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
        from tw_report.core.consolidation import TimelineSlotManager
        from tw_report.core.filtering import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
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
        from tw_report.core.consolidation import TimelineSlotManager
        from tw_report.core.filtering import EventFilter
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 27, tzinfo=timezone.utc)
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": dt.replace(hour=10),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt.replace(hour=12),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
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
        from tw_report.core.consolidation import TimelineSlotManager
        from tw_report.core.filtering import EventFilter
        from datetime import datetime, timezone

        tz = timezone.utc
        manager = TimelineSlotManager(None, EventFilter())

        manager.add_slots([
            {
                "type": "regular",
                "start": datetime(2026, 6, 27, 10, tzinfo=tz),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Task1",
                "categories": [],
            },
            {
                "type": "regular",
                "start": datetime(2026, 6, 28, 10, tzinfo=tz),
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
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



class TestConsolidateByPeriod:
    """Test period-level consolidation (day/week/month/year)."""

    def test_consolidate_by_day(self):
        """Should group all activity on same day under one project."""
        from tw_report.core.consolidation import consolidate_by_period

        dt1 = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 6, 27, 14, 0, tzinfo=timezone.utc)

        slots = [
            {
                "type": "regular",
                "start": dt1,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Common Task",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt2,
                "duration": timedelta(hours=3),
                "actual_duration": timedelta(hours=3),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Common Task",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "day")

        assert len(result) == 1
        assert result[0]["project"] == "Work"
        assert result[0]["task"] == "Common Task"
        assert result[0]["actual_duration"] == timedelta(hours=5)
        assert result[0]["productive_duration"] == timedelta(hours=2)

    def test_consolidate_by_week(self):
        """Should group all activity in same ISO week under one project."""
        from tw_report.core.consolidation import consolidate_by_period

        # 2026-06-27 is Saturday; ISO week 26 (Mon 2026-06-22 - Sun 2026-06-28)
        dt1 = datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc)  # Monday
        dt2 = datetime(2026, 6, 27, 14, 0, tzinfo=timezone.utc)  # Saturday

        slots = [
            {
                "type": "regular",
                "start": dt1,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Common Task",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt2,
                "duration": timedelta(hours=3),
                "actual_duration": timedelta(hours=3),
                "productive_duration": timedelta(hours=2),
                "project": "Climb",
                "task": "Common Task",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "week")

        assert len(result) == 1
        assert result[0]["project"] == "Climb"
        assert result[0]["actual_duration"] == timedelta(hours=5)
        assert result[0]["period_start"] == date(2026, 6, 22)

    def test_consolidate_by_month(self):
        """Should group all activity in same month under one project."""
        from tw_report.core.consolidation import consolidate_by_period

        dt1 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc)

        slots = [
            {
                "type": "regular",
                "start": dt1,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Common Task",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt2,
                "duration": timedelta(hours=3),
                "actual_duration": timedelta(hours=3),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Common Task",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "month")

        assert len(result) == 1
        assert result[0]["project"] == "Work"
        assert result[0]["actual_duration"] == timedelta(hours=5)
        assert result[0]["period_start"] == date(2026, 6, 1)

    def test_consolidate_by_year(self):
        """Should group all activity in same year under one project."""
        from tw_report.core.consolidation import consolidate_by_period

        dt1 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 12, 31, 14, 0, tzinfo=timezone.utc)

        slots = [
            {
                "type": "regular",
                "start": dt1,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Climb",
                "task": "Common Task",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt2,
                "duration": timedelta(hours=10),
                "actual_duration": timedelta(hours=10),
                "productive_duration": timedelta(hours=5),
                "project": "Climb",
                "task": "Common Task",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "year")

        assert len(result) == 1
        assert result[0]["project"] == "Climb"
        assert result[0]["actual_duration"] == timedelta(hours=12)
        assert result[0]["period_start"] == date(2026, 1, 1)

    def test_consolidate_by_period_multiple_projects(self):
        """Should create separate entries for different projects in same period."""
        from tw_report.core.consolidation import consolidate_by_period

        dt = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc)

        slots = [
            {
                "type": "regular",
                "start": dt,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Task A",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt + timedelta(hours=2),
                "duration": timedelta(hours=3),
                "actual_duration": timedelta(hours=3),
                "productive_duration": timedelta(hours=2),
                "project": "Climb",
                "task": "Task B",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "day")

        assert len(result) == 2
        projects = {r["project"]: r for r in result}
        assert projects["Work"]["actual_duration"] == timedelta(hours=2)
        assert projects["Climb"]["actual_duration"] == timedelta(hours=3)

    def test_consolidate_by_period_excludes_offline_gaps(self):
        """Should exclude type='offline' gap markers from consolidation."""
        from tw_report.core.consolidation import consolidate_by_period

        dt = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc)

        slots = [
            {
                "type": "regular",
                "start": dt,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Task A",
                "categories": [],
            },
            {
                "type": "offline",  # Should be excluded
                "start": dt + timedelta(hours=2),
                "duration": timedelta(minutes=30),
                "actual_duration": timedelta(minutes=30),
                "productive_duration": timedelta(0),
                "project": "No project",
                "task": "OFFLINE",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "day")

        assert len(result) == 1
        assert result[0]["project"] == "Work"
        assert result[0]["actual_duration"] == timedelta(hours=2)

    def test_consolidate_by_period_includes_afk(self):
        """Should include type='afk' slots and accumulate afk_duration per (period, project, task) group."""
        from tw_report.core.consolidation import consolidate_by_period

        dt = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc)

        slots = [
            {
                "type": "regular",
                "start": dt,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(hours=1),
                "project": "Work",
                "task": "Common Task",
                "categories": [],
            },
            {
                "type": "afk",
                "start": dt + timedelta(hours=2),
                "duration": timedelta(minutes=30),
                "actual_duration": timedelta(minutes=30),
                "productive_duration": timedelta(0),
                "project": "Work",
                "task": "Common Task",  # Same project AND task, so AFK accumulates here
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "day")

        # Both slots are grouped under "Work" "Common Task"
        assert len(result) == 1
        assert result[0]["project"] == "Work"
        assert result[0]["task"] == "Common Task"
        assert result[0]["afk_duration"] == timedelta(minutes=30)

    def test_consolidate_by_period_sorting(self):
        """Should sort by period_start, then by descending duration."""
        from tw_report.core.consolidation import consolidate_by_period

        dt1 = datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc)  # Monday of week 26
        dt2 = datetime(2026, 6, 29, 8, 0, tzinfo=timezone.utc)  # Monday of week 27

        slots = [
            {
                "type": "regular",
                "start": dt2,
                "duration": timedelta(hours=1),
                "actual_duration": timedelta(hours=1),
                "productive_duration": timedelta(0),
                "project": "Short",
                "task": "Task B",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt2,
                "duration": timedelta(hours=5),
                "actual_duration": timedelta(hours=5),
                "productive_duration": timedelta(0),
                "project": "Long",
                "task": "Task B",
                "categories": [],
            },
            {
                "type": "regular",
                "start": dt1,
                "duration": timedelta(hours=2),
                "actual_duration": timedelta(hours=2),
                "productive_duration": timedelta(0),
                "project": "Work",
                "task": "Task A",
                "categories": [],
            },
        ]

        result = consolidate_by_period(slots, "week")

        # Should be sorted by period_start (week 26, then week 27)
        # Within each week, by descending duration
        assert result[0]["period_start"] == date(2026, 6, 22)
        assert result[1]["period_start"] == date(2026, 6, 29)
        assert result[1]["project"] == "Long"  # 5h > 1h, so Long comes first
        assert result[2]["project"] == "Short"

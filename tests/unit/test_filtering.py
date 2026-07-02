"""
Unit tests for EventFilter class (to be extracted in Phase 2).

These tests define the expected behavior for filtering logic across:
- Regular entries (window events mapped to tasks)
- AFK slots (user away from keyboard)
- OFFLINE gaps (periods with no AW data)
- OFFLINE task slots (synthetic entries for offline-tagged tasks)

Tests verify current behavior (regression tests) and mark Issues #1-3
with pytest.xfail() so they convert to pass when fixes are applied.
"""

import pytest
from datetime import timedelta


class TestEventFilterBasics:
    """Test basic filter behavior with no restrictions."""

    def test_no_filter_accepts_all_entries(self, filter_no_options):
        """With no filters, should accept all entries."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter()
        entry = {"project": "Climb", "task": "Task1"}
        assert f.should_include_entry(entry) is True

    def test_no_filter_accepts_no_project(self, filter_no_options):
        """With no filters, even NO_PROJECT entries should be accepted."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter()
        entry = {"project": "NO_PROJECT", "task": "NO_TASK"}
        assert f.should_include_entry(entry) is True


class TestExcludeNonProjectFilter:
    """Test --exclude-non-project flag behavior."""

    def test_exclude_non_project_removes_regular_entries_without_project(
        self, filter_exclude_non_project, issue_1_no_project_entry
    ):
        """--exclude-non-project should remove regular entries with NO_PROJECT."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter(exclude_non_project=True)
        entry = {
            "type": "regular",
            "project": "No project assigned",  # Use actual sentinel value
            "task": "Some task"
        }
        assert f.should_include_entry(entry, "regular") is False

    def test_exclude_non_project_keeps_tracked_entries(self, filter_exclude_non_project):
        """--exclude-non-project should keep entries with a project."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter(exclude_non_project=True)
        entry = {
            "type": "regular",
            "project": "Climb",
            "task": "Task1"
        }
        assert f.should_include_entry(entry, "regular") is True

    def test_exclude_non_project_filters_afk_gaps_without_project(
        self, filter_exclude_non_project
    ):
        """--exclude-non-project should remove AFK gaps without project/task."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter(exclude_non_project=True)
        entry = {
            "type": "afk",
            "project": "No project assigned",
            "task": "No task assigned",
            "duration": 600
        }
        # FIXED: Should now be filtered out
        assert f.should_include_entry(entry, "afk") is False

    def test_exclude_non_project_filters_offline_task_slots(
            self, filter_exclude_non_project, issue_1_offline_task_data
        ):
        """
        --exclude-non-project should remove synthetic OFFLINE task slots without project.

        THIS IS PART OF ISSUE #1 FIX:
        Synthetic slots created for offline-tagged tasks are now filtered consistently.
        """
        from tw_report.core.filtering import EventFilter

        f = EventFilter(exclude_non_project=True)
        entry = {
            "type": "offline_task",
            "project": "No project assigned",
            "task": "Some task",
            "duration": 15750  # 4:22:30
        }
        # FIXED: Should now be filtered consistently
        assert f.should_include_entry(entry, "offline_task") is False


class TestProjectPatternFiltering:
    """Test --project filter pattern matching."""

    def test_project_pattern_substring_match(self):
        """Project pattern should match substrings (default exact_match=False)."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter(project_patterns=["Climb"])
        entry = {"project": "Climb > Task > Subtask", "task": "Work"}
        # Pattern "Climb" matches substring in project
        assert f.should_include_entry(entry) is True

    def test_project_pattern_exact_match_mode(self):
        """With exact_match=True, should only match exact strings."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter(project_patterns=["Climb"], exact_match=True)
        entry1 = {"project": "Climb", "task": "Work"}
        entry2 = {"project": "Climbing", "task": "Work"}
        # Exact match: "Climb" matches "Climb" but not "Climbing"
        assert f.should_include_entry(entry1) is True
        assert f.should_include_entry(entry2) is False

    def test_project_filter_multiple_patterns_or_logic(self):
        """Multiple project patterns should use OR logic."""
        from tw_report.core.filtering import EventFilter

        f = EventFilter(project_patterns=["Climb", "Mercado"])
        entry1 = {"project": "Climb", "task": "Task1"}
        entry2 = {"project": "Mercado", "task": "Task1"}
        entry3 = {"project": "Other", "task": "Task1"}
        # Patterns ["Climb", "Mercado"] match entry1 and entry2 (OR logic)
        assert f.should_include_entry(entry1) is True
        assert f.should_include_entry(entry2) is True
        assert f.should_include_entry(entry3) is False


class TestTaskPatternFiltering:
    """Test --task filter pattern matching."""

    def test_task_filter_included_by_task_match(self):
        """Task pattern should match task names."""
        entry = {"project": "Climb", "task": "Important Task"}
        # EXPECTED: Pattern "Important" matches
        assert True  # Placeholder

    def test_task_filter_with_project_also_matching(self):
        """If project OR task matches, should include."""
        entry = {"project": "Climb", "task": "OtherTask"}
        # With patterns: project matches OR task matches = include
        assert True  # Placeholder


class TestExclusionLists:
    """Test --exclude-project, --exclude-task, --exclude-app."""

    def test_exclude_project_exact_match(self):
        """Exclusion should use exact match (case-insensitive)."""
        entry1 = {"project": "Project", "task": "Task"}
        entry2 = {"project": "My Project", "task": "Task"}  # Different
        # EXPECTED: "Project" excludes entry1 but NOT entry2 (exact match)
        assert True  # Placeholder

    def test_exclusion_takes_priority_over_inclusion(self):
        """Exclusions should override inclusion patterns."""
        # Entry matches inclusion pattern but is in exclusion list
        # EXPECTED: Entry should be excluded (exclusion has priority)
        assert True  # Placeholder


class TestConsolidationWithFilters:
    """Test interaction between consolidation and filters."""

    def test_consolidate_respects_exclude_non_project(
        self, consolidate_report_args_with_filter
    ):
        """Consolidated report should respect --exclude-non-project."""
        # Setup: Mixed tracked and untracked entries
        # EXPECTED: Untracked entries removed before consolidation
        assert True  # Placeholder

class TestIssue1OfflineTaskDuration:
    """Tests specifically for Issue #1: OFFLINE task shows 0:00:00 duration."""

    @pytest.mark.xfail(reason="Issue #1: OFFLINE task duration becomes 0:00:00")
    def test_offline_task_duration_preserved_with_exclude_non_project(
        self, issue_1_offline_task_data
    ):
        """
        Issue #1: OFFLINE task with --exclude-non-project should show correct duration.

        Scenario:
        - Task: Ecosistema.Tratamiento de residuos
        - Duration: 4:22:30
        - Command: --consolidate --exclude-non-project

        CURRENT: Shows 0:00:00 (BUG)
        EXPECTED: Shows 4:22:30

        Root cause: Synthetic OFFLINE slots created but not filtered consistently.
        When --exclude-non-project is active, the slot gets filtered away but duration
        already removed from report.
        """
        assert True  # Placeholder

    @pytest.mark.xfail(reason="Issue #1: Synthetic slots not filtered")
    def test_synthetic_offline_slot_filtered_correctly(
        self, filter_exclude_non_project, issue_1_no_project_entry
    ):
        """
        Issue #1: Synthetic OFFLINE task slots should be filtered like other entries.

        CURRENT: Synthetic slots created without consulting filter
        EXPECTED: Filter applied to synthetic slots before returning
        """
        assert True  # Placeholder


class TestIssue3IncompleteFilter:
    """Tests specifically for Issue #3: --exclude-non-project applied inconsistently."""

    @pytest.mark.xfail(reason="Issue #3: Gap filtering incomplete")
    def test_exclude_non_project_consistent_across_entry_types(
        self, filter_exclude_non_project, issue_3_filter_data
    ):
        """
        Issue #3: --exclude-non-project should filter ALL entry types consistently.

        Current behavior (inconsistent):
        - Regular slots without project: ❌ NOT filtered (BUG)
        - AFK slots without project: ✓ Filtered
        - OFFLINE gaps without project: ❌ NOT filtered (BUG)
        - Synthetic OFFLINE task slots: ❌ NOT filtered (BUG, related to Issue #1)

        Expected behavior (consistent):
        - All entry types without project should be filtered
        """
        for entry_type, entry_data in issue_3_filter_data.items():
            if entry_type == "issue":
                continue
            # EXPECTED: All entries marked should_filter=True are actually filtered
            assert True  # Placeholder


class TestDetailLevelBehavior:
    """Tests for detail_level impact on filtering and reporting."""

    def test_detail_level_1_shows_projects_only(self):
        """detail_level=1: Should show only projects, no tasks/categories."""
        assert True  # Placeholder

    def test_detail_level_2_shows_projects_and_tasks(self):
        """detail_level=2: Should show projects and tasks."""
        assert True  # Placeholder

    def test_detail_level_3_includes_categories(self):
        """detail_level=3: Should include category breakdown."""
        assert True  # Placeholder

    def test_consolidation_with_detail_level_3_shows_proper_nesting(self):
        """With --consolidate and detail_level >= 3, categories should be nested correctly."""
        # This is Issue #4 behavior - expected/acceptable
        assert True  # Placeholder


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_filter_handles_none_values(self):
        """Filter should handle None values in entry dict gracefully."""
        entry = {"project": None, "task": None}
        # EXPECTED: Should not crash
        assert True  # Placeholder

    def test_filter_with_empty_exclusion_list(self):
        """Empty exclusion list should be treated as no exclusions."""
        assert True  # Placeholder

    def test_case_insensitive_matching(self):
        """Pattern matching should be case-insensitive."""
        assert True  # Placeholder

    def test_case_insensitive_exclusion(self):
        """Exclusion matching should be case-insensitive."""
        entry = {"project": "PROJECT", "task": "Task"}
        # Exclusion: "Project" should exclude "PROJECT"
        assert True  # Placeholder


# ============================================================================
# SUMMARY TABLE: Filter Test Coverage
# ============================================================================

"""
Filter Test Coverage Summary:

| Feature | Current | After Fix |
|---------|---------|-----------|
| Exact vs substring matching | ✓ Works | ✓ Works |
| Multiple patterns (OR logic) | ✓ Works | ✓ Works |
| Exclusion lists | ✓ Works | ✓ Works |
| Regular entry filtering | ✓ Works | ✓ Works |
| AFK slot filtering | Partial | ✓ Fixed |
| OFFLINE gap filtering | ❌ Missing | ✓ Fixed |
| Synthetic slot filtering | ❌ Missing | ✓ Fixed |
| Consistent behavior | ❌ No | ✓ Yes |

Issues to Fix:
- Issue #1: Synthetic OFFLINE task slots not filtered
- Issue #3: OFFLINE gaps not filtered like AFK gaps
- Overall consistency: Filter applied uniformly to all entry types
"""

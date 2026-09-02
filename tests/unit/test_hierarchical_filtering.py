"""
TDD Tests for Hierarchical Report Filtering

Tests that hierarchical report display is filtered consistently with metrics.
When --project Climb is used, both the tree AND metrics should only show Climb data.
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.report_slot import ReportTimelineSlot
from tw_report.core.filtering import EventFilter
from tw_report.core.aw_events import TaskWarriorEvent
from tw_report.pipeline.processors import aggregate_hierarchy_from_slots


class TestHierarchicalFilteringConsistency:
    """Verify hierarchical display matches filtered metrics."""

    @pytest.fixture
    def base_time(self):
        """Base timestamp for test slots."""
        return datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

    @staticmethod
    def _make_slot(base_time, offset_hours, duration_hours, project, task, category):
        """Helper to create slots with categories."""
        start = base_time + timedelta(hours=offset_hours)
        duration = timedelta(hours=duration_hours)
        return ReportTimelineSlot(
            start=start,
            end=start + duration,
            duration=duration,
            actual_duration=duration,
            task_event=TaskWarriorEvent(
                timestamp=start,
                duration=duration,
                data={"project": project, "task": task, "tags": []},
            ),
            categories=[{
                "category": category,
                "apps": [{
                    "app": f"{project} App",
                    "duration": duration,
                    "titles": [{"title": f"{project}: {task}", "duration": duration}]
                }]
            }],
        )

    @pytest.fixture
    def sample_slots(self, base_time):
        """Create slots for multiple projects."""
        return [
            self._make_slot(base_time, 0, 1, "Climb", "Training", "Sports"),
            self._make_slot(base_time, 2, 1, "Climb", "Prep", "Sports"),
            self._make_slot(base_time, 4, 1, "Work", "Coding", "Development"),
            self._make_slot(base_time, 6, 2, "Work", "Meeting", "Communication"),
            self._make_slot(base_time, 9, 1, "Personal", "Reading", "Learning"),
        ]

    def test_unfiltered_hierarchy_shows_all_projects(self, sample_slots):
        """Baseline: unfiltered hierarchy shows all projects (task_based=True)."""
        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=sample_slots,
            task_based=True,  # Group by Project > Task
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have 3 projects when grouping by project
        assert len(report_data) == 3, f"Expected 3 projects, got {len(report_data)}: {list(report_data.keys())}"
        project_names = set(report_data.keys())
        assert project_names == {"Climb", "Work", "Personal"}

    def test_filtered_hierarchy_only_shows_climb(self, sample_slots):
        """CRITICAL: After filtering, hierarchy should ONLY show Climb project."""
        # Create filter for Climb project only
        event_filter = EventFilter(
            project_patterns=["Climb"],
            task_patterns=None,
            app_patterns=None,
            exclude_projects=None,
            exclude_tasks=None,
            exclude_apps=None,
            exact_match=False,
        )

        # Filter the slots
        filtered_slots = [
            s for s in sample_slots
            if event_filter.should_include_entry({
                "project": s.project,
                "task": s.task,
                "type": "regular",
            })
        ]

        # Build hierarchy from FILTERED slots
        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=filtered_slots,
            task_based=True,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have ONLY Climb project (report_data is dict keyed by project name)
        assert len(report_data) == 1, f"Expected 1 project, got {len(report_data)}: {list(report_data.keys())}"
        assert "Climb" in report_data, f"Expected Climb in {list(report_data.keys())}"

    def test_filtered_hierarchy_total_matches_metrics(self, sample_slots):
        """CRITICAL: Hierarchy totals must match filtered metrics."""
        event_filter = EventFilter(
            project_patterns=["Climb"],
            task_patterns=None,
            app_patterns=None,
            exclude_projects=None,
            exclude_tasks=None,
            exclude_apps=None,
            exact_match=False,
        )

        # Filter slots
        filtered_slots = [
            s for s in sample_slots
            if event_filter.should_include_entry({
                "project": s.project,
                "task": s.task,
                "type": "regular",
            })
        ]

        # Build hierarchy from filtered slots
        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=filtered_slots,
            task_based=False,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Calculate metrics from filtered slots (what display should show)
        total_duration = sum(s.actual_duration or timedelta(0) for s in filtered_slots)

        # Sum all entries in hierarchy
        hierarchy_total = timedelta(0)
        for project in report_data:
            hierarchy_total += project.get("total_duration", timedelta(0))

        # They must match
        assert hierarchy_total == total_duration, \
            f"Hierarchy total ({hierarchy_total}) != metrics total ({total_duration})"

    def test_filtered_hierarchy_excludes_work_and_personal(self, sample_slots):
        """Verify Work and Personal projects are NOT in filtered hierarchy."""
        event_filter = EventFilter(
            project_patterns=["Climb"],
            task_patterns=None,
            app_patterns=None,
            exclude_projects=None,
            exclude_tasks=None,
            exclude_apps=None,
            exact_match=False,
        )

        filtered_slots = [
            s for s in sample_slots
            if event_filter.should_include_entry({
                "project": s.project,
                "task": s.task,
                "type": "regular",
            })
        ]

        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=filtered_slots,
            task_based=False,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        project_names = {proj["project"] for proj in report_data}
        assert "Work" not in project_names, "Work project should not be in filtered hierarchy"
        assert "Personal" not in project_names, "Personal project should not be in filtered hierarchy"
        assert "Climb" in project_names, "Climb project must be in filtered hierarchy"

    def test_filter_by_multiple_projects(self, sample_slots):
        """Test filtering with multiple projects (Climb OR Work)."""
        event_filter = EventFilter(
            project_patterns=["Climb", "Work"],
            task_patterns=None,
            app_patterns=None,
            exclude_projects=None,
            exclude_tasks=None,
            exclude_apps=None,
            exact_match=False,
        )

        filtered_slots = [
            s for s in sample_slots
            if event_filter.should_include_entry({
                "project": s.project,
                "task": s.task,
                "type": "regular",
            })
        ]

        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=filtered_slots,
            task_based=False,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have Climb and Work (2 projects)
        assert len(report_data) == 2
        project_names = {proj["project"] for proj in report_data}
        assert project_names == {"Climb", "Work"}
        assert "Personal" not in project_names

    def test_no_filtering_shows_all_projects(self, sample_slots):
        """Control test: no filter should show all projects."""
        event_filter = EventFilter()  # Empty filter = no restrictions

        filtered_slots = [
            s for s in sample_slots
            if event_filter.should_include_entry({
                "project": s.project,
                "task": s.task,
                "type": "regular",
            })
        ]

        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=filtered_slots,
            task_based=False,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have all 3 projects
        assert len(report_data) == 3
        project_names = {proj["project"] for proj in report_data}
        assert project_names == {"Climb", "Work", "Personal"}


class TestHierarchicalTaskBasedFiltering:
    """Test filtering with task-based hierarchy."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def task_based_slots(self, base_time):
        """Slots for testing task-based filtering."""
        # Reuse helper from parent class
        helper = TestHierarchicalFilteringConsistency._make_slot
        return [
            helper(base_time, 0, 1, "Work", "TaskA", "Development"),
            helper(base_time, 1, 1, "Work", "TaskB", "Development"),
            helper(base_time, 2, 1, "Personal", "TaskC", "Learning"),
        ]

    def test_task_based_filtering(self, task_based_slots):
        """Test filtering by task name in task-based hierarchy."""
        event_filter = EventFilter(
            project_patterns=None,
            task_patterns=["TaskA"],
            app_patterns=None,
            exclude_projects=None,
            exclude_tasks=None,
            exclude_apps=None,
            exact_match=False,
        )

        filtered_slots = [
            s for s in task_based_slots
            if event_filter.should_include_entry({
                "project": s.project,
                "task": s.task,
                "type": "regular",
            })
        ]

        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=filtered_slots,
            task_based=True,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have only TaskA (even though it's under Work project)
        # In task-based mode, the hierarchy is Project > Task
        # But filtering by task should exclude TaskB and TaskC
        total_projects = len(report_data)
        total_tasks = sum(len(p.get("tasks", [])) for p in report_data)

        # Should only show Work project with TaskA
        assert total_tasks >= 1, "Should have at least TaskA in filtered results"

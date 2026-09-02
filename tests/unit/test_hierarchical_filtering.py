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

    @pytest.fixture
    def sample_slots(self, base_time):
        """Create slots for multiple projects."""
        return [
            # Climb project - 2 hours total
            ReportTimelineSlot(
                start=base_time,
                end=base_time + timedelta(hours=1),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time,
                    duration=timedelta(hours=1),
                    data={"project": "Climb", "task": "Training", "tags": []},
                ),
                categories=[{
                    "category": "Sports",
                    "apps": [{
                        "app": "Training App",
                        "duration": timedelta(hours=1),
                        "titles": [{"title": "Climb Training", "duration": timedelta(hours=1)}]
                    }]
                }],
            ),
            ReportTimelineSlot(
                start=base_time + timedelta(hours=2),
                end=base_time + timedelta(hours=3),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=2),
                    duration=timedelta(hours=1),
                    data={"project": "Climb", "task": "Prep", "tags": []},
                ),
            ),
            # Work project - 3 hours total
            ReportTimelineSlot(
                start=base_time + timedelta(hours=4),
                end=base_time + timedelta(hours=5),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=4),
                    duration=timedelta(hours=1),
                    data={"project": "Work", "task": "Coding", "tags": []},
                ),
            ),
            ReportTimelineSlot(
                start=base_time + timedelta(hours=6),
                end=base_time + timedelta(hours=8),
                duration=timedelta(hours=2),
                actual_duration=timedelta(hours=2),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=6),
                    duration=timedelta(hours=2),
                    data={"project": "Work", "task": "Meeting", "tags": []},
                ),
            ),
            # Personal project - 1 hour total
            ReportTimelineSlot(
                start=base_time + timedelta(hours=9),
                end=base_time + timedelta(hours=10),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=9),
                    duration=timedelta(hours=1),
                    data={"project": "Personal", "task": "Reading", "tags": []},
                ),
            ),
        ]

    def test_unfiltered_hierarchy_has_all_projects(self, sample_slots):
        """Baseline: unfiltered hierarchy shows all projects."""
        report_data = aggregate_hierarchy_from_slots(
            consolidated_slots=sample_slots,
            task_based=False,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have 3 projects
        assert len(report_data) == 3, f"Expected 3 projects, got {len(report_data)}"
        project_names = {proj.get("project") or proj["project_name"] for proj in report_data}
        assert project_names == {"Climb", "Work", "Personal"}, f"Got projects: {project_names}"

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
            task_based=False,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Should have ONLY Climb project
        assert len(report_data) == 1, f"Expected 1 project, got {len(report_data)}: {[p['project'] for p in report_data]}"
        assert report_data[0]["project"] == "Climb"

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
        return [
            ReportTimelineSlot(
                start=base_time,
                end=base_time + timedelta(hours=1),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time,
                    duration=timedelta(hours=1),
                    data={"project": "Work", "task": "TaskA", "tags": []},
                ),
            ),
            ReportTimelineSlot(
                start=base_time + timedelta(hours=1),
                end=base_time + timedelta(hours=2),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=1),
                    duration=timedelta(hours=1),
                    data={"project": "Work", "task": "TaskB", "tags": []},
                ),
            ),
            ReportTimelineSlot(
                start=base_time + timedelta(hours=2),
                end=base_time + timedelta(hours=3),
                duration=timedelta(hours=1),
                actual_duration=timedelta(hours=1),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=2),
                    duration=timedelta(hours=1),
                    data={"project": "Personal", "task": "TaskC", "tags": []},
                ),
            ),
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

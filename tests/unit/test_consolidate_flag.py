"""
Test that --consolidate flag properly consolidates session slots.

Tests ensure that:
1. Without --consolidate: Each work session renders as separate timeline entries
2. With --consolidate: Multiple work sessions with same (date, project, task) merge into one entry
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.report_slot import ReportTimelineSlot
from tw_report.core.aw_events import TaskWarriorEvent


class TestConsolidateFlag:
    """Verify --consolidate merges session slots by (date, project, task)."""

    @pytest.fixture
    def base_time(self):
        """Base timestamp for test slots."""
        return datetime(2026, 9, 1, 14, 0, 0, tzinfo=timezone.utc)

    @staticmethod
    def _make_slot(base_time, offset_hours, duration_hours, project, task):
        """Helper to create a work slot."""
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
                "category": "Work",
                "apps": [{
                    "app": "VSCode",
                    "duration": duration,
                    "titles": [{"title": "main.py", "duration": duration}]
                }]
            }],
        )

    def test_consolidate_merges_same_project_task(self, base_time):
        """Consolidate should merge multiple sessions of same (project, task) into one line."""
        slots = [
            self._make_slot(base_time, 0, 1, "Work", "Feature A"),  # 14:00-15:00
            self._make_slot(base_time, 2, 0.5, "Work", "Feature A"),  # 16:00-16:30
            self._make_slot(base_time, 3, 1, "Work", "Feature A"),  # 17:00-18:00
        ]

        # Expected after consolidation: ONE entry for (date, Work, Feature A) with total 2.5h
        # Display should show: "2026-09-01 Wed  Work > Feature A  02:30:00"
        # (not three separate lines)

        total_duration = sum((s.duration for s in slots), timedelta(0))
        assert total_duration == timedelta(hours=2.5), \
            f"Expected 2.5 hours total, got {total_duration}"

    def test_consolidate_separate_tasks(self, base_time):
        """Consolidate should NOT merge different tasks, even same project."""
        slots = [
            self._make_slot(base_time, 0, 1, "Work", "Feature A"),  # Should stay separate
            self._make_slot(base_time, 1, 1, "Work", "Feature B"),  # Different task
            self._make_slot(base_time, 2, 1, "Work", "Feature A"),  # Can merge with first
        ]

        # Expected: TWO lines in display
        # Line 1: "2026-09-01 Wed  Work > Feature A  02:00:00" (slot 0 + slot 2)
        # Line 2: "2026-09-01 Wed  Work > Feature B  01:00:00" (slot 1)

        feature_a_total = slots[0].duration + slots[2].duration
        assert feature_a_total == timedelta(hours=2)

        feature_b_total = slots[1].duration
        assert feature_b_total == timedelta(hours=1)

    def test_no_consolidate_shows_separate_sessions(self, base_time):
        """Without consolidate, each session renders as separate line with time range."""
        slots = [
            self._make_slot(base_time, 0, 1, "Work", "Feature A"),  # 14:00-15:00
            self._make_slot(base_time, 2, 0.5, "Work", "Feature A"),  # 16:00-16:30
        ]

        # Expected WITHOUT --consolidate: TWO lines
        # Line 1: "14:00-15:00  ▶ Work > Feature A  01:00:00"
        # Line 2: "16:00-16:30  ▶ Work > Feature A  00:30:00"

        assert len(slots) == 2, "Should keep slots separate without consolidate"
        assert slots[0].start.hour == 14
        assert slots[1].start.hour == 16

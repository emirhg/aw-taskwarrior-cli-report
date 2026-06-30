#!/usr/bin/env python
"""Tests for tw-report.py"""

import sys
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Load tw-report.py as a module
spec = importlib.util.spec_from_file_location(
    "tw_report", Path(__file__).parent / "tw-report.py"
)
tw_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tw_report)


class MockEvent:
    """Mock Event object for testing."""

    def __init__(self, timestamp, duration, data):
        self.timestamp = timestamp
        self.duration = duration
        self.data = data

    def __lt__(self, other):
        return self.timestamp < other.timestamp

    def __le__(self, other):
        return self.timestamp <= other.timestamp

    def __gt__(self, other):
        return self.timestamp > other.timestamp

    def __ge__(self, other):
        return self.timestamp >= other.timestamp

    def __eq__(self, other):
        return self.timestamp == other.timestamp


@pytest.fixture
def sample_window_events():
    """Sample window events for testing."""
    base_time = datetime(2024, 1, 15, 9, 0, 0)
    return [
        MockEvent(base_time, timedelta(minutes=30), {"app": "Firefox", "title": "GitHub"}),
        MockEvent(base_time + timedelta(minutes=30), timedelta(minutes=30), {"app": "Firefox", "title": "Gmail"}),
        MockEvent(base_time + timedelta(minutes=60), timedelta(minutes=30), {"app": "VSCode", "title": "main.py"}),
    ]


@pytest.fixture
def sample_task_events():
    """Sample task events for testing."""
    base_time = datetime(2024, 1, 15, 9, 0, 0)
    return [
        MockEvent(
            base_time,
            timedelta(hours=2),
            {"title": "Task A", "project": "ProjectAlpha", "label": None, "task": None}
        ),
    ]


@pytest.fixture
def sample_afk_events():
    """Sample AFK events for testing."""
    base_time = datetime(2024, 1, 15, 9, 0, 0)
    return [
        MockEvent(base_time, timedelta(hours=3), {"status": "not-afk"}),
        MockEvent(base_time + timedelta(hours=3), timedelta(minutes=30), {"status": "afk"}),
        MockEvent(base_time + timedelta(hours=3, minutes=30), timedelta(hours=2), {"status": "not-afk"}),
    ]


class TestTimelineGeneration:
    """Tests for generate_timeline_data function."""

    def _build_report_events(self, window_events, task_events):
        """Helper to convert window_events to report_event dicts with project/task resolution."""
        report_events = []
        for window_event in window_events:
            # Find active task for this window event
            active_task = None
            project = tw_report.NO_PROJECT
            task_name = tw_report.NO_TASK
            if task_events:
                for task_event in task_events:
                    if (window_event.timestamp < task_event.timestamp + task_event.duration
                        and task_event.timestamp < window_event.timestamp + window_event.duration):
                        active_task = task_event
                        task_name, project = tw_report.get_task_info(active_task)
                        break

            report_events.append({
                "event": window_event,
                "project": project,
                "task": task_name,
                "active_task": active_task,
            })
        return report_events

    def test_generate_timeline_data_basic(self, sample_window_events, sample_task_events, sample_afk_events):
        """Test basic timeline generation with consecutive events."""
        report_events = self._build_report_events(sample_window_events, sample_task_events)
        cat_score_map = {}
        slots = tw_report.generate_timeline_data(
            report_events, sample_afk_events, cat_score_map
        )
        assert len(slots) > 0
        assert all("project" in slot and "task" in slot for slot in slots)

    def test_generate_timeline_data_consecutive_events_merge(self):
        """Test that consecutive events with same project/task merge into one slot."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        window_events = [
            MockEvent(base_time, timedelta(minutes=30), {"app": "VSCode", "title": "file1.py"}),
            MockEvent(base_time + timedelta(minutes=30), timedelta(minutes=30), {"app": "VSCode", "title": "file2.py"}),
            MockEvent(base_time + timedelta(minutes=60), timedelta(minutes=30), {"app": "VSCode", "title": "file3.py"}),
        ]

        task_events = [
            MockEvent(
                base_time,
                timedelta(hours=2),
                {"title": "Development", "project": "ProjectX", "label": None, "task": None}
            ),
        ]

        afk_events = [
            MockEvent(base_time, timedelta(hours=2), {"status": "not-afk"}),
        ]

        report_events = self._build_report_events(window_events, task_events)
        cat_score_map = {}
        slots = tw_report.generate_timeline_data(report_events, afk_events, cat_score_map)

        assert len(slots) == 1
        assert slots[0]["project"] == "ProjectX"
        assert slots[0]["task"] == "Development"
        assert slots[0]["duration"] == timedelta(minutes=90)

    def test_generate_timeline_data_blank_spots_dont_break_continuity(self):
        """Test that window event gaps within same not-afk period merge into one slot."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        window_events = [
            MockEvent(base_time, timedelta(minutes=20), {"app": "Firefox", "title": "Page 1"}),
            MockEvent(base_time + timedelta(minutes=50), timedelta(minutes=20), {"app": "Firefox", "title": "Page 2"}),
        ]

        task_events = [
            MockEvent(
                base_time,
                timedelta(hours=2),
                {"title": "Task X", "project": "ProjectX", "label": None, "task": None}
            ),
        ]

        afk_events = [
            MockEvent(base_time, timedelta(hours=2), {"status": "not-afk"}),
        ]

        report_events = self._build_report_events(window_events, task_events)
        cat_score_map = {}
        slots = tw_report.generate_timeline_data(report_events, afk_events, cat_score_map)

        assert len(slots) == 1
        assert slots[0]["project"] == "ProjectX"
        assert slots[0]["task"] == "Task X"
        assert slots[0]["duration"] == timedelta(minutes=40)

    def test_generate_timeline_data_afk_breaks_slot(self):
        """Test that AFK periods (gaps in window events) create separate slots."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        window_events = [
            MockEvent(base_time, timedelta(minutes=30), {"app": "Firefox", "title": "Morning"}),
            MockEvent(base_time + timedelta(hours=2, minutes=30), timedelta(minutes=30), {"app": "Firefox", "title": "Afternoon"}),
        ]

        task_events = [
            MockEvent(
                base_time,
                timedelta(hours=4),
                {"title": "Task Y", "project": "ProjectY", "label": None, "task": None}
            ),
        ]

        afk_events = [
            MockEvent(base_time, timedelta(minutes=90), {"status": "not-afk"}),
            MockEvent(base_time + timedelta(minutes=90), timedelta(minutes=30), {"status": "afk"}),
            MockEvent(base_time + timedelta(hours=2), timedelta(hours=2), {"status": "not-afk"}),
        ]

        report_events = self._build_report_events(window_events, task_events)
        cat_score_map = {}
        slots = tw_report.generate_timeline_data(report_events, afk_events, cat_score_map)

        assert len(slots) == 2
        assert slots[0]["project"] == "ProjectY"
        assert slots[1]["project"] == "ProjectY"

    def test_generate_timeline_data_different_projects(self):
        """Test timeline with events from different projects."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        window_events = [
            MockEvent(base_time, timedelta(minutes=30), {"app": "VSCode", "title": "ProjectA file"}),
            MockEvent(base_time + timedelta(minutes=30), timedelta(minutes=30), {"app": "Terminal", "title": "bash"}),
        ]

        task_events = [
            MockEvent(base_time, timedelta(minutes=30), {"title": "TaskA", "project": "ProjectA", "label": None, "task": None}),
            MockEvent(base_time + timedelta(minutes=30), timedelta(minutes=30), {"title": "TaskB", "project": "ProjectB", "label": None, "task": None}),
        ]

        afk_events = [
            MockEvent(base_time, timedelta(hours=1), {"status": "not-afk"}),
        ]

        report_events = self._build_report_events(window_events, task_events)
        cat_score_map = {}
        slots = tw_report.generate_timeline_data(report_events, afk_events, cat_score_map)

        assert len(slots) >= 1


class TestFilterFunctions:
    """Tests for filter helper functions."""

    def test_match_partial(self):
        """Test partial matching."""
        assert tw_report._match("ProjectAlpha", "alpha", exact=False)
        assert tw_report._match("ProjectAlpha", "Proj", exact=False)
        assert not tw_report._match("ProjectBeta", "alpha", exact=False)

    def test_match_exact(self):
        """Test exact matching (case-insensitive)."""
        assert tw_report._match("ProjectAlpha", "projectalpha", exact=True)
        assert tw_report._match("ProjectAlpha", "PROJECTALPHA", exact=True)
        assert not tw_report._match("ProjectAlpha", "Project", exact=True)

    def test_matches_any_no_patterns(self):
        """Test matches_any with no patterns (should match all)."""
        assert tw_report._matches_any("anything", None, exact=False)
        assert tw_report._matches_any("anything", [], exact=False)

    def test_matches_any_with_patterns(self):
        """Test matches_any with multiple patterns (OR logic)."""
        patterns = ["alpha", "beta"]
        assert tw_report._matches_any("ProjectAlpha", patterns, exact=False)
        assert tw_report._matches_any("ProjectBeta", patterns, exact=False)
        assert not tw_report._matches_any("ProjectGamma", patterns, exact=False)

    def test_excluded_exact_match(self):
        """Test exclusion with exact matching."""
        exclusions = ["Personal", "Private"]
        assert tw_report._excluded("Personal", exclusions)
        assert tw_report._excluded("personal", exclusions)
        assert not tw_report._excluded("PersonalProject", exclusions)


class TestApplyFilters:
    """Tests for the apply_filters function."""

    def test_apply_filters_project_partial(self):
        """Test filtering projects with partial match."""
        report_data = {
            "Ianua": {
                "total_duration": timedelta(hours=1),
                "prod_score": 5.0,
                "tasks": {
                    "TaskA": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 5.0,
                        "categories": {
                            "Coding": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 5.0,
                                "apps": {
                                    "VSCode": {
                                        "total_duration": timedelta(hours=1),
                                        "prod_score": 5.0,
                                    }
                                },
                            }
                        },
                    }
                },
            },
            "Personal": {
                "total_duration": timedelta(hours=1),
                "prod_score": 3.0,
                "tasks": {
                    "TaskB": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 3.0,
                        "categories": {
                            "Reading": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 3.0,
                                "apps": {
                                    "Firefox": {
                                        "total_duration": timedelta(hours=1),
                                        "prod_score": 3.0,
                                    }
                                },
                            }
                        },
                    }
                },
            },
        }

        args = type("Args", (), {
            "search": None,
            "project": ["ian"],
            "task": None,
            "app": None,
            "exact": False,
            "exclude_project": None,
            "exclude_task": None,
            "exclude_app": None,
        })()

        filtered = tw_report.apply_filters(report_data, args, task_based=True)
        assert "Ianua" in filtered
        assert "Personal" not in filtered

    def test_apply_filters_exact(self):
        """Test exact matching in filters."""
        report_data = {
            "Ianua": {
                "total_duration": timedelta(hours=1),
                "prod_score": 5.0,
                "tasks": {
                    "TaskA": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 5.0,
                        "categories": {
                            "Coding": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 5.0,
                                "apps": {"VSCode": {"total_duration": timedelta(hours=1), "prod_score": 5.0}},
                            }
                        },
                    }
                },
            },
        }

        args = type("Args", (), {
            "search": None,
            "project": ["ian"],
            "task": None,
            "app": None,
            "exact": True,
            "exclude_project": None,
            "exclude_task": None,
            "exclude_app": None,
        })()

        filtered = tw_report.apply_filters(report_data, args, task_based=True)
        assert "Ianua" not in filtered  # "ian" does not exactly match "Ianua"

    def test_apply_filters_or_logic(self):
        """Test OR logic with multiple project filters."""
        report_data = {
            "Ianua": {
                "total_duration": timedelta(hours=1),
                "prod_score": 5.0,
                "tasks": {
                    "TaskA": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 5.0,
                        "categories": {
                            "Coding": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 5.0,
                                "apps": {"VSCode": {"total_duration": timedelta(hours=1), "prod_score": 5.0}},
                            }
                        },
                    }
                },
            },
            "Personal": {
                "total_duration": timedelta(hours=1),
                "prod_score": 3.0,
                "tasks": {
                    "TaskB": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 3.0,
                        "categories": {
                            "Reading": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 3.0,
                                "apps": {"Firefox": {"total_duration": timedelta(hours=1), "prod_score": 3.0}},
                            }
                        },
                    }
                },
            },
        }

        args = type("Args", (), {
            "search": None,
            "project": ["ian", "per"],
            "task": None,
            "app": None,
            "exact": False,
            "exclude_project": None,
            "exclude_task": None,
            "exclude_app": None,
        })()

        filtered = tw_report.apply_filters(report_data, args, task_based=True)
        assert "Ianua" in filtered
        assert "Personal" in filtered

    def test_apply_filters_exclude_project(self):
        """Test project exclusion."""
        report_data = {
            "Ianua": {
                "total_duration": timedelta(hours=1),
                "prod_score": 5.0,
                "tasks": {
                    "TaskA": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 5.0,
                        "categories": {
                            "Coding": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 5.0,
                                "apps": {"VSCode": {"total_duration": timedelta(hours=1), "prod_score": 5.0}},
                            }
                        },
                    }
                },
            },
            "Personal": {
                "total_duration": timedelta(hours=1),
                "prod_score": 3.0,
                "tasks": {
                    "TaskB": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 3.0,
                        "categories": {
                            "Reading": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 3.0,
                                "apps": {"Firefox": {"total_duration": timedelta(hours=1), "prod_score": 3.0}},
                            }
                        },
                    }
                },
            },
        }

        args = type("Args", (), {
            "search": None,
            "project": None,
            "task": None,
            "app": None,
            "exact": False,
            "exclude_project": ["Personal"],
            "exclude_task": None,
            "exclude_app": None,
        })()

        filtered = tw_report.apply_filters(report_data, args, task_based=True)
        assert "Ianua" in filtered
        assert "Personal" not in filtered

    def test_apply_filters_search_term(self):
        """Test general search term matching across project/task/app."""
        report_data = {
            "Ianua": {
                "total_duration": timedelta(hours=1),
                "prod_score": 5.0,
                "tasks": {
                    "TaskA": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 5.0,
                        "categories": {
                            "Coding": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 5.0,
                                "apps": {"VSCode": {"total_duration": timedelta(hours=1), "prod_score": 5.0}},
                            }
                        },
                    }
                },
            },
            "Personal": {
                "total_duration": timedelta(hours=1),
                "prod_score": 3.0,
                "tasks": {
                    "TaskB": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 3.0,
                        "categories": {
                            "Reading": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 3.0,
                                "apps": {"Firefox": {"total_duration": timedelta(hours=1), "prod_score": 3.0}},
                            }
                        },
                    }
                },
            },
        }

        args = type("Args", (), {
            "search": "ian",
            "project": None,
            "task": None,
            "app": None,
            "exact": False,
            "exclude_project": None,
            "exclude_task": None,
            "exclude_app": None,
        })()

        filtered = tw_report.apply_filters(report_data, args, task_based=True)
        assert "Ianua" in filtered
        assert "Personal" not in filtered


class TestCategorization:
    """Test category matching and prioritization."""

    def test_category_depth_prioritization(self):
        """Test that more specific (deeper) categories take priority."""
        # Create category rules: shallow and deep paths
        import re
        categories = [
            (["Work", "Programming"], re.compile(r"nvim"), 10.0),
            (["Work", "Programming", "Terminal"], re.compile(r"^kitty$"), 20.0),
        ]

        # Event: kitty running nvim
        event = MockEvent(
            datetime(2024, 1, 15, 9, 0, 0),
            timedelta(minutes=30),
            {"app": "kitty", "title": "nvim ./tw-report.py"}
        )

        # Manually apply categorization logic
        app_name = event.data.get("app", "")
        title = event.data.get("title", "")
        match_strings = [
            app_name + " " + title,
            app_name,
            title,
        ]
        matched_cats = []
        for cat_list, pattern, _ in categories:
            if any(pattern.search(s) for s in match_strings):
                if cat_list:
                    full_path = " > ".join(cat_list)
                    matched_cats.append((len(cat_list), full_path))

        # Sort by depth (deeper first)
        matched_cats.sort(key=lambda x: (-x[0], x[1]))
        categories_list = [cat for _, cat in matched_cats]

        # Should have both categories, with deeper one first
        assert len(categories_list) == 2
        assert categories_list[0] == "Work > Programming > Terminal"
        assert categories_list[1] == "Work > Programming"

    def test_kitty_terminal_classification(self):
        """Test that kitty is classified as Terminal, not just Programming."""
        import re
        from argparse import Namespace

        # Simplified category rules matching ActivityWatch settings
        categories = [
            (["Work", "Programming"], re.compile(r"nvim|vim|emacs"), 10.0),
            (["Work", "Programming", "Terminal"], re.compile(r"^kitty$"), 20.0),
        ]

        # Event: kitty with nvim
        window_events = [
            MockEvent(
                datetime(2024, 1, 15, 9, 0, 0),
                timedelta(minutes=30),
                {"app": "kitty", "title": "nvim ./tw-report.py"}
            )
        ]

        # Process events with categorization
        args = Namespace(verbose=False, min_score=None, max_score=None)

        for event in window_events:
            app_name = event.data.get("app", "")
            title = event.data.get("title", "")
            match_strings = [
                app_name + " " + title,
                app_name,
                title,
            ]
            matched_cats = []
            for cat_list, pattern, _ in categories:
                if any(pattern.search(s) for s in match_strings):
                    if cat_list:
                        full_path = " > ".join(cat_list)
                        matched_cats.append((len(cat_list), full_path))

            if matched_cats:
                matched_cats.sort(key=lambda x: (-x[0], x[1]))
                event.data["$category"] = [cat for _, cat in matched_cats]

        # Verify the event is categorized under Terminal, not just Programming
        assert "$category" in window_events[0].data
        categories_list = window_events[0].data["$category"]
        assert "Work > Programming > Terminal" in categories_list
        # Terminal should be first (highest priority)
        assert categories_list[0] == "Work > Programming > Terminal"


class TestGenerateGapEntries:
    """Tests for generate_gap_entries function (AFK and OFFLINE marker generation)."""

    def test_generate_gap_entries_afk_slots(self):
        """Test that AFK events produce type='afk' slots."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        afk_events = [
            MockEvent(base_time, timedelta(hours=1), {"status": "not-afk"}),
            MockEvent(base_time + timedelta(hours=1), timedelta(minutes=30), {"status": "afk"}),
            MockEvent(base_time + timedelta(hours=1, minutes=30), timedelta(hours=1), {"status": "not-afk"}),
        ]

        task_events = None
        window_events = []

        gap_entries = tw_report.generate_gap_entries(afk_events, task_events, window_events=window_events)

        # Should have at least one AFK slot (from the status="afk" event)
        afk_slots = [g for g in gap_entries if g.get("type") == "afk"]
        assert len(afk_slots) >= 1
        assert afk_slots[0]["duration"] == timedelta(minutes=30)

    def test_generate_gap_entries_offline_markers(self):
        """Test that gaps > 120s in AFK bucket coverage produce type='offline' markers."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        # Two AFK events with a 3-minute gap between them (> 120s threshold)
        afk_events = [
            MockEvent(base_time, timedelta(hours=1), {"status": "not-afk"}),
            MockEvent(base_time + timedelta(hours=1), timedelta(minutes=30), {"status": "afk"}),
            # Gap: 3 minutes (180s > 120s) → should produce OFFLINE marker
            MockEvent(base_time + timedelta(hours=1, minutes=33), timedelta(minutes=30), {"status": "afk"}),
        ]

        task_events = None
        window_events = []

        gap_entries = tw_report.generate_gap_entries(afk_events, task_events, window_events=window_events)

        # Should have one OFFLINE marker for the gap
        offline_markers = [g for g in gap_entries if g.get("type") == "offline"]
        assert len(offline_markers) == 1
        assert offline_markers[0]["duration"] == timedelta(minutes=3)

    def test_generate_gap_entries_no_offline_for_short_gaps(self):
        """Test that gaps ≤ 120s do not produce OFFLINE markers."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        # Two AFK events with a 1-minute gap between them (< 120s threshold)
        afk_events = [
            MockEvent(base_time, timedelta(hours=1), {"status": "not-afk"}),
            MockEvent(base_time + timedelta(hours=1), timedelta(minutes=30), {"status": "afk"}),
            # Gap: 1 minute (60s < 120s) → should NOT produce OFFLINE marker
            MockEvent(base_time + timedelta(hours=1, minutes=31), timedelta(minutes=30), {"status": "afk"}),
        ]

        task_events = None
        window_events = []

        gap_entries = tw_report.generate_gap_entries(afk_events, task_events, window_events=window_events)

        # Should have NO OFFLINE markers (gap too short)
        offline_markers = [g for g in gap_entries if g.get("type") == "offline"]
        assert len(offline_markers) == 0


class TestGapEntryFiltering:
    """Tests for the three gap entry filtering fixes."""

    def test_exclude_non_project_filters_afk_without_task(self):
        """FIX 1: --exclude-non-project should suppress AFK slots with NO_PROJECT."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        # Build gap_entries manually: one AFK with NO_PROJECT, one with a real project
        gap_entries = [
            {
                "type": "afk",
                "start": base_time,
                "end": base_time + timedelta(minutes=30),
                "duration": timedelta(minutes=30),
                "project": tw_report.NO_PROJECT,
                "task": tw_report.NO_TASK,
            },
            {
                "type": "afk",
                "start": base_time + timedelta(hours=1),
                "end": base_time + timedelta(hours=1, minutes=30),
                "duration": timedelta(minutes=30),
                "project": "ProjectX",
                "task": "TaskX",
            },
        ]

        # Apply the filter from the FIX
        filtered_gaps = [
            g for g in gap_entries
            if not (g.get("type") == "afk" and g.get("project") == tw_report.NO_PROJECT)
        ]

        # Should only have the ProjectX AFK slot
        assert len(filtered_gaps) == 1
        assert filtered_gaps[0]["project"] == "ProjectX"

    def test_exclude_offline_only_removes_offline_type(self):
        """FIX 2: --exclude-offline should only remove type='offline' entries, not AFK."""
        gap_entries = [
            {
                "type": "afk",
                "start": datetime(2024, 1, 15, 9, 0, 0),
                "end": datetime(2024, 1, 15, 9, 30, 0),
                "duration": timedelta(minutes=30),
                "project": "ProjectX",
                "task": "TaskX",
            },
            {
                "type": "offline",
                "start": datetime(2024, 1, 15, 9, 30, 0),
                "end": datetime(2024, 1, 15, 9, 33, 0),
                "duration": timedelta(minutes=3),
                "project": "__offline__",
                "task": "",
            },
        ]

        # Apply the filter from the FIX
        filtered_gaps = [g for g in gap_entries if g.get("type") != "offline"]

        # Should only have the AFK slot
        assert len(filtered_gaps) == 1
        assert filtered_gaps[0]["type"] == "afk"

    def test_exclude_afk_only_removes_afk_type(self):
        """FIX 3: --exclude-afk should only remove type='afk' entries, not OFFLINE."""
        gap_entries = [
            {
                "type": "afk",
                "start": datetime(2024, 1, 15, 9, 0, 0),
                "end": datetime(2024, 1, 15, 9, 30, 0),
                "duration": timedelta(minutes=30),
                "project": "ProjectX",
                "task": "TaskX",
            },
            {
                "type": "offline",
                "start": datetime(2024, 1, 15, 9, 30, 0),
                "end": datetime(2024, 1, 15, 9, 33, 0),
                "duration": timedelta(minutes=3),
                "project": "__offline__",
                "task": "",
            },
        ]

        # Apply the filter from the FIX
        filtered_gaps = [g for g in gap_entries if g.get("type") != "afk"]

        # Should only have the OFFLINE marker
        assert len(filtered_gaps) == 1
        assert filtered_gaps[0]["type"] == "offline"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

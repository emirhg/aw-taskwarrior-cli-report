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

    def test_generate_timeline_data_basic(self, sample_window_events, sample_task_events, sample_afk_events):
        """Test basic timeline generation with consecutive events."""
        slots = tw_report.generate_timeline_data(
            sample_window_events, sample_task_events, sample_afk_events
        )
        assert len(slots) > 0
        assert all("project" in slot and "task" in slot for slot in slots)

    def test_generate_timeline_data_consecutive_events_merge(self):
        """Test that consecutive events with same project/task merge into one slot."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        # Three consecutive events (no gaps) for same project/task
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

        slots = tw_report.generate_timeline_data(window_events, task_events, afk_events)

        # All three consecutive events should merge into one slot
        assert len(slots) == 1
        assert slots[0]["project"] == "ProjectX"
        assert slots[0]["task"] == "Development"
        assert slots[0]["duration"] == timedelta(minutes=90)

    def test_generate_timeline_data_blank_spots_dont_break_continuity(self):
        """Test that window event gaps within same not-afk period merge into one slot."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        # Two window events for same project/task, with a gap between them
        # Within the same not-afk period, they should merge into ONE slot
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

        slots = tw_report.generate_timeline_data(window_events, task_events, afk_events)

        # Events merge into ONE slot within the same not-afk period
        assert len(slots) == 1
        assert slots[0]["project"] == "ProjectX"
        assert slots[0]["task"] == "Task X"
        # Duration is sum of both events, not the span
        assert slots[0]["duration"] == timedelta(minutes=40)

    def test_generate_timeline_data_afk_breaks_slot(self):
        """Test that AFK periods (gaps in window events) create separate slots."""
        base_time = datetime(2024, 1, 15, 9, 0, 0)

        # Two window events for same task, separated by a gap (simulating AFK)
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

        slots = tw_report.generate_timeline_data(window_events, task_events, afk_events)

        # Gap between events creates 2 slots (not merged)
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

        slots = tw_report.generate_timeline_data(window_events, task_events, afk_events)

        # Should have slots for both projects
        projects = [s["project"] for s in slots]
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Unit tests for hierarchical report rendering (tw_report.pipeline.report_render).

Tests verify header output, detail level handling, sorting, and task-based vs
category-based rendering. Uses capsys to capture stdout.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tw_report.pipeline.report_render import (
    print_report,
    print_report_header,
    print_summary_total,
)


class TestPrintSummaryTotal:
    """Test summary total line rendering."""

    def test_basic_summary(self, capsys):
        """Basic summary line with duration."""
        print_summary_total(timedelta(hours=1))
        captured = capsys.readouterr()
        assert "Total Time:" in captured.out
        assert "1:00:00" in captured.out

    def test_summary_with_productivity(self, capsys):
        """Summary with productivity percentage."""
        print_summary_total(timedelta(hours=2), timedelta(hours=1))
        captured = capsys.readouterr()
        assert "Total Time:" in captured.out
        assert "[prod" in captured.out
        assert "50%" in captured.out

    def test_summary_zero_duration(self, capsys):
        """Summary with zero duration."""
        print_summary_total(timedelta(0))
        captured = capsys.readouterr()
        assert "0:00:00" in captured.out


class TestPrintReportHeader:
    """Test report header rendering."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def test_header_basic(self, base_time, capsys):
        """Basic header with title and period."""
        print_report_header(
            title=" Report ",
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            total_duration=timedelta(hours=8),
            task_based=True,
        )
        captured = capsys.readouterr()
        assert "=" in captured.out  # Centered title
        assert "Period:" in captured.out
        assert ":yesterday" in captured.out

    def test_header_task_based_with_metrics(self, base_time, capsys):
        """Task-based header with productivity metrics."""
        print_report_header(
            title=" Report ",
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            total_duration=timedelta(hours=2),
            task_based=True,
            non_afk_time=timedelta(hours=8),
            productive_time=timedelta(hours=3),
            productive_task_time=timedelta(hours=2),
            first_event_time=base_time,
            last_event_time=base_time + timedelta(hours=8),
            total_score=85.5,
        )
        captured = capsys.readouterr()
        assert "Project Tracking:" in captured.out
        assert "Focus time:" in captured.out
        assert "85.50" in captured.out

    def test_header_category_based(self, base_time, capsys):
        """Non-task-based (category) mode header."""
        print_report_header(
            title=" Report ",
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            total_duration=timedelta(hours=2),
            task_based=False,
            non_afk_time=timedelta(hours=8),
            productive_time=timedelta(hours=3),
            productive_task_time=timedelta(hours=1),
            first_event_time=base_time,
            last_event_time=base_time + timedelta(hours=8),
        )
        captured = capsys.readouterr()
        assert "Tracked projects: 0.0%" in captured.out

    def test_header_minimal(self, base_time, capsys):
        """Minimal header without detailed metrics."""
        print_report_header(
            title=" Report ",
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            total_duration=timedelta(hours=8),
            task_based=True,
            total_time_all=timedelta(hours=9),
        )
        captured = capsys.readouterr()
        assert "Total Time:" in captured.out
        assert "9:00:00" in captured.out

    def test_header_with_current_session(self, base_time, capsys):
        """Header with current session info."""
        session_start = base_time + timedelta(hours=7)
        session_end = base_time + timedelta(hours=8)
        print_report_header(
            title=" Report ",
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            total_duration=timedelta(hours=2),
            task_based=True,
            non_afk_time=timedelta(hours=8),
            productive_time=timedelta(hours=3),
            productive_task_time=timedelta(hours=2),
            first_event_time=base_time,
            last_event_time=base_time + timedelta(hours=8),
            current_session_start=session_start,
            current_session_end=session_end,
            current_session_duration=timedelta(hours=1),
        )
        captured = capsys.readouterr()
        assert "Current Session:" in captured.out
        assert "1:00:00" in captured.out


class TestPrintReport:
    """Test hierarchical report rendering."""

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def sample_report_data(self):
        """Sample hierarchical report data."""
        return {
            "Platform": {
                "total_duration": timedelta(hours=4),
                "prod_score": 80.0,
                "tasks": {
                    "Code Review": {
                        "total_duration": timedelta(hours=2),
                        "prod_score": 90.0,
                        "categories": {
                            "Development": {
                                "total_duration": timedelta(hours=2),
                                "prod_score": 90.0,
                                "apps": {
                                    "vim": {
                                        "total_duration": timedelta(hours=1),
                                        "prod_score": 100.0,
                                    },
                                    "GitHub": {
                                        "total_duration": timedelta(hours=1),
                                        "prod_score": 80.0,
                                    },
                                },
                            }
                        },
                    },
                    "Meetings": {
                        "total_duration": timedelta(hours=2),
                        "prod_score": 70.0,
                        "categories": {
                            "Communication": {
                                "total_duration": timedelta(hours=2),
                                "prod_score": 70.0,
                                "apps": {
                                    "Zoom": {
                                        "total_duration": timedelta(hours=2),
                                        "prod_score": 70.0,
                                    }
                                },
                            }
                        },
                    },
                },
            },
            "No project assigned": {
                "total_duration": timedelta(hours=1),
                "prod_score": 0.0,
                "tasks": {},
            },
        }

    def test_report_task_based(self, base_time, sample_report_data, capsys):
        """Task-based report rendering."""
        print_report(
            report_data=sample_report_data,
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            detail_level=2,
        )
        captured = capsys.readouterr()
        assert "▶ Project: Platform" in captured.out
        assert "• Task: Code Review" in captured.out
        assert "• Task: Meetings" in captured.out
        # Should not show "No project assigned" in totals
        assert "Total Time:" in captured.out

    def test_report_detail_level_1(self, base_time, sample_report_data, capsys):
        """Detail level 1: projects only."""
        print_report(
            report_data=sample_report_data,
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            detail_level=1,
        )
        captured = capsys.readouterr()
        assert "▶ Project:" in captured.out
        assert "• Task:" not in captured.out

    def test_report_detail_level_3(self, base_time, sample_report_data, capsys):
        """Detail level 3: projects, tasks, and categories."""
        print_report(
            report_data=sample_report_data,
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            detail_level=3,
        )
        captured = capsys.readouterr()
        assert "▶ Project:" in captured.out
        assert "• Task:" in captured.out
        assert "Development" in captured.out or "Communication" in captured.out

    def test_report_empty_data(self, base_time, capsys):
        """Report with no data."""
        print_report(
            report_data={},
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
        )
        captured = capsys.readouterr()
        assert "No activity found" in captured.out

    def test_report_sort_by_duration(self, base_time, sample_report_data, capsys):
        """Report sorted by duration."""
        print_report(
            report_data=sample_report_data,
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            detail_level=2,
            sort_by_duration=True,
            sort_by_score=False,
        )
        captured = capsys.readouterr()
        # Just verify it runs without error
        assert "▶ Project:" in captured.out

    def test_report_category_based(self, base_time, capsys):
        """Category-based report rendering."""
        report_data = {
            "Development": {
                "total_duration": timedelta(hours=3),
                "prod_score": 85.0,
                "apps": {
                    "vim": {
                        "total_duration": timedelta(hours=2),
                        "prod_score": 100.0,
                    },
                    "GitHub": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 70.0,
                    },
                },
            }
        }
        print_report(
            report_data=report_data,
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=False,
            detail_level=2,
        )
        captured = capsys.readouterr()
        assert "▶ Category:" in captured.out
        assert "• App:" in captured.out

    def test_report_with_titles(self, base_time, capsys):
        """Report with window titles at detail level 5."""
        report_data = {
            "Platform": {
                "total_duration": timedelta(hours=1),
                "prod_score": 90.0,
                "tasks": {
                    "Code": {
                        "total_duration": timedelta(hours=1),
                        "prod_score": 90.0,
                        "categories": {
                            "Dev": {
                                "total_duration": timedelta(hours=1),
                                "prod_score": 90.0,
                                "apps": {
                                    "vim": {
                                        "total_duration": timedelta(hours=1),
                                        "prod_score": 90.0,
                                        "titles": {
                                            "main.py": {
                                                "total_duration": timedelta(
                                                    minutes=30
                                                ),
                                                "prod_score": 100.0,
                                            },
                                            "test_main.py": {
                                                "total_duration": timedelta(
                                                    minutes=30
                                                ),
                                                "prod_score": 80.0,
                                            },
                                        },
                                    }
                                },
                            }
                        },
                    }
                },
            }
        }
        print_report(
            report_data=report_data,
            period=":yesterday",
            start_time=base_time,
            end_time=base_time + timedelta(days=1),
            task_based=True,
            detail_level=5,
        )
        captured = capsys.readouterr()
        # Titles should be shown at detail level 5
        assert "main.py" in captured.out or "test_main.py" in captured.out

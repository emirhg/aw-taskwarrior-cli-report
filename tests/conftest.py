"""
Pytest configuration and fixtures for tw-report tests.

This module provides test data fixtures that reproduce real-world scenarios
including the documented bugs from DIAGNOSIS.md and IMPLEMENTATION_GUIDE.md.
"""

import pytest
from datetime import datetime, timedelta, timezone
from aw_core.models import Event
from typing import Dict, List, Optional


# ============================================================================
# TIMEZONE & HELPERS
# ============================================================================

UTC = timezone.utc


def make_datetime(year: int, month: int, day: int,
                  hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Helper to create UTC datetime objects."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def make_event(timestamp: datetime, duration: timedelta, data: Dict) -> Event:
    """Helper to create ActivityWatch Event objects."""
    return Event(timestamp=timestamp, duration=duration, data=data)


# ============================================================================
# BASIC FIXTURES (Used by multiple test classes)
# ============================================================================

@pytest.fixture
def tz():
    """UTC timezone for test consistency."""
    return UTC


@pytest.fixture
def sample_date():
    """Standard date for fixture data: 2026-06-27."""
    return make_datetime(2026, 6, 27)


# ============================================================================
# WINDOW EVENT FIXTURES
# ============================================================================

@pytest.fixture
def window_event_vscode(sample_date):
    """Window event: VSCode, 1 hour of coding."""
    return make_event(
        timestamp=sample_date.replace(hour=14),
        duration=timedelta(hours=1),
        data={
            "app": "VSCode",
            "title": "tw-report.py - GitHub",
            "class": "VSCode"
        }
    )


@pytest.fixture
def window_event_firefox(sample_date):
    """Window event: Firefox, 30 minutes of browsing."""
    return make_event(
        timestamp=sample_date.replace(hour=15),
        duration=timedelta(minutes=30),
        data={
            "app": "firefox",
            "title": "Gmail - Inbox",
            "class": "firefox"
        }
    )


@pytest.fixture
def window_events_for_consolidation(sample_date):
    """Multiple window events for testing consolidation."""
    return [
        # Event 1: VSCode, 1 hour
        make_event(
            timestamp=sample_date.replace(hour=10),
            duration=timedelta(hours=1),
            data={"app": "VSCode", "title": "Code", "class": "VSCode"}
        ),
        # Event 2: Firefox, 30 min (same task)
        make_event(
            timestamp=sample_date.replace(hour=11),
            duration=timedelta(minutes=30),
            data={"app": "firefox", "title": "Gmail", "class": "firefox"}
        ),
        # Event 3: VSCode, 1 hour (after break, same task)
        make_event(
            timestamp=sample_date.replace(hour=13),
            duration=timedelta(hours=1),
            data={"app": "VSCode", "title": "Code", "class": "VSCode"}
        ),
    ]


# ============================================================================
# AFK EVENT FIXTURES
# ============================================================================

@pytest.fixture
def afk_event_not_afk(sample_date):
    """AFK event: status='not-afk' (user active), 1 hour."""
    return make_event(
        timestamp=sample_date.replace(hour=14),
        duration=timedelta(hours=1),
        data={"status": "not-afk"}
    )


@pytest.fixture
def afk_event_afk(sample_date):
    """AFK event: status='afk' (user away), 10 minutes."""
    return make_event(
        timestamp=sample_date.replace(hour=15, minute=15),
        duration=timedelta(minutes=10),
        data={"status": "afk"}
    )


@pytest.fixture
def afk_events_with_gaps(sample_date):
    """Multiple AFK events with gaps (testing offline detection)."""
    return [
        # Not-AFK: 08:00-09:00
        make_event(
            timestamp=sample_date.replace(hour=8),
            duration=timedelta(hours=1),
            data={"status": "not-afk"}
        ),
        # Not-AFK: 09:30-10:30 (30 min gap creates potential OFFLINE marker)
        make_event(
            timestamp=sample_date.replace(hour=9, minute=30),
            duration=timedelta(hours=1),
            data={"status": "not-afk"}
        ),
        # AFK: 10:45-10:55 (small gap)
        make_event(
            timestamp=sample_date.replace(hour=10, minute=45),
            duration=timedelta(minutes=10),
            data={"status": "afk"}
        ),
    ]


# ============================================================================
# TASK EVENT FIXTURES
# ============================================================================

@pytest.fixture
def task_event_climb(sample_date):
    """TaskWarrior event: Climb > Task1."""
    return make_event(
        timestamp=sample_date.replace(hour=14),
        duration=timedelta(hours=1),
        data={
            "project": "Climb",
            "task": "Task1",
            "label": "Task1",
            "tags": ["work", "climbing"],
            "title": "Climb > Task1"
        }
    )


@pytest.fixture
def task_event_offline(sample_date):
    """TaskWarrior event: Task with 'offline' tag."""
    return make_event(
        timestamp=sample_date.replace(hour=11, minute=35, second=44),
        duration=timedelta(hours=4, minutes=22, seconds=30),
        data={
            "project": "Ecosistema",
            "task": "Tratamiento de residuos",
            "label": "Residuos",
            "tags": ["offline", "ecosistema"],  # KEY: offline tag
            "title": "Ecosistema > Tratamiento de residuos"
        }
    )


@pytest.fixture
def task_events_with_offline(sample_date):
    """Multiple task events including OFFLINE-tagged tasks."""
    return [
        # Regular task
        make_event(
            timestamp=sample_date.replace(hour=10),
            duration=timedelta(hours=1),
            data={
                "project": "Climb",
                "task": "Task1",
                "tags": ["work"],
                "title": "Climb > Task1"
            }
        ),
        # OFFLINE task 1
        make_event(
            timestamp=sample_date.replace(hour=11, minute=35),
            duration=timedelta(minutes=30),
            data={
                "project": "Ecosistema",
                "task": "Residuos",
                "tags": ["offline"],  # OFFLINE tag
                "title": "Ecosistema > Residuos"
            }
        ),
        # OFFLINE task 2 (same task, later occurrence)
        make_event(
            timestamp=sample_date.replace(hour=15, minute=58),
            duration=timedelta(minutes=5),
            data={
                "project": "Ecosistema",
                "task": "Residuos",
                "tags": ["offline"],  # OFFLINE tag
                "title": "Ecosistema > Residuos"
            }
        ),
    ]


# ============================================================================
# ISSUE #1: OFFLINE TASK DURATION
# ============================================================================

@pytest.fixture
def issue_1_offline_task_data():
    """
    Fixture: Issue #1 - OFFLINE task showing 0:00:00 duration

    Scenario: Ecosistema.Tratamiento de residuos.Orgánicos with 4:22:30
    But when using --exclude-non-project, it shows 0:00:00

    Root cause: Synthetic slots not filtered consistently
    """
    return {
        "project": "Ecosistema",
        "task": "Tratamiento de residuos",
        "duration": timedelta(hours=4, minutes=22, seconds=30),
        "tags": ["offline"],
        "expected_in_report": False,  # When --exclude-non-project is set
        "issue": "Synthetic OFFLINE slots not filtered like regular slots"
    }


@pytest.fixture
def issue_1_no_project_entry():
    """Entry with NO_PROJECT that should be filtered by --exclude-non-project."""
    return {
        "type": "offline_task",
        "project": "NO_PROJECT",  # Key: untracked
        "task": "Some task",
        "duration": 15750,  # 4:22:30
    }


# ============================================================================
# ISSUE #2: MULTIPLE OFF ENTRIES
# ============================================================================

@pytest.fixture
def issue_2_consolidation_data(sample_date):
    """
    Fixture: Issue #2 - Multiple OFF entries instead of consolidated

    Scenario: Single task (Ecosistema.Recámara.Lavar cortinas) 12:09-20:37
    Contains 5 OFFLINE gaps within it

    CURRENT: Shows task with 5 separate OFF entries (BUG)
    EXPECTED: Shows single consolidated slot with accumulated OFFLINE duration
    """
    return {
        "task": {
            "type": "regular",
            "start": sample_date.replace(hour=12, minute=9),
            "end": sample_date.replace(hour=20, minute=37),
            "duration": timedelta(hours=8, minutes=27, seconds=30),
            "project": "Ecosistema",
            "task": "Lavar cortinas",
        },
        "offline_gaps": [
            timedelta(minutes=5, seconds=11),
            timedelta(minutes=4, seconds=10),
            timedelta(minutes=5, seconds=38),
            timedelta(minutes=7, seconds=42),
            timedelta(minutes=4, seconds=52),
        ],
        "issue": "Consolidation breaks at every OFFLINE gap instead of merging same task"
    }


# ============================================================================
# ISSUE #3: INCOMPLETE --exclude-non-project FILTER
# ============================================================================

@pytest.fixture
def issue_3_filter_data():
    """
    Fixture: Issue #3 - --exclude-non-project doesn't filter all entry types

    CURRENT: Filters AFK slots but not OFFLINE gaps or synthetic OFFLINE slots
    EXPECTED: All entry types filtered consistently
    """
    return {
        "regular_no_project": {
            "type": "regular",
            "project": "NO_PROJECT",
            "task": "NO_TASK",
            "should_filter": True,
        },
        "afk_no_project": {
            "type": "afk",
            "project": "NO_PROJECT",
            "task": "NO_TASK",
            "should_filter": True,
        },
        "offline_no_project": {
            "type": "offline",
            "project": "NO_PROJECT",
            "task": "",  # Empty, not explicitly NO_TASK
            "should_filter": True,  # BUG: Currently NOT filtered
        },
        "offline_task_no_project": {
            "type": "offline_task",
            "project": "NO_PROJECT",
            "task": "Some task",
            "should_filter": True,  # BUG: Currently NOT filtered (Issue #1)
        },
        "issue": "--exclude-non-project not applied uniformly to all entry types"
    }


# ============================================================================
# FILTER CONFIGURATION FIXTURES
# ============================================================================

@pytest.fixture
def filter_no_options():
    """Filter with no restrictions (default behavior)."""
    return {
        "project_patterns": None,
        "task_patterns": None,
        "app_patterns": None,
        "exclude_projects": None,
        "exclude_tasks": None,
        "exclude_apps": None,
        "exclude_non_project": False,
        "exact_match": False,
    }


@pytest.fixture
def filter_exclude_non_project():
    """Filter with --exclude-non-project flag."""
    return {
        "exclude_non_project": True,
    }


@pytest.fixture
def filter_exclude_non_project_and_project_pattern():
    """Filter: --exclude-non-project + --project Climb."""
    return {
        "project_patterns": ["Climb"],
        "exclude_non_project": True,
    }


# ============================================================================
# CONSOLIDATED REPORT FIXTURES (For integration tests)
# ============================================================================

@pytest.fixture
def consolidate_report_args():
    """Standard arguments for consolidated report testing."""
    return {
        "timesheet": True,
        "consolidate": True,
        "detail_level": 1,
        "exclude_non_project": False,
    }


@pytest.fixture
def consolidate_report_args_with_filter():
    """Consolidated report with --exclude-non-project."""
    return {
        "timesheet": True,
        "consolidate": True,
        "detail_level": 1,
        "exclude_non_project": True,
    }


# ============================================================================
# CATEGORY FIXTURES
# ============================================================================

@pytest.fixture
def sample_categories():
    """Sample category rules for testing."""
    return [
        {
            "name": ["Work", "Programming", "Terminal"],
            "data": {"score": 100},
            "rule": {"type": "regex", "regex": ".*terminal.*|.*bash.*", "ignore_case": True}
        },
        {
            "name": ["Work", "Email"],
            "data": {"score": 50},
            "rule": {"type": "regex", "regex": ".*gmail.*|.*outlook.*", "ignore_case": True}
        },
        {
            "name": ["Media", "Video"],
            "data": {"score": -50},
            "rule": {"type": "regex", "regex": ".*youtube.*|.*netflix.*", "ignore_case": True}
        },
    ]


# ============================================================================
# MARKERS FOR KNOWN ISSUES (xfail tests)
# ============================================================================

def issue_1_marker():
    """Pytest marker for Issue #1 tests (OFFLINE task duration 0:00:00)."""
    return pytest.mark.xfail(reason="Issue #1: OFFLINE task duration becomes 0:00:00 with --exclude-non-project")


def issue_2_marker():
    """Pytest marker for Issue #2 tests (Multiple OFF entries)."""
    return pytest.mark.xfail(reason="Issue #2: Multiple OFF entries instead of consolidated")


def issue_3_marker():
    """Pytest marker for Issue #3 tests (Incomplete filter)."""
    return pytest.mark.xfail(reason="Issue #3: --exclude-non-project doesn't filter OFFLINE gaps or synthetic slots")

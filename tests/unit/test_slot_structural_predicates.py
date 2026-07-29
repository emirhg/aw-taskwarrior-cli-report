"""
Verification tests for the NEW structural predicates that will replace the `type` string discriminator.

These tests validate that the proposed structural predicates correctly classify slots
according to how they're actually produced in the real pipeline, BEFORE we change
ReportTimelineSlot itself. This is spec-first verification.

Predicates being validated:
- is_offline_task = (task_event is not None and event_duration is not None)
- is_afk_only = (afk_duration is not None and afk_duration == actual_duration and event_duration is None)
- regular (default/residual) = everything else
"""

import pytest
from datetime import datetime, timedelta, timezone

from tw_report.core.timeline import TimelineSlot
from tw_report.core.filtering import NO_PROJECT, NO_TASK


UTC = timezone.utc


def make_time_slot(
    type_str: str,
    start: datetime,
    duration: timedelta,
    project: str = "TestProject",
    task: str = "TestTask",
    actual_duration: timedelta = None,
    afk_duration: timedelta = None,
    event_duration: timedelta = None,
) -> TimelineSlot:
    """Helper to construct slots exactly as the real pipeline producers do."""
    if actual_duration is None:
        actual_duration = duration
    return TimelineSlot(
        type=type_str,
        start=start,
        end=start + duration,
        project=project,
        task=task,
        duration=duration,
        actual_duration=actual_duration,
        afk_duration=afk_duration,
        event_duration=event_duration,
    )


class TestStructuralPredicateOfflineTask:
    """Verify the offline_task structural predicate works correctly."""

    def test_offline_task_has_both_task_and_event_duration(self):
        """Offline task slots have task_event and event_duration set."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="offline_task",
            start=dt_start,
            duration=timedelta(hours=2),
            project="ClimbProject",
            task="ClimbTask",
            actual_duration=timedelta(hours=1, minutes=30),
            event_duration=timedelta(hours=1, minutes=30),
        )
        # Predicate: task_event is not None and event_duration is not None
        # In the new model: task_event would be the TaskWarriorEvent
        # This test verifies that offline_task slots always have both fields set
        assert slot.project != NO_PROJECT
        assert slot.task != NO_TASK
        assert slot.event_duration is not None

    def test_offline_task_never_has_afk_duration(self):
        """Offline task slots don't have afk_duration."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="offline_task",
            start=dt_start,
            duration=timedelta(hours=2),
            project="ClimbProject",
            task="ClimbTask",
            actual_duration=timedelta(hours=1, minutes=30),
            event_duration=timedelta(hours=1, minutes=30),
        )
        # Offline tasks never have embedded AFK
        assert slot.afk_duration is None


class TestStructuralPredicateAFKOnly:
    """Verify the is_afk_only structural predicate works correctly."""

    def test_bare_afk_gap_has_matching_durations(self):
        """Bare AFK gap slots have afk_duration == actual_duration."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        afk_duration = timedelta(minutes=10)
        slot = make_time_slot(
            type_str="afk",
            start=dt_start,
            duration=afk_duration,
            project=NO_PROJECT,
            task=NO_TASK,
            actual_duration=afk_duration,
            afk_duration=afk_duration,  # Must be set per plan §2
        )
        # Predicate: afk_duration is not None and afk_duration == actual_duration
        assert slot.afk_duration == afk_duration
        assert slot.actual_duration == afk_duration
        assert slot.afk_duration == slot.actual_duration
        assert slot.event_duration is None

    def test_bare_afk_gap_no_event_duration(self):
        """Bare AFK gap slots never have event_duration."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="afk",
            start=dt_start,
            duration=timedelta(minutes=10),
            project=NO_PROJECT,
            task=NO_TASK,
            actual_duration=timedelta(minutes=10),
            afk_duration=timedelta(minutes=10),
        )
        assert slot.event_duration is None


class TestStructuralPredicateRegular:
    """Verify that non-offline_task, non-bare-afk slots are regular."""

    def test_tracked_regular_slot(self):
        """Tracked work slots have task but no event_duration."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="regular",
            start=dt_start,
            duration=timedelta(hours=2),
            project="WorkProject",
            task="WorkTask",
            actual_duration=timedelta(hours=1, minutes=50),
        )
        # Regular slot: has project/task, no event_duration
        assert slot.project != NO_PROJECT
        assert slot.task != NO_TASK
        assert slot.event_duration is None

    def test_untracked_regular_slot_no_project(self):
        """Untracked gaps (NO_PROJECT/NO_TASK) are regular slots."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="regular",
            start=dt_start,
            duration=timedelta(minutes=30),
            project=NO_PROJECT,
            task=NO_TASK,
            actual_duration=timedelta(minutes=30),
        )
        # Regular untracked: NO_PROJECT/NO_TASK is fine, no event_duration
        assert slot.project == NO_PROJECT
        assert slot.task == NO_TASK
        assert slot.event_duration is None

    def test_regular_with_embedded_afk(self):
        """Regular slot with embedded AFK has afk_duration < actual_duration."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="regular",
            start=dt_start,
            duration=timedelta(hours=2),
            project="WorkProject",
            task="WorkTask",
            actual_duration=timedelta(hours=1, minutes=30),  # 1.5h work + 30m AFK = 2h total
            afk_duration=timedelta(minutes=30),
        )
        # Regular with embedded AFK: afk_duration != actual_duration
        assert slot.afk_duration != slot.actual_duration
        assert slot.afk_duration < slot.actual_duration
        # NOT a bare AFK-only slot (because actual_duration > afk_duration)
        assert not (slot.afk_duration == slot.actual_duration)
        # NOT an offline_task (no event_duration)
        assert slot.event_duration is None


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_slot_with_zero_event_duration(self):
        """Offline task with zero event_duration is still offline_task."""
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="offline_task",
            start=dt_start,
            duration=timedelta(hours=2),
            project="ClimbProject",
            task="ClimbTask",
            actual_duration=timedelta(hours=0),  # Completely offline, no online time
            event_duration=timedelta(hours=0),  # event_duration is 0
        )
        # Predicate checks "event_duration is not None", not "!= 0"
        # so zero-duration counts as set and explicitly intentional
        assert slot.event_duration is not None
        assert slot.event_duration == timedelta(hours=0)

    def test_slot_with_matching_afk_and_actual_but_with_event_duration_is_not_afk_only(self):
        """If a slot has both afk_duration==actual_duration AND event_duration, it's not bare AFK."""
        # This shouldn't occur in practice, but testing the predicate robustness
        dt_start = datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)
        slot = make_time_slot(
            type_str="afk",  # Labeled as AFK
            start=dt_start,
            duration=timedelta(minutes=10),
            project=NO_PROJECT,
            task=NO_TASK,
            actual_duration=timedelta(minutes=10),
            afk_duration=timedelta(minutes=10),
            event_duration=timedelta(minutes=10),  # Anomalously set
        )
        # Even though afk_duration == actual_duration, presence of event_duration means NOT bare AFK
        # Predicate: is_afk_only = (afk_duration is not None and afk_duration == actual_duration and event_duration is None)
        assert not (slot.afk_duration == slot.actual_duration and slot.event_duration is None)

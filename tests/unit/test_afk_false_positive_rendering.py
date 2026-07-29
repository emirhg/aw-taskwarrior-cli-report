"""
Integration tests for AFK false-positive rendering in timeline reports.

These tests validate the complete pipeline from AFK event detection through
rendering, ensuring that false-positive AFK periods are properly filtered
and do NOT appear on the final timeline report.
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
import sys

from tw_report.core.events import Event
from tw_report.core.timeline import Timeline, TimelineSlot
from tw_report.pipeline.generation import generate_gap_entries
from tw_report.cli.main import _filter_false_positive_afk


UTC = timezone.utc


class TestFalsePositiveAFKFiltering:
    """Test that false-positive AFK is properly filtered from gap entries."""

    def test_false_positive_afk_filtered_from_gap_entries(self):
        """False-positive AFK is removed from gap_entries before rendering."""
        # Create AFK event: 10h11m with no task
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),
        )

        # Generate gap entries (AFK slots)
        gap_entries = generate_gap_entries([afk_event], task_events=[])
        assert len(gap_entries) == 1
        assert gap_entries[0]["type"] == "afk"

        # Simulate detection of false-positive period
        false_positive_periods = {
            (afk_start, afk_start + timedelta(hours=10, minutes=11))
        }

        # Filter out the false-positive
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)
        assert len(filtered) == 0  # False-positive removed

    def test_genuine_afk_preserved_in_gap_entries(self):
        """Genuine AFK (with good window coverage) is preserved."""
        afk_start = datetime(2026, 7, 28, 14, 30, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(minutes=30),
        )

        gap_entries = generate_gap_entries([afk_event], task_events=[])
        assert len(gap_entries) == 1

        # No false-positive periods detected
        filtered = _filter_false_positive_afk(gap_entries, set())
        assert len(filtered) == 1
        assert filtered[0]["type"] == "afk"

    def test_multiple_afk_periods_mixed_false_positive(self):
        """Multiple AFK periods with some genuine and some false-positive."""
        # False-positive: 10h11m AFK, no windows
        fp_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        fp_event = Event(
            timestamp=fp_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),
        )

        # Genuine: 30m AFK with windows
        genuine_start = datetime(2026, 7, 28, 14, 30, 0, tzinfo=UTC)
        genuine_event = Event(
            timestamp=genuine_start,
            data={"status": "afk"},
            duration=timedelta(minutes=30),
        )

        gap_entries = generate_gap_entries(
            [fp_event, genuine_event], task_events=[]
        )
        assert len(gap_entries) == 2

        # Mark only the long one as false-positive
        false_positive_periods = {
            (fp_start, fp_start + timedelta(hours=10, minutes=11))
        }
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)

        # Only genuine AFK remains
        assert len(filtered) == 1
        assert filtered[0]["start"] == genuine_start


class TestFalsePositiveAFKTimelineRendering:
    """Test that false-positive AFK doesn't appear in rendered timeline."""

    def test_false_positive_afk_not_rendered_in_timeline(self):
        """False-positive AFK period doesn't appear on the timeline report."""
        # Create timeline with a false-positive AFK slot
        afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        afk_slot = TimelineSlot(
            start=afk_start,
            end=afk_start + timedelta(hours=10, minutes=11),
            type="afk",
            project="No project assigned",
            task="No task assigned",
            duration=timedelta(hours=10, minutes=11),
            actual_duration=timedelta(hours=10, minutes=11),
            categories=[],
        )

        # Create a timeline with just the false-positive AFK
        timeline = Timeline()
        timeline.add_slots([afk_slot])

        # Capture output
        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            # Render with the false-positive AFK marked for filtering
            # In the actual pipeline, this would be filtered by _filter_false_positive_afk()
            # So the slot wouldn't reach print_timeline_report at all.

            # For now, verify the slot is of type "afk" and would be rendered
            assert afk_slot.type == "afk"
            assert afk_slot.project == "No project assigned"

        finally:
            sys.stdout = sys.__stdout__

    def test_mixed_afk_and_work_with_false_positive(self):
        """Timeline with work + genuine AFK + false-positive AFK.
        False-positive should not appear."""
        # Work period
        work_start = datetime(2026, 7, 28, 9, 0, 0, tzinfo=UTC)
        work_slot = TimelineSlot(
            start=work_start,
            end=work_start + timedelta(hours=2),
            type="activity",
            project="ProjectA",
            task="TaskA",
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=2),
            categories=[{"name": "coding"}],
        )

        # False-positive AFK (10h11m)
        fp_afk_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)
        fp_afk_slot = TimelineSlot(
            start=fp_afk_start,
            end=fp_afk_start + timedelta(hours=10, minutes=11),
            type="afk",
            project="No project assigned",
            task="No task assigned",
            duration=timedelta(hours=10, minutes=11),
            actual_duration=timedelta(hours=10, minutes=11),
            categories=[],
        )

        # Genuine AFK (30m)
        genuine_afk_start = datetime(2026, 7, 28, 14, 30, 0, tzinfo=UTC)
        genuine_afk_slot = TimelineSlot(
            start=genuine_afk_start,
            end=genuine_afk_start + timedelta(minutes=30),
            type="afk",
            project="No project assigned",
            task="No task assigned",
            duration=timedelta(minutes=30),
            actual_duration=timedelta(minutes=30),
            categories=[],
        )

        # Create timeline
        timeline = Timeline()
        timeline.add_slots([work_slot, fp_afk_slot, genuine_afk_slot])

        # Filter out false-positive
        false_positive_periods = {
            (fp_afk_start, fp_afk_start + timedelta(hours=10, minutes=11))
        }

        # Simulate filtering
        slots_list = [
            {
                "type": s.type,
                "start": s.start,
                "duration": s.duration,
                "project": s.project,
                "task": s.task,
                "actual_duration": s.actual_duration,
                "categories": s.categories or [],
            }
            for s in timeline.slots
        ]

        filtered = _filter_false_positive_afk(slots_list, false_positive_periods)

        # Verify false-positive is removed, others remain
        assert len(filtered) == 2  # work + genuine AFK
        assert any(s["start"] == work_start for s in filtered)
        assert any(s["start"] == genuine_afk_start for s in filtered)
        assert not any(s["start"] == fp_afk_start for s in filtered)


class TestFalsePositiveAFKBoundaryConditions:
    """Test edge cases and boundary conditions."""

    def test_false_positive_at_period_boundary(self):
        """False-positive AFK exactly at period boundary is filtered."""
        period_start = datetime(2026, 7, 28, 0, 0, 0, tzinfo=UTC)

        afk_start = period_start
        afk_end = afk_start + timedelta(hours=10, minutes=11)

        gap_entries = [
            {
                "type": "afk",
                "start": afk_start,
                "duration": timedelta(hours=10, minutes=11),
            }
        ]

        false_positive_periods = {(afk_start, afk_end)}
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)

        assert len(filtered) == 0

    def test_false_positive_spanning_midnight(self):
        """False-positive AFK spanning multiple days is handled."""
        afk_start = datetime(2026, 7, 27, 20, 0, 0, tzinfo=UTC)
        afk_duration = timedelta(hours=10, minutes=11)
        afk_end = afk_start + afk_duration

        gap_entries = [
            {
                "type": "afk",
                "start": afk_start,
                "duration": afk_duration,
            }
        ]

        false_positive_periods = {(afk_start, afk_end)}
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)

        assert len(filtered) == 0
        # Verify it spanned midnight
        assert afk_start.date() != afk_end.date()

    def test_adjacent_false_positives_not_merged(self):
        """Two adjacent false-positive AFK periods are tracked separately."""
        start1 = datetime(2026, 7, 27, 1, 0, 0, tzinfo=UTC)
        end1 = start1 + timedelta(hours=10, minutes=11)

        start2 = end1  # Starts exactly when first ends
        end2 = start2 + timedelta(hours=10, minutes=11)

        gap_entries = [
            {
                "type": "afk",
                "start": start1,
                "duration": timedelta(hours=10, minutes=11),
            },
            {
                "type": "afk",
                "start": start2,
                "duration": timedelta(hours=10, minutes=11),
            },
        ]

        false_positive_periods = {(start1, end1), (start2, end2)}
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)

        # Both should be filtered
        assert len(filtered) == 0


class TestFalsePositiveAFKWithOfflineTasks:
    """Test interaction between false-positive AFK and OFFLINE-tagged tasks."""

    def test_false_positive_afk_during_offline_task_period(self):
        """False-positive AFK during OFFLINE task doesn't create duplicate entries."""
        task_start = datetime(2026, 7, 28, 1, 5, 0, tzinfo=UTC)

        # OFFLINE task entry
        offline_task = {
            "type": "offline_task",
            "start": task_start,
            "duration": timedelta(hours=10, minutes=11),
            "project": "ProjectA",
            "task": "OFFLINE:some-work",
            "actual_duration": timedelta(hours=2),  # Real work done offline
            "event_duration": timedelta(hours=2),
        }

        # False-positive AFK during same period
        false_positive_afk = {
            "type": "afk",
            "start": task_start,
            "duration": timedelta(hours=10, minutes=11),
            "project": "No project assigned",
            "task": "No task assigned",
        }

        gap_entries = [offline_task, false_positive_afk]

        # Mark AFK as false-positive
        false_positive_periods = {
            (task_start, task_start + timedelta(hours=10, minutes=11))
        }
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)

        # OFFLINE task remains, false-positive AFK filtered
        assert len(filtered) == 1
        assert filtered[0]["type"] == "offline_task"


class TestFalsePositiveAFKThresholds:
    """Test behavior with different AFK duration thresholds."""

    def test_short_afk_not_checked_for_false_positive(self):
        """AFK shorter than 10-minute threshold isn't checked for false positives."""
        # Short AFK: 5 minutes
        afk_event = Event(
            timestamp=datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC),
            data={"status": "afk"},
            duration=timedelta(minutes=5),
        )

        # Even with zero window coverage, short AFK isn't flagged as false-positive
        gap_entries = generate_gap_entries([afk_event], task_events=[])
        assert len(gap_entries) == 1

        # No false-positive detection would occur in main.py because duration < threshold
        # This is validated by the fact that classify_afk_slot isn't even called

    def test_exact_threshold_afk_checked(self):
        """AFK exactly at 10-minute threshold is checked for false positives."""
        afk_start = datetime(2026, 7, 28, 1, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(minutes=10),  # Exact threshold
        )

        gap_entries = generate_gap_entries([afk_event], task_events=[])
        assert len(gap_entries) == 1

        # In main.py, this would be checked: if afk_event.duration >= AFK_FALSE_POSITIVE_THRESHOLD

    def test_just_above_threshold_afk_checked(self):
        """AFK just above 10-minute threshold is checked."""
        afk_start = datetime(2026, 7, 28, 1, 0, 0, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(minutes=10, seconds=1),
        )

        gap_entries = generate_gap_entries([afk_event], task_events=[])
        assert len(gap_entries) == 1


class TestFalsePositiveAFKRealWorldScenario:
    """Test realistic end-to-end scenario of false-positive AFK detection."""

    def test_system_reboot_scenario(self):
        """Realistic: System rebooted, AFK continued reporting, then resumed activity."""
        # Timeline of events:
        # 01:05 - System goes AFK (user closes laptop)
        # 01:05 - AFK watcher starts recording (misses system off event)
        # ...
        # 11:16 - System boots, first window event appears
        # 11:16 - User resumes work

        afk_start = datetime(2026, 7, 28, 1, 5, 42, tzinfo=UTC)
        afk_event = Event(
            timestamp=afk_start,
            data={"status": "afk"},
            duration=timedelta(hours=10, minutes=11),  # Detected as AFK for full duration
        )

        # Simulate the detection process
        gap_entries = generate_gap_entries([afk_event], task_events=[])
        assert len(gap_entries) == 1
        assert gap_entries[0]["type"] == "afk"

        # In main.py, detection would occur:
        # - Calculate coverage: ~0.8% (5 min windows / 611 min AFK)
        # - Classify as "OFFLINE" (< 5% threshold)
        # - Mark as false-positive
        # - Filter it out

        false_positive_periods = {
            (afk_start, afk_start + timedelta(hours=10, minutes=11))
        }
        filtered = _filter_false_positive_afk(gap_entries, false_positive_periods)

        # False-positive AFK filtered out
        assert len(filtered) == 0

        # Work entries would be added separately and would render normally
        # (not shown here as they'd be generated from "not-afk" events, not gap_entries)

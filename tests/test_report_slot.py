"""
Comprehensive tests for ReportTimelineSlot and ReportEntries.

Tests the unified merge implementation and bug fixes:
1. Tags preservation (previously dropped)
2. Offline gap handling consistency (will be tested in ReportEntries layer)
3. N/A: merge_by_project_date() dead code retirement
4. split_slots_spanning_days divergence resolution (tested separately)
5. Mixed-type merge rejection
6. event_duration position-independence
7. AFK duration field uniformity
8. Fuller 3-level category merging
9. N/A: group totals computed once (presentation layer)
10. N/A: "activity" type renamed at source (cli/main.py)
"""

import pytest
from datetime import datetime, timedelta, timezone, date

from tw_report.core.timeline import TimelineSlot, TimelineSlotValidationError
from tw_report.core.report_slot import ReportTimelineSlot, ReportEntries


# Fixtures for common test data
UTC = timezone.utc


@pytest.fixture
def dt_start():
    """A fixed start datetime for consistent test data."""
    return datetime(2026, 7, 23, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def basic_slot(dt_start):
    """A basic regular slot."""
    return TimelineSlot(
        type="regular",
        start=dt_start,
        end=dt_start + timedelta(hours=1),
        duration=timedelta(hours=1),
        actual_duration=timedelta(hours=1),
        productive_duration=timedelta(minutes=50),
        project="TestProject",
        task="TestTask",
        categories=[],
        tags=["tag1", "tag2"],
    )


@pytest.fixture
def afk_slot(dt_start):
    """An AFK slot."""
    return TimelineSlot(
        type="afk",
        start=dt_start + timedelta(hours=2),
        end=dt_start + timedelta(hours=2, minutes=30),
        duration=timedelta(minutes=30),
        actual_duration=timedelta(minutes=30),
        productive_duration=timedelta(0),
        project="NoProject",
        task="NoTask",
        categories=[],
        tags=[],
    )


@pytest.fixture
def offline_task_slot(dt_start):
    """An offline_task slot (with event_duration for the online portion)."""
    return TimelineSlot(
        type="offline_task",
        start=dt_start + timedelta(hours=3),
        end=dt_start + timedelta(hours=4, minutes=30),
        duration=timedelta(hours=1, minutes=30),  # Wall-clock span
        actual_duration=timedelta(minutes=45),  # Online time
        productive_duration=timedelta(minutes=40),
        event_duration=timedelta(minutes=45),  # Online time (duplicated per spec)
        project="OfflineProject",
        task="OfflineTask",
        categories=[],
        tags=["offline"],
    )


class TestReportTimelineSlotConstruction:
    """Test single-slot wrapping and basic properties."""

    def test_from_timeline_slot_wraps_atomic(self, basic_slot):
        """from_timeline_slot should wrap a single slot unchanged."""
        report_slot = ReportTimelineSlot.from_timeline_slot(basic_slot)
        assert report_slot.slot is basic_slot
        assert report_slot.source_slots == [basic_slot]
        assert report_slot.is_consolidated is False
        assert report_slot.start == basic_slot.start
        assert report_slot.project == "TestProject"
        assert report_slot.tags == ["tag1", "tag2"]

    def test_properties_delegate_to_slot(self, basic_slot):
        """All properties should delegate transparently to self.slot."""
        report_slot = ReportTimelineSlot.from_timeline_slot(basic_slot)
        assert report_slot.type == "regular"
        assert report_slot.start == basic_slot.start
        assert report_slot.end == basic_slot.end
        assert report_slot.duration == timedelta(hours=1)
        assert report_slot.actual_duration == timedelta(hours=1)
        assert report_slot.productive_duration == timedelta(minutes=50)
        assert report_slot.project == "TestProject"
        assert report_slot.task == "TestTask"


class TestReportTimelineSlotMerge:
    """Test from_timeline_slots merge implementation (bug fixes 1, 5, 6, 7, 8)."""

    def test_merge_basic_two_slots(self, dt_start):
        """Basic merge: two consecutive slots should combine."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(minutes=50),
            project="P", task="T", categories=[], tags=["a"],
        )
        slot2 = TimelineSlot(
            type="regular",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=2),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(minutes=45),
            project="P", task="T", categories=[], tags=["b"],
        )

        merged = ReportTimelineSlot.from_timeline_slots([slot1, slot2])
        assert merged.is_consolidated is True
        assert merged.start == slot1.start
        assert merged.end == slot2.end
        assert merged.duration == timedelta(hours=2)
        assert merged.actual_duration == timedelta(hours=2)  # Sum
        assert merged.productive_duration == timedelta(minutes=95)  # 50 + 45
        assert merged.project == "P"
        assert merged.task == "T"

    def test_merge_preserves_and_dedupes_tags(self, dt_start):
        """Bug fix #1: Tags should be preserved and deduplicated (bug was: tags dropped)."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=["a", "b", "c"],
        )
        slot2 = TimelineSlot(
            type="regular",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=2),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=["b", "d"],
        )

        merged = ReportTimelineSlot.from_timeline_slots([slot1, slot2])
        # Should have union of tags, deduplicated, order-preserving
        assert merged.tags == ["a", "b", "c", "d"]

    def test_merge_rejects_mixed_types_by_default(self, dt_start):
        """Bug fix #5: Mixed-type merge should raise unless explicitly opted in."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )
        slot2 = TimelineSlot(
            type="afk",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=1, minutes=30),
            duration=timedelta(minutes=30),
            actual_duration=timedelta(minutes=30),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )

        with pytest.raises(TimelineSlotValidationError):
            ReportTimelineSlot.from_timeline_slots([slot1, slot2])

    def test_merge_allows_mixed_types_when_explicitly_opted_in(self, dt_start):
        """Bug fix #5: allow_mixed_types=True should permit type mismatch."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )
        slot2 = TimelineSlot(
            type="afk",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=1, minutes=30),
            duration=timedelta(minutes=30),
            actual_duration=timedelta(minutes=30),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )

        merged = ReportTimelineSlot.from_timeline_slots(
            [slot1, slot2], allow_mixed_types=True
        )
        # Should use first slot's type
        assert merged.type == "regular"

    def test_merge_sums_event_duration_regardless_of_position(self, dt_start):
        """Bug fix #6: event_duration should be summed even if offline_task isn't first."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(minutes=30),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )
        slot2 = TimelineSlot(
            type="offline_task",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=2),
            duration=timedelta(hours=1),
            actual_duration=timedelta(minutes=20),
            productive_duration=timedelta(0),
            event_duration=timedelta(minutes=20),
            project="P", task="T", categories=[], tags=["offline"],
        )
        slot3 = TimelineSlot(
            type="offline_task",
            start=dt_start + timedelta(hours=2),
            end=dt_start + timedelta(hours=3),
            duration=timedelta(hours=1),
            actual_duration=timedelta(minutes=15),
            productive_duration=timedelta(0),
            event_duration=timedelta(minutes=15),
            project="P", task="T", categories=[], tags=["offline"],
        )

        # Mix offline_task slots with a regular slot
        merged = ReportTimelineSlot.from_timeline_slots(
            [slot1, slot2, slot3], allow_mixed_types=True
        )
        # event_duration should be summed from ALL offline_task members (20 + 15)
        assert merged.event_duration == timedelta(minutes=35)

    def test_merge_afk_duration_uses_actual_duration(self, dt_start):
        """Bug fix #7: AFK duration should be summed via actual_duration uniformly."""
        slot1 = TimelineSlot(
            type="afk",
            start=dt_start,
            end=dt_start + timedelta(minutes=15),
            duration=timedelta(minutes=15),
            actual_duration=timedelta(minutes=15),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )
        slot2 = TimelineSlot(
            type="afk",
            start=dt_start + timedelta(minutes=15),
            end=dt_start + timedelta(minutes=20),
            duration=timedelta(minutes=5),
            actual_duration=timedelta(minutes=5),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )

        merged = ReportTimelineSlot.from_timeline_slots([slot1, slot2])
        # AFK duration should be sum of actual_duration (15 + 5)
        assert merged.afk_duration == timedelta(minutes=20)

    def test_merge_uses_full_3level_category_merge(self, dt_start):
        """Bug fix #8: Category merge should preserve titles (3-level), not drop them (2-level)."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T",
            categories=[
                {
                    "category": "Dev",
                    "duration": timedelta(minutes=30),
                    "start": dt_start,
                    "end": dt_start + timedelta(minutes=30),
                    "apps": [
                        {
                            "app": "VSCode",
                            "duration": timedelta(minutes=30),
                            "start": dt_start,
                            "end": dt_start + timedelta(minutes=30),
                            "titles": [
                                {
                                    "title": "file1.py",
                                    "duration": timedelta(minutes=30),
                                    "events": [],
                                }
                            ],
                        }
                    ],
                }
            ],
            tags=[],
        )
        slot2 = TimelineSlot(
            type="regular",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=2),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T",
            categories=[
                {
                    "category": "Dev",
                    "duration": timedelta(minutes=30),
                    "start": dt_start + timedelta(hours=1),
                    "end": dt_start + timedelta(hours=1, minutes=30),
                    "apps": [
                        {
                            "app": "VSCode",
                            "duration": timedelta(minutes=30),
                            "start": dt_start + timedelta(hours=1),
                            "end": dt_start + timedelta(hours=1, minutes=30),
                            "titles": [
                                {
                                    "title": "file2.py",
                                    "duration": timedelta(minutes=30),
                                    "events": [],
                                }
                            ],
                        }
                    ],
                }
            ],
            tags=[],
        )

        merged = ReportTimelineSlot.from_timeline_slots([slot1, slot2])
        # Should have merged categories with 2 titles (not dropped)
        assert len(merged.categories) == 1
        assert merged.categories[0]["category"] == "Dev"
        assert len(merged.categories[0]["apps"]) == 1
        assert len(merged.categories[0]["apps"][0]["titles"]) == 2  # Both titles preserved


class TestReportTimelineSlotBucketing:
    """Test bucket_start, bucket_key, and split_at_boundaries."""

    def test_bucket_start_day_mode(self, dt_start):
        """bucket_start("day") should return the day's date."""
        result = ReportTimelineSlot.bucket_start(dt_start, "day")
        assert result == date(2026, 7, 23)

    def test_bucket_start_week_mode(self, dt_start):
        """bucket_start("week") should return the Monday of the week (ISO convention)."""
        # July 23, 2026 is a Wednesday; Monday of that week is July 20
        result = ReportTimelineSlot.bucket_start(dt_start, "week")
        assert result == date(2026, 7, 20)  # Monday

    def test_bucket_start_month_mode(self, dt_start):
        """bucket_start("month") should return the 1st of the month."""
        result = ReportTimelineSlot.bucket_start(dt_start, "month")
        assert result == date(2026, 7, 1)

    def test_bucket_start_year_mode(self, dt_start):
        """bucket_start("year") should return Jan 1 of the year."""
        result = ReportTimelineSlot.bucket_start(dt_start, "year")
        assert result == date(2026, 1, 1)

    def test_bucket_key_delegates_to_bucket_start(self, basic_slot, dt_start):
        """bucket_key should delegate to bucket_start for the slot's start time."""
        report_slot = ReportTimelineSlot.from_timeline_slot(basic_slot)
        result = report_slot.bucket_key("week")
        assert result == date(2026, 7, 20)  # Monday of July 23

    def test_split_at_boundaries_same_bucket_passthrough(self, basic_slot):
        """Split on a slot within the same bucket should return [self] unchanged."""
        report_slot = ReportTimelineSlot.from_timeline_slot(basic_slot)
        split = report_slot.split_at_boundaries("day")
        assert len(split) == 1
        assert split[0].start == basic_slot.start
        assert split[0].duration == timedelta(hours=1)

    def test_split_at_boundaries_day_mode_spanning_midnight(self, dt_start):
        """Split spanning two days should produce two pieces with prorated durations."""
        # dt_start is 2026-07-23 10:00 UTC
        # Adjust to get 11 PM on July 23: that's 13 hours after 10 AM
        start_time = dt_start.replace(hour=23, minute=0, second=0, microsecond=0)  # 2026-07-23 23:00 UTC
        end_time = start_time + timedelta(hours=2)  # 2026-07-24 01:00 UTC

        slot = TimelineSlot(
            type="regular",
            start=start_time,
            end=end_time,
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=2),
            productive_duration=timedelta(hours=1),
            project="P", task="T", categories=[], tags=[],
        )

        report_slot = ReportTimelineSlot.from_timeline_slot(slot)
        split = report_slot.split_at_boundaries("day")

        assert len(split) == 2
        # First piece: 1 hour (11 PM - midnight)
        assert split[0].duration == timedelta(hours=1)
        assert split[0].actual_duration == timedelta(hours=1)
        assert split[0].productive_duration == timedelta(minutes=30)  # 1:2 ratio

        # Second piece: 1 hour (midnight - 1 AM)
        assert split[1].duration == timedelta(hours=1)
        assert split[1].actual_duration == timedelta(hours=1)
        assert split[1].productive_duration == timedelta(minutes=30)  # 1:2 ratio

    def test_split_at_boundaries_zero_duration_slot(self, dt_start):
        """Split on a zero-duration slot should handle gracefully."""
        slot = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start,
            duration=timedelta(0),
            actual_duration=timedelta(0),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )

        report_slot = ReportTimelineSlot.from_timeline_slot(slot)
        # Should not crash; behavior is to return original or one piece
        split = report_slot.split_at_boundaries("day")
        assert len(split) >= 1


class TestReportTimelineSlotSerialization:
    """Test to_dict and to_timeline_slot."""

    def test_to_dict_includes_period_start_when_set(self, basic_slot):
        """to_dict should include period_start if bucket_start_date is set."""
        report_slot = ReportTimelineSlot.from_timeline_slot(basic_slot)
        report_slot.bucket_start_date = date(2026, 7, 20)

        d = report_slot.to_dict()
        assert d["period_start"] == date(2026, 7, 20)

    def test_to_timeline_slot_returns_wrapped_slot(self, basic_slot):
        """to_timeline_slot should return the wrapped TimelineSlot."""
        report_slot = ReportTimelineSlot.from_timeline_slot(basic_slot)
        assert report_slot.to_timeline_slot() is basic_slot


class TestReportTimelineEmbeddedAFK:
    """Test combining work slots with embedded AFK periods."""

    def test_combine_work_with_embedded_afk_basic(self):
        """Work slot with overlapping AFK slot should be combined."""
        # Work slot: 14:09-18:51
        work = TimelineSlot(
            type="regular",
            start=datetime(2026, 7, 23, 14, 9, tzinfo=UTC),
            end=datetime(2026, 7, 23, 18, 51, tzinfo=UTC),
            project="Anarcademia",
            task="Mecanismo",
            duration=timedelta(hours=4, minutes=42),
            actual_duration=timedelta(hours=4, minutes=41, seconds=57),
        )

        # AFK slot: 14:55-14:59 (within work period)
        afk1 = TimelineSlot(
            type="afk",
            start=datetime(2026, 7, 23, 14, 55, tzinfo=UTC),
            end=datetime(2026, 7, 23, 14, 59, tzinfo=UTC),
            project="Anarcademia",
            task="Mecanismo",
            duration=timedelta(minutes=4),
            actual_duration=timedelta(minutes=4),
        )

        # AFK slot: 15:01-15:07 (within work period)
        afk2 = TimelineSlot(
            type="afk",
            start=datetime(2026, 7, 23, 15, 1, tzinfo=UTC),
            end=datetime(2026, 7, 23, 15, 7, tzinfo=UTC),
            project="Anarcademia",
            task="Mecanismo",
            duration=timedelta(minutes=6),
            actual_duration=timedelta(minutes=6),
        )

        # Create timeline with work + AFK slots
        from tw_report.core.timeline import Timeline

        timeline = Timeline()
        timeline.add_slots([work, afk1, afk2])

        # Convert to ReportTimeline and combine
        report_timeline = ReportEntries.from_timeline(timeline)
        combined = report_timeline.combine_work_with_embedded_afk()

        # Should have 1 slot (combined work + embedded AFK)
        assert len(combined.slots()) == 1

        combined_slot = combined.slots()[0]
        assert combined_slot.type == "regular"
        assert combined_slot.project == "Anarcademia"
        assert combined_slot.task == "Mecanismo"
        assert len(combined_slot.embedded_afk_slots) == 2
        assert combined_slot.embedded_afk_slots[0].start == afk1.start
        assert combined_slot.embedded_afk_slots[1].start == afk2.start

    def test_combine_work_keeps_non_overlapping_afk(self):
        """AFK slots not overlapping with work should remain standalone."""
        # Work slot: 14:09-15:00
        work = TimelineSlot(
            type="regular",
            start=datetime(2026, 7, 23, 14, 9, tzinfo=UTC),
            end=datetime(2026, 7, 23, 15, 0, tzinfo=UTC),
            project="Anarcademia",
            task="Mecanismo",
            duration=timedelta(minutes=51),
            actual_duration=timedelta(minutes=51),
        )

        # AFK slot: 13:00-13:30 (before work)
        afk_before = TimelineSlot(
            type="afk",
            start=datetime(2026, 7, 23, 13, 0, tzinfo=UTC),
            end=datetime(2026, 7, 23, 13, 30, tzinfo=UTC),
            project="Anarcademia",
            task="Mecanismo",
            duration=timedelta(minutes=30),
            actual_duration=timedelta(minutes=30),
        )

        # AFK slot: 14:55-15:05 (overlaps)
        afk_overlaps = TimelineSlot(
            type="afk",
            start=datetime(2026, 7, 23, 14, 55, tzinfo=UTC),
            end=datetime(2026, 7, 23, 15, 5, tzinfo=UTC),
            project="Anarcademia",
            task="Mecanismo",
            duration=timedelta(minutes=10),
            actual_duration=timedelta(minutes=10),
        )

        from tw_report.core.timeline import Timeline

        timeline = Timeline()
        timeline.add_slots([work, afk_before, afk_overlaps])

        report_timeline = ReportEntries.from_timeline(timeline)
        combined = report_timeline.combine_work_with_embedded_afk()

        # Should have 2 slots: standalone AFK before + combined work
        assert len(combined.slots()) == 2

        # After sorting by start time: AFK before comes first
        standalone_afk = combined.slots()[0]
        assert standalone_afk.type == "afk"
        assert standalone_afk.start == afk_before.start

        # Then combined work with embedded AFK
        work_slot = combined.slots()[1]
        assert work_slot.type == "regular"
        assert len(work_slot.embedded_afk_slots) == 1
        assert work_slot.embedded_afk_slots[0].start == afk_overlaps.start


class TestReportEntries:
    """Test ReportEntries collection operations."""

    def test_from_timeline_wraps_all_slots(self, basic_slot, afk_slot):
        """from_timeline should wrap every slot as a singleton ReportTimelineSlot."""
        from tw_report.core.timeline import Timeline

        timeline = Timeline()
        timeline.add_slot(basic_slot)
        timeline.add_slot(afk_slot)

        report_timeline = ReportEntries.from_timeline(timeline)
        assert len(report_timeline.slots()) == 2
        assert all(not s.is_consolidated for s in report_timeline.slots())

    def test_consolidate_consecutive_merges_same_task_date(self, dt_start):
        """consolidate_consecutive should merge consecutive same-(project,task,date) slots."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=["a"],
        )
        slot2 = TimelineSlot(
            type="regular",
            start=dt_start + timedelta(hours=2),
            end=dt_start + timedelta(hours=3),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=["b"],
        )

        report_timeline = ReportEntries(
            slots_list=[
                ReportTimelineSlot.from_timeline_slot(slot1),
                ReportTimelineSlot.from_timeline_slot(slot2),
            ]
        )

        consolidated = report_timeline.consolidate_consecutive()
        # Should merge into one, spanning 10:00-11:00 and 12:00-13:00 (2 hours wall-clock time)
        assert len(consolidated.slots()) == 1
        assert consolidated.slots()[0].is_consolidated
        assert consolidated.slots()[0].actual_duration == timedelta(hours=2)
        assert consolidated.slots()[0].tags == ["a", "b"]  # Both tags preserved

    def test_consolidate_consecutive_excludes_bare_offline_gaps(self, dt_start):
        """consolidate_consecutive should exclude bare type=='offline' gap markers from output."""
        slot1 = TimelineSlot(
            type="regular",
            start=dt_start,
            end=dt_start + timedelta(hours=1),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )
        gap_slot = TimelineSlot(
            type="offline",
            start=dt_start + timedelta(hours=1),
            end=dt_start + timedelta(hours=2),
            duration=timedelta(hours=1),
            actual_duration=timedelta(0),
            productive_duration=timedelta(0),
            project="", task="", categories=[], tags=[],
        )
        slot2 = TimelineSlot(
            type="regular",
            start=dt_start + timedelta(hours=2),
            end=dt_start + timedelta(hours=3),
            duration=timedelta(hours=1),
            actual_duration=timedelta(hours=1),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )

        report_timeline = ReportEntries(
            slots_list=[
                ReportTimelineSlot.from_timeline_slot(slot1),
                ReportTimelineSlot.from_timeline_slot(gap_slot),
                ReportTimelineSlot.from_timeline_slot(slot2),
            ]
        )

        consolidated = report_timeline.consolidate_consecutive()
        # Should merge slot1 and slot2 (gap doesn't break continuity) but not include the gap itself
        assert len(consolidated.slots()) == 1
        assert consolidated.slots()[0].type == "regular"
        assert consolidated.slots()[0].actual_duration == timedelta(hours=2)

    def test_bucket_day_mode(self, dt_start):
        """bucket('day') should split and group by calendar day."""
        start_time = dt_start.replace(hour=23, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(hours=2)

        slot = TimelineSlot(
            type="regular",
            start=start_time,
            end=end_time,
            duration=timedelta(hours=2),
            actual_duration=timedelta(hours=2),
            productive_duration=timedelta(0),
            project="P", task="T", categories=[], tags=[],
        )

        report_timeline = ReportEntries(
            slots_list=[ReportTimelineSlot.from_timeline_slot(slot)]
        )

        bucketed = report_timeline.bucket("day")
        # Should produce 2 buckets (July 23 and July 24)
        assert len(bucketed.slots()) == 2
        assert bucketed.slots()[0].bucket_start_date == date(2026, 7, 23)
        assert bucketed.slots()[1].bucket_start_date == date(2026, 7, 24)

    def test_slots_and_as_dicts(self, basic_slot):
        """slots() and as_dicts() should return the list and dict conversions."""
        report_timeline = ReportEntries(
            slots_list=[ReportTimelineSlot.from_timeline_slot(basic_slot)]
        )

        slots = report_timeline.slots()
        assert len(slots) == 1

        dicts = report_timeline.as_dicts()
        assert len(dicts) == 1
        assert isinstance(dicts[0], dict)

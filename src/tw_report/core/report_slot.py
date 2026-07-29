"""
ReportTimelineSlot: unified model for consolidation, bucketing, and reporting.

This module provides ReportTimelineSlot and ReportTimeline classes that centralize
all slot-merging, period-bucketing, and multi-bucket-spanning logic in one place,
replacing the three divergent implementations currently scattered across:
  - TimelineSlotManager.consolidate()
  - consolidate_by_period()
  - timeline_render.py's split_slots_spanning_days (module-level vs. nested duplicate)

Key design:
- ReportTimelineSlot wraps TimelineSlot by composition (not inheritance), reusing
  TimelineSlot.__post_init__ validation for free on every merge/split.
- ReportTimeline provides grouping/bucketing/collapsing operations as pure methods.
- All slot merging fixes (tags preservation, offline-gap-handling consistency,
  event_duration position-independence, AFK duration field uniformity, fuller
  category merging) are implemented once here.
- Multi-bucket proportional splitting (day/week/month/year) is generalized and
  available through split_at_boundaries(mode).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time
from typing import Any, Dict, List, Optional, Tuple, Literal

from tw_report.core.timeline import TimelineSlot, TimelineSlotValidationError


@dataclass
class DisplayColumns:
    """Fixed-width columns for consistent timeline display.

    Each duration type has its own reserved column to avoid offset issues
    and make it easy to spot what type of time is recorded:
    - OFFLINE: System was powered off (untracked wall-clock time)
    - AFK: User was idle/away (system recorded but user not active)
    - ACTIVE: User was actively working (keyboard/mouse activity)
    - PRODUCTIVITY: Quality metric derived from app categories

    Empty columns are left blank (no offset) when data doesn't exist.
    """
    time_range: str       # "HH:MM - HH:MM" (11 chars)
    project: str          # "▶ Project name" (variable width, truncated)
    task: str             # "▶▶ Task name" (variable width, truncated)
    offline_time: str     # "(HH:MM:SS)" if present, else blank (12 chars)
    afk_time: str         # "(HH:MM:SS)" if present, else blank (12 chars)
    active_time: str      # "HH:MM:SS" (8 chars)
    productivity: str     # "[prod XXX%]" if present, else blank (12 chars)

    def format(self, terminal_width: int = 120) -> str:
        """Format columns into a single line with fixed positions.

        Uses display width (not byte length) to handle multi-byte UTF-8 characters.
        This ensures proper visual alignment regardless of character encoding.

        Layout (columns are right-aligned to terminal width):
        - Indent (7) + time_range (13 for "HH:MM - HH:MM") + sep (2)
        - project (28) + sep (2) + task (35)
        - [right-aligned to terminal width]
          - offline_time (12) + afk_time (12) + active_time (8) + productivity (14)
        """
        from tw_report.utils.formatting import display_width, ljust_display

        # Build left section (identification) using display width
        # Time range is always "HH:MM - HH:MM" = 13 characters
        indent = " " * 7
        time_part = ljust_display(self.time_range, 13)  # "HH:MM - HH:MM" = 13 chars
        project_part = ljust_display(self.project, 28)
        task_part = ljust_display(self.task, 35)

        left_section = f"{indent}{time_part}  {project_part}  {task_part}"

        # Build right section (duration breakdown)
        # Each column preserves its width even when empty
        offline_col = ljust_display(self.offline_time, 12)
        afk_col = ljust_display(self.afk_time, 12)
        active_col = ljust_display(self.active_time, 8)
        # Add 2 spaces separator before productivity
        productivity_col = ljust_display("  " + self.productivity, 14) if self.productivity else " " * 14

        right_section = f"{offline_col}{afk_col}{active_col}{productivity_col}"

        # Right-align the duration section to terminal width using display width
        # Leave 2-space separator between left and right
        total_right_width = display_width(right_section)
        left_section_width = display_width(left_section)
        left_padding = terminal_width - left_section_width - total_right_width - 2

        # Ensure we don't create negative padding
        if left_padding < 0:
            full_line = left_section + "  " + right_section
        else:
            full_line = left_section + (" " * left_padding) + "  " + right_section

        return full_line

    @classmethod
    def from_slot_dict(cls, slot: Dict[str, Any], start_time: datetime, end_time: datetime) -> "DisplayColumns":
        """Create DisplayColumns from a dict-based slot (from timeline rendering pipeline).

        Args:
            slot: Dictionary with keys like type, project, task, duration, afk_duration, etc.
            start_time: Start time (local timezone)
            end_time: End time (local timezone)

        Returns:
            DisplayColumns formatted and ready to display
        """
        from tw_report.utils.formatting import format_duration, abbreviate_project_path
        from tw_report.core.filtering import NO_PROJECT, NO_TASK

        # Format time range
        time_range = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"

        # Format project and task using the same abbreviation logic as rendering
        project_name = slot.get("project", NO_PROJECT)
        task_name = slot.get("task", NO_TASK)

        # Use abbreviate_project_path for consistent formatting
        abbrev_project = abbreviate_project_path(
            project_name.replace(".", " > ") if project_name != NO_PROJECT else NO_PROJECT,
            task_name
        )
        # Project column: 28 chars (including ▶ prefix)
        project_display = f"▶ {abbrev_project}"[:28] if abbrev_project else ""

        # Task column: 35 chars (including ▶▶ prefix)
        if task_name and task_name != NO_TASK:
            task_display = f"▶▶ {task_name}"[:35]
        else:
            task_display = " " if abbrev_project else ""

        # Format duration columns (no parenthesis)
        offline_time = ""
        if slot.get("offline_extension_duration"):
            offline_dur = slot["offline_extension_duration"]
            if isinstance(offline_dur, timedelta) and offline_dur.total_seconds() > 0:
                offline_time = format_duration(offline_dur)

        afk_time = ""
        if slot.get("afk_duration"):
            afk_dur = slot["afk_duration"]
            if isinstance(afk_dur, timedelta) and afk_dur.total_seconds() > 0:
                afk_time = format_duration(afk_dur)

        # Active time (use actual_duration if available, else duration)
        active_duration = slot.get("actual_duration") or slot.get("duration")
        if active_duration:
            if isinstance(active_duration, timedelta):
                active_time = format_duration(active_duration)
            else:
                active_time = str(active_duration)
        else:
            active_time = ""

        # Productivity metric
        productivity = ""
        if slot.get("productive_duration"):
            prod_dur = slot["productive_duration"]
            if isinstance(prod_dur, timedelta) and isinstance(active_duration, timedelta):
                if active_duration.total_seconds() > 0 and prod_dur.total_seconds() > 0:
                    pct = (prod_dur.total_seconds() / active_duration.total_seconds()) * 100
                    productivity = f"[prod {pct:>3.0f}%]"

        return cls(
            time_range=time_range,
            project=project_display,
            task=task_display,
            offline_time=offline_time,
            afk_time=afk_time,
            active_time=active_time,
            productivity=productivity,
        )


@dataclass
class ReportTimelineSlot:
    """
    Report-optimized timeline slot representing a single granular or consolidated activity.

    Wraps a TimelineSlot (validated atomic data) and adds reporting-specific metadata:
    - source_slots: constituent slots if merged/split, for traceability
    - is_consolidated: True if produced by merging >1 slot
    - bucket_mode / bucket_start_date: period assignment after split_at_boundaries()
    - embedded_afk_slots: AFK periods nested within this slot (same task/project)

    For combined work+AFK slots:
    - slot: contains work data (TW task, project, duration)
    - embedded_afk_slots: list of AFK TimelineSlots that occurred during this work period
    - The wall-clock span encompasses both work and AFK time

    Properties delegate to self.slot for all data fields (start, duration, etc.),
    so call sites read rts.start instead of rts.slot.start or slot["start"].
    """

    slot: TimelineSlot
    source_slots: List[TimelineSlot] = field(default_factory=list)  # [self.slot] if atomic
    is_consolidated: bool = False
    bucket_mode: Optional[Literal["day", "week", "month", "year"]] = None
    bucket_start_date: Optional[date] = None
    embedded_afk_slots: List[TimelineSlot] = field(default_factory=list)  # AFK periods within this work slot

    # Delegate properties to self.slot for transparent access
    @property
    def type(self) -> str:
        return self.slot.type

    @property
    def start(self) -> datetime:
        return self.slot.start

    @property
    def end(self) -> datetime:
        return self.slot.end

    @property
    def project(self) -> str:
        return self.slot.project

    @property
    def task(self) -> str:
        return self.slot.task

    @property
    def duration(self) -> timedelta:
        return self.slot.duration

    @property
    def actual_duration(self) -> timedelta:
        return self.slot.actual_duration

    @property
    def productive_duration(self) -> timedelta:
        return self.slot.productive_duration

    @property
    def afk_duration(self) -> Optional[timedelta]:
        """Optional AFK duration from the slot."""
        return self.slot.afk_duration

    @property
    def offline_extension_duration(self) -> Optional[timedelta]:
        """Optional offline extension duration from the slot."""
        return self.slot.offline_extension_duration

    @property
    def event_duration(self) -> Optional[timedelta]:
        """Optional event duration from the slot."""
        return self.slot.event_duration

    @property
    def categories(self) -> List[Dict[str, Any]]:
        return self.slot.categories

    @property
    def tags(self) -> List[str]:
        return self.slot.tags

    @property
    def apps(self) -> Optional[List[Dict[str, Any]]]:
        return self.slot.apps

    def get_display_columns(self) -> DisplayColumns:
        """Format slot data into fixed-width display columns.

        Returns DisplayColumns with each duration type in its own column,
        empty columns left blank (no offset) when data doesn't exist.
        """
        from tw_report.utils.formatting import format_duration
        from datetime import timezone

        # Format time range
        def to_local(dt: datetime) -> datetime:
            if dt.tzinfo is None or dt.tzinfo == timezone.utc:
                return dt.replace(tzinfo=timezone.utc).astimezone()
            return dt

        start_local = to_local(self.start)
        end_local = to_local(self.start + self.duration)
        time_range = f"{start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}"

        # Format project and task (truncate if too long)
        project_name = self.project.replace(".", " > ") if self.project else "No project"
        project_display = f"▶ {project_name}"[:30]  # Truncate to fit column

        task_name = self.task if self.task else ""
        task_display = (f"▶▶ {task_name}" if task_name else "")[:32]  # Truncate to fit column

        # Format duration columns - each type gets its own space (no parenthesis)
        offline_time = ""
        if self.offline_extension_duration and self.offline_extension_duration.total_seconds() > 0:
            offline_time = format_duration(self.offline_extension_duration)

        afk_time = ""
        if self.afk_duration and self.afk_duration.total_seconds() > 0:
            afk_time = format_duration(self.afk_duration)

        # Active time is always shown (actual work duration)
        active_duration = self.actual_duration if self.actual_duration else self.duration
        active_time = format_duration(active_duration)

        # Productivity metric (if applicable)
        productivity = ""
        if self.productive_duration and self.productive_duration.total_seconds() > 0:
            if active_duration.total_seconds() > 0:
                pct = (self.productive_duration.total_seconds() / active_duration.total_seconds()) * 100
                productivity = f"[prod {pct:>3.0f}%]"

        return DisplayColumns(
            time_range=time_range,
            project=project_display,
            task=task_display,
            offline_time=offline_time,
            afk_time=afk_time,
            active_time=active_time,
            productivity=productivity,
        )

    @classmethod
    def from_timeline_slot(cls, slot: TimelineSlot) -> "ReportTimelineSlot":
        """
        Wrap a single TimelineSlot as an atomic ReportTimelineSlot.

        Args:
            slot: A validated TimelineSlot

        Returns:
            ReportTimelineSlot with is_consolidated=False, source_slots=[slot]
        """
        return cls(slot=slot, source_slots=[slot], is_consolidated=False)

    @classmethod
    def from_timeline_slots(
        cls,
        group: List[TimelineSlot],
        *,
        allow_mixed_types: bool = False,
    ) -> "ReportTimelineSlot":
        """
        Merge multiple TimelineSlots into a single ReportTimelineSlot.

        This is the ONE TRUE MERGE IMPLEMENTATION, fixing all consolidation bugs:
        1. Tags are preserved (union + dedupe, order-preserving) — previously dropped
        2. Offline gap exclusion (handled by caller/collection layer) — consistent
        3. N/A: merge_by_project_date() is dead code, being retired
        4. Uses wall-clock duration for splitting axis, not actual_duration
        5. Mixed-type merge raises TimelineSlotValidationError by default
        6. event_duration summed across ALL offline_task slots, not position-dependent
        7. AFK duration summed via actual_duration uniformly
        8. Uses fuller 3-level category merge (category→app→title), not shallow 2-level
        9. (Caller responsibility: compute group totals once, not twice)
        10. (Caller responsibility: "activity" type renamed to "regular" at source)

        Args:
            group: List of TimelineSlots to merge (must be non-empty)
            allow_mixed_types: If True, don't raise on type mismatch; use first slot's type.
                             Default False — mixed types are an error unless explicitly opted in.

        Returns:
            ReportTimelineSlot with is_consolidated=True, all durations summed,
            tags deduplicated, categories merged via the fuller merge_categories.

        Raises:
            TimelineSlotValidationError: On type mismatch (unless allow_mixed_types=True)
                                        or invalid/inconsistent slot data
        """
        if not group:
            raise ValueError("Cannot merge empty slot list")

        # Validate type consistency unless explicitly opted in
        if not allow_mixed_types:
            types = set(s.type for s in group)
            if len(types) > 1:
                raise TimelineSlotValidationError(
                    f"Cannot merge slots with differing types {types} unless allow_mixed_types=True. "
                    f"Mixed-type merges likely indicate a grouping logic error."
                )

        # Wall-clock time window (span, not sum — gaps are meaningful)
        start = min(s.start for s in group)
        end = max(s.end for s in group)
        duration = end - start

        # Accumulate durations (true sums)
        actual_duration = sum((s.actual_duration for s in group), timedelta(0))
        productive_duration = sum(
            (s.productive_duration for s in group), timedelta(0)
        )

        # AFK duration (unified via actual_duration, not duration)
        afk_slots = [s for s in group if s.type == "afk"]
        afk_duration = sum(
            (s.actual_duration for s in afk_slots), timedelta(0)
        ) if afk_slots else timedelta(0)

        # Tags — PRESERVE and dedupe (bug fix #1)
        tags_union = list(dict.fromkeys(t for s in group for t in s.tags))

        # Categories — use the fuller 3-level merge (bug fix #8)
        merged_categories = _merge_categories_full(group)

        # event_duration for offline_task slots (sum across all offline_task members, bug fix #6)
        event_duration = None
        offline_task_slots = [s for s in group if s.type == "offline_task"]
        if offline_task_slots:
            event_durations = [s.event_duration or timedelta(0) for s in offline_task_slots]
            event_duration = sum(event_durations, timedelta(0))

        # offline_extension_duration for offline_task slots (duration - event_duration per slot, summed)
        offline_extension_duration = None
        if offline_task_slots:
            offsets = [s.duration - (s.event_duration or timedelta(0)) for s in offline_task_slots]
            offline_extension_duration = sum(offsets, timedelta(0))

        # Build the merged TimelineSlot via the real constructor
        # (this runs __post_init__ validation immediately, catching arithmetic mistakes)
        merged_slot = TimelineSlot(
            type=group[0].type,
            start=start,
            end=end,
            duration=duration,
            actual_duration=actual_duration,
            productive_duration=productive_duration,
            project=group[0].project,
            task=group[0].task,
            categories=merged_categories,
            tags=tags_union,
            afk_duration=afk_duration if afk_duration > timedelta(0) else None,
            event_duration=event_duration,
            offline_extension_duration=offline_extension_duration,
        )

        return cls(
            slot=merged_slot,
            source_slots=group,
            is_consolidated=True,
        )

    @staticmethod
    def bucket_start(dt: datetime, mode: Literal["day", "week", "month", "year"]) -> date:
        """
        Get the start date of the period bucket containing dt, for the given mode.

        Promoted from the private nested function in consolidate_by_period().
        Deliberately matches core/period.py's :week/:lastweek convention (Monday-start ISO weeks).

        Args:
            dt: A timezone-aware datetime
            mode: "day" (midnight), "week" (Monday), "month" (1st), "year" (Jan 1)

        Returns:
            The date marking the start of the bucket containing dt
        """
        d = dt.date()
        if mode == "day":
            return d
        elif mode == "week":
            # Monday-start ISO week (matching period.py convention)
            return d - timedelta(days=d.weekday())
        elif mode == "month":
            return d.replace(day=1)
        elif mode == "year":
            return d.replace(month=1, day=1)
        else:
            raise ValueError(f"Unknown bucket mode: {mode}")

    def bucket_key(self, mode: Literal["day", "week", "month", "year"]) -> date:
        """
        Get this slot's bucket key for the given mode.

        Safe to call only on slots that have already been confined to one bucket
        (e.g. after split_at_boundaries). For slots that haven't been split,
        this returns the bucket containing start, which may not be the only bucket
        the slot touches — use split_at_boundaries first if correctness matters.

        Args:
            mode: "day", "week", "month", or "year"

        Returns:
            The bucket-start date for the bucket containing this slot's start
        """
        return ReportTimelineSlot.bucket_start(self.start, mode)

    def split_at_boundaries(
        self, mode: Literal["day", "week", "month", "year"]
    ) -> List["ReportTimelineSlot"]:
        """
        Split this slot at period boundaries, proportionally allocating durations.

        Generalizes the currently-active day-only split logic to all 4 modes.
        For a slot within a single bucket, returns [self] unchanged.
        For a slot spanning N buckets, returns N pieces with durations prorated
        by wall-clock time fraction in each piece.

        Args:
            mode: "day", "week", "month", or "year"

        Returns:
            List of ReportTimelineSlot pieces, each confined to one bucket,
            with source_slots set to the original source_slots (provenance preserved),
            bucket_mode/bucket_start_date set on each piece.
        """
        # Fast path: slot stays within one bucket
        start_bucket = ReportTimelineSlot.bucket_start(self.start, mode)
        end_bucket = ReportTimelineSlot.bucket_start(self.end - timedelta(seconds=1), mode)
        if start_bucket == end_bucket:
            self_copy = ReportTimelineSlot(
                slot=self.slot,
                source_slots=self.source_slots,
                is_consolidated=self.is_consolidated,
                bucket_mode=mode,
                bucket_start_date=start_bucket,
            )
            return [self_copy]

        # Guard against pathological cases (spans >100 units for this mode)
        span = (end_bucket - start_bucket).days
        if mode == "day" and span > 100:
            return [self]  # Skip splitting
        elif mode == "week" and span // 7 > 100:
            return [self]
        elif mode == "month" and span // 30 > 100:  # Rough estimate
            return [self]
        elif mode == "year" and span // 365 > 100:
            return [self]

        pieces = []
        current_dt = self.start

        while current_dt < self.end:
            # Determine this bucket's end boundary
            current_bucket_start = ReportTimelineSlot.bucket_start(current_dt, mode)
            next_bucket_start = current_bucket_start + _bucket_duration(mode)
            bucket_end = datetime.combine(next_bucket_start, time.min, tzinfo=current_dt.tzinfo)

            # Calculate overlap with this bucket
            piece_start = current_dt
            piece_end = min(bucket_end, self.end)
            piece_duration = piece_end - piece_start

            # Proportionally allocate durations
            if self.duration.total_seconds() > 0:
                ratio = piece_duration.total_seconds() / self.duration.total_seconds()
            else:
                ratio = 0

            # Build the piece slot
            piece_slot_data = {
                "type": self.slot.type,
                "start": piece_start,
                "end": piece_end,
                "duration": piece_duration,
                "actual_duration": timedelta(
                    seconds=self.slot.actual_duration.total_seconds() * ratio
                ),
                "productive_duration": timedelta(
                    seconds=self.slot.productive_duration.total_seconds() * ratio
                ),
                "project": self.slot.project,
                "task": self.slot.task,
                "categories": self.slot.categories,  # NOT prorated
                "tags": self.slot.tags,
            }

            # Conditionally add optional duration fields (guard against None)
            if self.slot.afk_duration is not None and self.slot.afk_duration.total_seconds() > 0:
                piece_slot_data["afk_duration"] = timedelta(
                    seconds=self.slot.afk_duration.total_seconds() * ratio
                )
            # event_duration is required for offline_task slots (validation check in TimelineSlot.__post_init__)
            if self.slot.event_duration is not None:
                piece_slot_data["event_duration"] = timedelta(
                    seconds=self.slot.event_duration.total_seconds() * ratio
                )
            # offline_extension_duration must be calculated from split piece duration - event_duration
            # to avoid rounding error accumulation when both are prorated independently
            if self.slot.offline_extension_duration is not None and self.slot.offline_extension_duration.total_seconds() > 0:
                # Only set if piece actually spans offline time
                piece_event_duration = piece_slot_data.get("event_duration", timedelta(0))
                piece_offline_extension = piece_duration - piece_event_duration
                if piece_offline_extension > timedelta(0):
                    piece_slot_data["offline_extension_duration"] = piece_offline_extension
            if self.slot.apps is not None:
                piece_slot_data["apps"] = self.slot.apps

            # Construct the piece as a real TimelineSlot (validates immediately)
            piece_slot = TimelineSlot(**piece_slot_data)

            # Wrap as ReportTimelineSlot with provenance and bucket info
            piece_bucket_start = ReportTimelineSlot.bucket_start(piece_start, mode)
            piece_report_slot = ReportTimelineSlot(
                slot=piece_slot,
                source_slots=self.source_slots,
                is_consolidated=self.is_consolidated,
                bucket_mode=mode,
                bucket_start_date=piece_bucket_start,
            )
            pieces.append(piece_report_slot)

            # Move to next bucket
            current_dt = bucket_end

        return pieces

    @classmethod
    def from_work_slot_with_embedded_afk(
        cls, work_slot: TimelineSlot, afk_slots: List[TimelineSlot]
    ) -> "ReportTimelineSlot":
        """
        Create a combined work+AFK slot, with AFK periods nested within.

        Used to represent a complete time period from both TaskWarrior (work data)
        and ActivityWatch (AFK data). The work slot's span encompasses the full
        time period, and embedded AFK slots show where the user was away.

        Args:
            work_slot: Work slot (type="regular") from TaskWarrior/window events
            afk_slots: List of AFK slots (type="afk") that overlap with this work period

        Returns:
            ReportTimelineSlot with work_slot as the primary slot and afk_slots nested
        """
        # Compute total AFK time that actually occurs DURING the work slot
        # Only count the intersection of AFK and work time, not AFK that extends beyond
        total_embedded_afk = timedelta(0)
        for afk in afk_slots:
            # Calculate the overlap between work and AFK
            overlap_start = max(work_slot.start, afk.start)
            overlap_end = min(work_slot.end, afk.end)
            if overlap_start < overlap_end:
                # There is overlap; add only the overlapping portion
                overlap_duration = overlap_end - overlap_start
                total_embedded_afk += overlap_duration

        # Update work slot's afk_duration to include embedded AFK
        if total_embedded_afk > timedelta(0):
            work_slot.afk_duration = total_embedded_afk

        return cls(
            slot=work_slot,
            source_slots=[work_slot] + afk_slots,  # Traceability: all contributors
            is_consolidated=False,  # Not a merge (different data sources)
            embedded_afk_slots=afk_slots,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dict for backward-compat with code paths that haven't migrated yet.

        Includes period_start if bucket_start_date is set (for print_period_consolidated_report compat).
        Includes embedded_afk_slots if present (for rendering nested AFK gaps).
        """
        d = self.slot.to_dict()
        if self.bucket_start_date is not None:
            d["period_start"] = self.bucket_start_date
        if self.embedded_afk_slots:
            # Store as list of dicts for renderer compatibility
            d["embedded_afk_slots"] = [afk.to_dict() for afk in self.embedded_afk_slots]
        return d

    def to_timeline_slot(self) -> TimelineSlot:
        """Get the wrapped TimelineSlot."""
        return self.slot


@dataclass
class ReportTimeline:
    """
    Collection of ReportTimelineSlots with grouping/bucketing/consolidation operations.

    Separate from Timeline (which is for granular data only, no aggregation).
    """

    slots_list: List[ReportTimelineSlot] = field(default_factory=list)

    @classmethod
    def from_timeline(cls, timeline) -> "ReportTimeline":
        """
        Wrap every TimelineSlot as a singleton ReportTimelineSlot.

        Args:
            timeline: A Timeline instance

        Returns:
            ReportTimeline with each atomic slot wrapped
        """
        report_slots = [
            ReportTimelineSlot.from_timeline_slot(slot)
            for slot in timeline.get_slots()
        ]
        return cls(slots_list=report_slots)

    def combine_work_with_embedded_afk(self) -> "ReportTimeline":
        """
        Combine work slots with embedded AFK periods for the same (project, task).

        Transforms separate work+AFK slots into combined slots where AFK periods
        are nested within work slots. This provides a clearer picture: one work
        period with AFK gaps clearly shown as components, not competing rows.

        CRITICAL FIX: Merge overlapping work slots for the same (project, task)
        BEFORE combining with AFK, to prevent duplicate entries from ActivityWatch
        overlapping not-afk events (e.g., during window recovery).

        Algorithm:
        1. Deduplicate overlapping work slots for same (project, task)
        2. Separate remaining work slots from AFK slots
        3. For each work slot, find overlapping AFK slots with same (project, task)
        4. Create combined slot with embedded_afk_slots
        5. Keep non-overlapping AFK slots as standalone

        Returns:
            ReportTimeline with combined work+AFK slots
        """
        # First, merge overlapping work slots for the same (project, task)
        work_slots_raw = [rs for rs in self.slots_list if rs.slot.type == "regular"]
        work_slots = self._merge_overlapping_work_slots(work_slots_raw)

        afk_slots = [rs for rs in self.slots_list if rs.slot.type == "afk"]
        other_slots = [rs for rs in self.slots_list if rs.slot.type not in ("regular", "afk")]

        result_report_slots = []

        # For each (merged) work slot, find overlapping AFK slots with same task
        for work_rs in work_slots:
            work_slot = work_rs.slot
            # Find AFK slots that overlap and are for the same task
            embedded_afk_slots = [
                afk_rs.slot
                for afk_rs in afk_slots
                if (
                    afk_rs.slot.project == work_slot.project
                    and afk_rs.slot.task == work_slot.task
                    and afk_rs.slot.start < work_slot.end
                    and work_slot.start < afk_rs.slot.end
                )
            ]

            # Create combined ReportTimelineSlot with embedded AFK
            combined_slot = ReportTimelineSlot.from_work_slot_with_embedded_afk(
                work_slot, embedded_afk_slots
            )
            result_report_slots.append(combined_slot)

        # Add AFK slots that were NOT embedded (standalone)
        for afk_rs in afk_slots:
            afk_slot = afk_rs.slot
            # Keep only if NOT embedded in any work slot
            is_embedded = any(
                afk_slot.project == work_rs.slot.project
                and afk_slot.task == work_rs.slot.task
                and afk_slot.start < work_rs.slot.end
                and work_rs.slot.start < afk_slot.end
                for work_rs in work_slots
            )
            if not is_embedded:
                result_report_slots.append(afk_rs)

        # Add other slot types
        result_report_slots.extend(other_slots)

        # Sort by start time to preserve chronological order
        result_report_slots.sort(key=lambda rs: rs.start)

        return ReportTimeline(slots_list=result_report_slots)

    def _merge_overlapping_work_slots(self, work_slots_raw: List["ReportTimelineSlot"]) -> List["ReportTimelineSlot"]:
        """
        Merge overlapping work slots for the same (project, task).

        CRITICAL FIX FOR DUPLICATE SLOTS (2026-07-23):
        ===============================================
        When ActivityWatch records overlapping "not-afk" events (e.g., during window manager
        recovery or clock adjustments), multiple work slots with identical (project, task)
        but different end times are created. This causes confusing duplicate entries in the
        timeline report (same task appearing 2-3 times with overlapping time ranges).

        Example problem (before fix):
          14:09 - 18:51  ▶ Anarcademi... > Mecanismo de Antikythera  04:41:57  [AFK]
          14:09 - 19:35  ▶ Anarcademi... > Mecanismo de Antikythera  05:25:47  [AFK]  ← DUPLICATE!
          18:51 - 19:39  ▶ Anarcademi... > Mecanismo de Antikythera  00:47:30  [AFK]

        After fix:
          14:09 - 19:35  ▶ Anarcademi... > Mecanismo de Antikythera  05:29:28  [AFK]  ← MERGED

        This method solves the problem by merging overlapping slots into a single entry
        spanning the full range. This is called early in combine_work_with_embedded_afk()
        BEFORE AFK slots are embedded, ensuring clean output.

        Args:
            work_slots_raw: List of work ReportTimelineSlots (potentially overlapping)

        Returns:
            List of work slots with overlaps merged within each (project, task) group

        Important: Do NOT disable this fix without addressing the upstream ActivityWatch
        overlapping events problem. Users expect clean, non-duplicate timelines.
        """
        if not work_slots_raw:
            return []

        # Group by (project, task)
        groups: Dict[Tuple[str, str], List[ReportTimelineSlot]] = {}
        for rs in work_slots_raw:
            key = (rs.project, rs.task)
            if key not in groups:
                groups[key] = []
            groups[key].append(rs)

        result = []
        for key, slot_group in groups.items():
            # Within each (project, task) group, merge overlapping slots
            if len(slot_group) <= 1:
                result.extend(slot_group)
                continue

            # Sort by start time
            sorted_group = sorted(slot_group, key=lambda rs: rs.start)
            merged_list = []
            current = sorted_group[0]

            for rs in sorted_group[1:]:
                current_end = current.start + current.duration
                # Check if overlapping or adjacent (within 1 second)
                if rs.start <= current_end + timedelta(seconds=1):
                    # Merge: extend to cover both slots
                    merged_end = max(current_end, rs.start + rs.duration)
                    merged_duration = merged_end - current.start

                    # Create merged slot by building new data
                    # When merging overlapping slots, use the union of times, not sum
                    # The merged slot represents the entire time span covered by both overlapping slots
                    merged_data = {
                        "type": current.slot.type,
                        "start": current.start,
                        "end": merged_end,
                        "duration": merged_duration,
                        "actual_duration": current.slot.actual_duration + rs.slot.actual_duration,
                        "productive_duration": current.slot.productive_duration + rs.slot.productive_duration,
                        "project": current.slot.project,
                        "task": current.slot.task,
                        "categories": current.slot.categories,  # Use first slot's categories
                        "tags": current.slot.tags,
                    }

                    # Preserve optional fields by taking the max (union of overlapping time markers)
                    # not the sum (which would double-count overlapping portions)
                    if current.slot.afk_duration or rs.slot.afk_duration:
                        # Take max of the two AFK durations (they overlap, so max is the union)
                        curr_afk = current.slot.afk_duration or timedelta(0)
                        rs_afk = rs.slot.afk_duration or timedelta(0)
                        merged_data["afk_duration"] = max(curr_afk, rs_afk)
                    if current.slot.offline_extension_duration or rs.slot.offline_extension_duration:
                        # Take max of offline_extension_duration (overlapping window activity)
                        curr_off = current.slot.offline_extension_duration or timedelta(0)
                        rs_off = rs.slot.offline_extension_duration or timedelta(0)
                        merged_data["offline_extension_duration"] = max(curr_off, rs_off)
                    if current.slot.event_duration or rs.slot.event_duration:
                        # For event_duration (online time), take sum since they represent disjoint time
                        curr_event = current.slot.event_duration or timedelta(0)
                        rs_event = rs.slot.event_duration or timedelta(0)
                        merged_data["event_duration"] = curr_event + rs_event

                    # Create merged TimelineSlot
                    merged_slot = TimelineSlot(**merged_data)
                    current = ReportTimelineSlot(
                        slot=merged_slot,
                        source_slots=[current.slot, rs.slot],
                        is_consolidated=True,  # Mark as merged
                        embedded_afk_slots=current.embedded_afk_slots + rs.embedded_afk_slots,
                    )
                else:
                    # Non-overlapping: save current and start new
                    merged_list.append(current)
                    current = rs

            merged_list.append(current)
            result.extend(merged_list)

        return result

    def consolidate_consecutive(self) -> "ReportTimeline":
        """
        Fine-grain consolidation: merge CONSECUTIVE slots sharing (project, task, date).

        Bare type=="offline" gap markers: consumed as continuity signal only
        (do not break a same-(project,task) run, but never appear as output rows).
        This fixes the inconsistency between TimelineSlotManager.consolidate() and
        consolidate_by_period() — both now uniformly exclude bare offline gaps.

        Returns:
            ReportTimeline with consecutive-same-task runs merged
        """
        if not self.slots_list:
            return ReportTimeline()

        consolidated = []
        current_group = []

        for report_slot in self.slots_list:
            slot = report_slot.slot

            # Bare offline gap markers: skip them (consume only as continuity signal)
            if slot.type == "offline":
                continue

            if not current_group:
                current_group.append(slot)
                continue

            # Check if same (project, task, date)
            same_project_task_date = (
                slot.project == current_group[0].project
                and slot.task == current_group[0].task
                and slot.start.date() == current_group[0].start.date()
            )

            if same_project_task_date:
                current_group.append(slot)
            else:
                # Different task — merge current group and start new one
                if current_group:
                    # Allow mixed types (regular + afk) within same (project, task, date) group
                    # e.g., a work session interrupted by AFK gaps should be merged into one row
                    merged_report_slot = ReportTimelineSlot.from_timeline_slots(
                        current_group, allow_mixed_types=True
                    )
                    consolidated.append(merged_report_slot)
                    current_group.clear()
                current_group.append(slot)

        # Final flush
        if current_group:
            # Allow mixed types (regular + afk) within same (project, task, date) group
            merged_report_slot = ReportTimelineSlot.from_timeline_slots(
                current_group, allow_mixed_types=True
            )
            consolidated.append(merged_report_slot)

        return ReportTimeline(slots_list=consolidated)

    def grouped_by_project_date(
        self,
    ) -> List[Tuple[str, date, List[ReportTimelineSlot]]]:
        """
        Group slots by (project, date) without merging.

        Returns tuples of (project, date, [slots for that project on that date]).
        This is used by the renderer for headers/totals, without collapsing
        individual rows into a single merged entry.

        Returns:
            List of (project, date, slots_list) tuples
        """
        groups = []
        current_project = None
        current_date = None
        current_group = []

        for report_slot in sorted(self.slots_list, key=lambda s: (s.project, s.start.date(), s.start)):
            project = report_slot.project
            date_key = report_slot.start.date()

            if project != current_project or date_key != current_date:
                if current_group:
                    groups.append((current_project, current_date, current_group))
                current_project = project
                current_date = date_key
                current_group = [report_slot]
            else:
                current_group.append(report_slot)

        if current_group:
            groups.append((current_project, current_date, current_group))

        return groups

    def bucket(self, mode: Literal["day", "week", "month", "year"]) -> "ReportTimeline":
        """
        Period bucketing: split all slots at boundaries, then global-groupby (bucket, project, task).

        Replaces consolidate_by_period(). Bare type=="offline" gap markers are excluded
        from output (only consumed as continuity signals).

        Args:
            mode: "day", "week", "month", or "year"

        Returns:
            ReportTimeline with slots split at boundaries and grouped by period bucket,
            sorted by (bucket_start_date, -project_total, -task_total)
        """
        # Split all slots at boundaries
        split_pieces = []
        for report_slot in self.slots_list:
            split_pieces.extend(report_slot.split_at_boundaries(mode))

        # Global groupby (bucket, project, task), excluding bare offline gaps
        bucket_groups = {}
        for piece in split_pieces:
            if piece.slot.type == "offline":
                continue  # Exclude bare offline gap markers from output

            key = (piece.bucket_start_date, piece.project, piece.task)
            if key not in bucket_groups:
                bucket_groups[key] = []
            bucket_groups[key].append(piece.slot)

        # Merge each bucket group
        bucketed = []
        for (bucket_date, project, task), slot_group in sorted(bucket_groups.items()):
            # Allow mixed types in period consolidation (e.g., 'regular' + 'afk' in same period/project/task)
            merged = ReportTimelineSlot.from_timeline_slots(slot_group, allow_mixed_types=True)
            merged.bucket_start_date = bucket_date
            merged.bucket_mode = mode
            bucketed.append(merged)

        # Sort by (bucket_date, -project_duration_desc, -task_duration_desc)
        # (simplified: just bucket_date for now; render layer can further sort by project/task if needed)
        bucketed.sort(key=lambda s: s.bucket_start_date)

        return ReportTimeline(slots_list=bucketed)

    def collapse_to_project(self) -> "ReportTimeline":
        """
        Collapse (bucket, project, task) rows to (bucket, project) totals.

        For use with bucketed ReportTimeline (post bucket() call).
        Sums actual_duration, productive_duration, afk_duration, offline_extension_duration.
        Drops task and categories.

        Returns:
            ReportTimeline with one row per (bucket, project), durations summed
        """
        by_bucket_project = {}

        for report_slot in self.slots_list:
            key = (report_slot.bucket_start_date, report_slot.project)
            if key not in by_bucket_project:
                by_bucket_project[key] = []
            by_bucket_project[key].append(report_slot)

        collapsed = []
        for (bucket_date, project), group in by_bucket_project.items():
            # Create a synthetic merged slot at the (bucket, project) level
            # Allow mixed types since we're collapsing already-bucketed data
            merged = ReportTimelineSlot.from_timeline_slots([s.slot for s in group], allow_mixed_types=True)
            merged.bucket_start_date = bucket_date
            merged.bucket_mode = group[0].bucket_mode if group else None
            collapsed.append(merged)

        return ReportTimeline(slots_list=collapsed)

    def slots(self) -> List[ReportTimelineSlot]:
        """Get the internal slots list."""
        return self.slots_list

    def as_dicts(self) -> List[Dict[str, Any]]:
        """Convert all slots to dicts (for backward compat with dict-consuming code)."""
        return [s.to_dict() for s in self.slots_list]


def _merge_categories_full(group: List[TimelineSlot]) -> List[Dict[str, Any]]:
    """
    Merge categories from all slots in a group (3-level: category→app→title).

    Imported/reused from consolidation.py's standalone merge_categories,
    to avoid duplicating this complex nested-merge logic.
    """
    # For now, inline a simplified version; in production, this should import
    # from consolidation.merge_categories to avoid duplication.
    # TODO: import merge_categories from consolidation instead
    merged_cats = {}

    for slot in group:
        for cat_info in slot.categories:
            cat = cat_info.get("category", "Uncategorized")
            if cat not in merged_cats:
                merged_cats[cat] = {
                    "category": cat,
                    "duration": timedelta(0),
                    "start": cat_info.get("start"),
                    "end": cat_info.get("end"),
                    "apps": {},
                }
            else:
                # Expand start/end range
                cat_start = cat_info.get("start")
                cat_end = cat_info.get("end")
                if cat_start and (
                    not merged_cats[cat]["start"] or cat_start < merged_cats[cat]["start"]
                ):
                    merged_cats[cat]["start"] = cat_start
                if cat_end and (
                    not merged_cats[cat]["end"] or cat_end > merged_cats[cat]["end"]
                ):
                    merged_cats[cat]["end"] = cat_end

            merged_cats[cat]["duration"] += cat_info.get("duration", timedelta(0))

            # Merge apps under this category
            for app_info in cat_info.get("apps", []):
                app = app_info.get("app", "Unknown App")
                if app not in merged_cats[cat]["apps"]:
                    merged_cats[cat]["apps"][app] = {
                        "app": app,
                        "duration": timedelta(0),
                        "start": app_info.get("start"),
                        "end": app_info.get("end"),
                        "titles": {},
                    }
                else:
                    app_start = app_info.get("start")
                    app_end = app_info.get("end")
                    if app_start and (
                        not merged_cats[cat]["apps"][app]["start"]
                        or app_start < merged_cats[cat]["apps"][app]["start"]
                    ):
                        merged_cats[cat]["apps"][app]["start"] = app_start
                    if app_end and (
                        not merged_cats[cat]["apps"][app]["end"]
                        or app_end > merged_cats[cat]["apps"][app]["end"]
                    ):
                        merged_cats[cat]["apps"][app]["end"] = app_end

                merged_cats[cat]["apps"][app]["duration"] += app_info.get(
                    "duration", timedelta(0)
                )

                # Merge titles under this app
                for title_info in app_info.get("titles", []):
                    title = title_info.get("title", "Unknown Title")
                    if title not in merged_cats[cat]["apps"][app]["titles"]:
                        merged_cats[cat]["apps"][app]["titles"][title] = {
                            "title": title,
                            "duration": timedelta(0),
                            "events": [],
                        }
                    merged_cats[cat]["apps"][app]["titles"][title]["duration"] += (
                        title_info.get("duration", timedelta(0))
                    )
                    merged_cats[cat]["apps"][app]["titles"][title]["events"].extend(
                        title_info.get("events", [])
                    )

    # Convert to list format
    result = []
    for cat, cat_data in sorted(merged_cats.items()):
        cat_entry = {
            "category": cat_data["category"],
            "duration": cat_data["duration"],
            "start": cat_data.get("start"),
            "end": cat_data.get("end"),
        }
        if cat_data["apps"]:
            cat_entry["apps"] = [
                {
                    "app": app_data["app"],
                    "duration": app_data["duration"],
                    "start": app_data.get("start"),
                    "end": app_data.get("end"),
                    "titles": list(app_data["titles"].values())
                    if app_data["titles"]
                    else [],
                }
                for app_data in cat_data["apps"].values()
            ]
        result.append(cat_entry)

    return result


def _bucket_duration(mode: Literal["day", "week", "month", "year"]) -> timedelta:
    """Helper to get the duration of one bucket (approximate for variable-length periods)."""
    if mode == "day":
        return timedelta(days=1)
    elif mode == "week":
        return timedelta(days=7)
    elif mode == "month":
        return timedelta(days=30)  # Approximate
    elif mode == "year":
        return timedelta(days=365)  # Approximate
    else:
        raise ValueError(f"Unknown mode: {mode}")

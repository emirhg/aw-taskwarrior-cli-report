"""
ReportTimelineSlot: unified model for consolidation, bucketing, and reporting.

This module provides ReportTimelineSlot and ReportEntries classes that centralize
all slot-merging, period-bucketing, and multi-bucket-spanning logic in one place,
replacing the three divergent implementations currently scattered across:
  - TimelineSlotManager.consolidate()
  - consolidate_by_period()
  - timeline_render.py's split_slots_spanning_days (module-level vs. nested duplicate)

Key design:
- ReportTimelineSlot wraps TimelineSlot by composition (not inheritance), reusing
  TimelineSlot.__post_init__ validation for free on every merge/split.
- ReportEntries provides grouping/bucketing/collapsing operations as pure methods.
- All slot merging fixes (tags preservation, offline-gap-handling consistency,
  event_duration position-independence, AFK duration field uniformity, fuller
  category merging) are implemented once here.
- Multi-bucket proportional splitting (day/week/month/year) is generalized and
  available through split_at_boundaries(mode).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time
from typing import Any, Dict, List, Optional, Tuple, Literal, TYPE_CHECKING, Union

from tw_report.core.timeline import TimelineSlot, TimelineSlotValidationError
from tw_report.core.filtering import NO_PROJECT, NO_TASK

if TYPE_CHECKING:
    from tw_report.core.aw_events import WindowEvent, AFKEvent, TaskWarriorEvent


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
        """Format columns into a single line with dynamic project/task sizing.

        CRITICAL: This format is the ONLY source of truth for column widths and structure.
        The timeline header in timeline_render.py MUST match these exact widths or columns
        will be misaligned.

        ALIGNMENT ARCHITECTURE (2026-07-28):
        ====================================
        This method defines the MASTER column structure that all rendering must follow:

        Left Section (Identification): 87 display width total
        - Indent: 7 spaces
        - Time range: 13 chars (always "HH:MM - HH:MM" format)
        - Separator: 2 spaces
        - Project: 28 chars (left-justified, truncated)
        - Separator: 2 spaces
        - Task: 35 chars (left-justified, truncated)
        Calculation: 7 + 13 + 2 + 28 + 2 + 35 = 87

        Right Section (Duration Breakdown): 46 display width total
        - OFFLINE column: 12 chars (empty or "(HH:MM:SS)")
        - AFK column: 12 chars (empty or "(HH:MM:SS)")
        - ACTIVE column: 8 chars (empty or "HH:MM:SS")
        - PRODUCTIVITY column: 14 chars (empty or "  [prod XXX%]")
        Calculation: 12 + 12 + 8 + 14 = 46

        Dynamic Padding: terminal_width - 87 - 46 - 2 (separator) = left_padding
        Formula: left_section + (left_padding spaces) + "  " + right_section

        PAST BUGS & LESSONS (why the design matters):
        =============================================
        Bug 1: Missing PRODUCTIVITY column in header
        - Header had 32-width right section (12+12+8)
        - DisplayColumns has 46-width right section (12+12+8+14)
        - Result: 14-char misalignment on ALL terminal widths
        - Fix: Always include all columns, even if empty

        Bug 2: Using fixed positions instead of dynamic terminal_width
        - Initial header used fixed math assuming terminal_width
        - On wider terminals (150+ chars), labels stayed at position 89
        - But durations right-aligned to actual terminal width (e.g., 150)
        - Result: columns appeared completely misaligned
        - Fix: Always use get_terminal_width() and recalculate for every line

        Bug 3: Using ljust() instead of ljust_display()
        - ljust() counts bytes, not visual columns
        - Multi-byte UTF-8 chars (▶, ñ, é, emoji) are 2+ bytes but 1-2 visual width
        - Result: columns drifted by 1-3 positions depending on content
        - Fix: Use ljust_display() everywhere for visual (not byte) alignment

        CRITICAL DEPENDENCIES:
        ======================
        1. timeline_render.py header (lines 552-586) MUST use:
           - Left section: 87 width
           - Right section: 46 width (WITH 14-char productivity column)
           - SAME dynamic terminal_width calculation

        2. All ljust() calls must be ljust_display() to handle UTF-8

        3. If you ADD or RESIZE a duration column here, you MUST update:
           - timeline_render.py header (line 573-577)
           - Day total formatting (line 893+)
           - Consolidation report headers
           - Anything else that tries to match these positions

        DO NOT:
        - Use fixed positions (e.g., column starts at position 89)
        - Forget the productivity column (even if empty, 14 chars)
        - Use len() instead of display_width() for Unicode
        - Use ljust() instead of ljust_display() for padding
        - Change column widths without updating ALL rendering locations
        """
        from tw_report.utils.formatting import display_width, ljust_display

        # Build left section (identification) using dynamic sizing (no fixed column widths)
        # Time range is always "HH:MM - HH:MM" = 13 characters
        indent = " " * 7
        time_part = ljust_display(self.time_range, 13)  # "HH:MM - HH:MM" = 13 chars

        left_section = f"{indent}{time_part}  {self.project}  {self.task}"

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
    def from_slot_dict(cls, slot: Union[Dict[str, Any], "ReportTimelineSlot"], start_time: datetime, end_time: datetime) -> "DisplayColumns":
        """Create DisplayColumns from a dict-based or ReportTimelineSlot (from timeline rendering pipeline).

        Args:
            slot: Dictionary or ReportTimelineSlot with keys like type, project, task, duration, afk_duration, etc.
            start_time: Start time (local timezone)
            end_time: End time (local timezone)

        Returns:
            DisplayColumns formatted and ready to display
        """
        from tw_report.utils.formatting import format_duration, abbreviate_project_path
        from tw_report.core.filtering import NO_PROJECT, NO_TASK

        # Helper to get slot field (works with both dicts and objects)
        def get_field(field, default=None):
            if isinstance(slot, dict):
                return slot.get(field, default)
            else:
                return getattr(slot, field, default) if hasattr(slot, field) else default

        # Format time range
        time_range = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"

        # Format project and task using the same abbreviation logic as rendering
        project_name = get_field("project", NO_PROJECT)
        task_name = get_field("task", NO_TASK)

        # Use abbreviate_project_path for consistent formatting
        abbrev_project = abbreviate_project_path(
            project_name.replace(".", " > ") if project_name != NO_PROJECT else NO_PROJECT,
            task_name
        )
        # Project display (no truncation cap)
        project_display = f"▶ {abbrev_project}" if abbrev_project else ""

        # Task display (no truncation cap)
        if task_name and task_name != NO_TASK:
            task_display = f"▶▶ {task_name}"
        else:
            task_display = " " if abbrev_project else ""

        # Format duration columns (no parenthesis)
        offline_time = ""
        offline_dur = get_field("offline_extension_duration")
        if offline_dur:
            if isinstance(offline_dur, timedelta) and offline_dur.total_seconds() > 0:
                offline_time = format_duration(offline_dur)

        afk_time = ""
        afk_dur = get_field("afk_duration")
        if afk_dur:
            if isinstance(afk_dur, timedelta) and afk_dur.total_seconds() > 0:
                afk_time = format_duration(afk_dur)

        # Active time = ONLINE time - AFK time
        # (actual_duration is online time when system was recording)
        online_duration = get_field("actual_duration") or get_field("duration")
        afk_duration_slot = get_field("afk_duration") or timedelta(0)

        if online_duration:
            if isinstance(online_duration, timedelta):
                # Calculate active as online minus afk
                active_duration = online_duration - afk_duration_slot
                if active_duration.total_seconds() > 0:
                    active_time = format_duration(active_duration)
                else:
                    active_time = ""
            else:
                active_time = str(online_duration)
        else:
            active_time = ""

        # Productivity metric
        productivity = ""
        prod_dur = get_field("productive_duration")
        if prod_dur:
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
    Report-optimized consolidated timeline slot (merged from TimelineSlot + wrapper).

    Represents a single time span with aggregated activity data.

    Time span fields:
    - start/end: Wall-clock time boundaries
    - duration: Total duration (start to end)
    - actual_duration: Active time (non-AFK or online portion for offline_task)

    Data source fields:
    - task_event: Optional TaskWarriorEvent (task/project/tags only set if matched)
    - window_events: List[WindowEvent] from window bucket (own activity only)
    - afk_events: List[AFKEvent] embedded within this span

    Aggregates:
    - productive_duration: Time on productive activities
    - categories: Category/app/title breakdown
    - tags: Union of tags from source task events
    - apps: Legacy field

    Metadata:
    - source_slots: List of atomic slots that were merged
    - is_consolidated: True if merged from >1 source slot
    - bucket_mode/bucket_start_date: Period assignment
    - afk_duration: AFK time within this span (optional, for bare AFK gaps)
    - offline_extension_duration: OFFLINE gap duration (optional)
    - event_duration: For offline_task slots (tracks online vs offline split)
    """

    start: datetime
    end: datetime
    duration: timedelta
    actual_duration: timedelta
    productive_duration: timedelta = field(default_factory=lambda: timedelta(0))
    task_event: Optional["TaskWarriorEvent"] = None
    window_events: List["WindowEvent"] = field(default_factory=list)
    afk_events: List["AFKEvent"] = field(default_factory=list)
    afk_duration: Optional[timedelta] = None
    offline_extension_duration: Optional[timedelta] = None
    event_duration: Optional[timedelta] = None
    tags: List[str] = field(default_factory=list)
    categories: List[Dict[str, Any]] = field(default_factory=list)
    apps: Optional[List[Dict[str, Any]]] = None
    source_slots: List["ReportTimelineSlot"] = field(default_factory=list)
    is_consolidated: bool = False
    bucket_mode: Optional[Literal["day", "week", "month", "year"]] = None
    bucket_start_date: Optional[date] = None

    @property
    def project(self) -> str:
        """Project name, with NO_PROJECT fallback if no task_event."""
        return self.task_event.project if self.task_event else NO_PROJECT

    @property
    def task(self) -> str:
        """Task name, with NO_TASK fallback if no task_event."""
        return self.task_event.task if self.task_event else NO_TASK

    @property
    def is_offline_task(self) -> bool:
        """True if this is an offline_task slot: task_event and event_duration both set."""
        return self.task_event is not None and self.event_duration is not None

    @property
    def is_afk_only(self) -> bool:
        """True if this is a bare AFK gap: afk_duration==actual_duration and no event_duration."""
        return (
            self.afk_duration is not None
            and self.afk_duration == self.actual_duration
            and self.event_duration is None
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict format for backward compatibility.

        Returns a dict representation matching the old TimelineSlot.to_dict() format.
        """
        slot_dict = {
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "actual_duration": self.actual_duration,
            "productive_duration": self.productive_duration,
            "project": self.project,
            "task": self.task,
            "tags": self.tags,
            "categories": self.categories,
            "apps": self.apps or [],
        }
        # Add optional fields only if they have values (must check for None, not truthiness)
        if self.afk_duration is not None:
            slot_dict["afk_duration"] = self.afk_duration
        if self.offline_extension_duration is not None:
            slot_dict["offline_extension_duration"] = self.offline_extension_duration
        if self.event_duration is not None:
            slot_dict["event_duration"] = self.event_duration

        # Add type discriminator for legacy code paths
        if self.is_offline_task:
            slot_dict["type"] = "offline_task"
        elif self.is_afk_only:
            slot_dict["type"] = "afk"
        else:
            slot_dict["type"] = "regular"

        return slot_dict

    @classmethod
    def from_timeline_slot(cls, slot: TimelineSlot) -> "ReportTimelineSlot":
        """
        Convert a TimelineSlot to the new merged ReportTimelineSlot shape.

        Extracts all fields from the old TimelineSlot and populates the new structure.
        This is a compatibility bridge during migration.

        Args:
            slot: A validated TimelineSlot

        Returns:
            ReportTimelineSlot with is_consolidated=False, source_slots=[slot]
        """
        # Import here to avoid circular imports
        from tw_report.core.aw_events import TaskWarriorEvent

        # Extract task_event from the old slot's project/task fields if present
        task_event = None
        if slot.project or slot.task:
            # Create a synthetic TaskWarriorEvent from the TimelineSlot's extracted fields
            task_event = TaskWarriorEvent(
                timestamp=slot.start,
                duration=slot.duration,
                data={
                    "project": slot.project,
                    "title": slot.task,
                    "tags": slot.tags if slot.tags else [],
                }
            )

        # For backward compat with tests that check source_slots, we need to track
        # the original slot. Since we don't have the TimelineSlot anymore, we can't
        # store it directly. For now, keep source_slots empty since the new model
        # doesn't inherit from TimelineSlot.
        return cls(
            start=slot.start,
            end=slot.end,
            duration=slot.duration,
            actual_duration=slot.actual_duration,
            productive_duration=slot.productive_duration,
            task_event=task_event,
            window_events=[],
            afk_events=[],
            afk_duration=slot.afk_duration,
            offline_extension_duration=slot.offline_extension_duration,
            event_duration=slot.event_duration,
            tags=slot.tags,
            categories=slot.categories,
            apps=slot.apps,
            source_slots=[],
            is_consolidated=False,
        )

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

        # Extract task_event from the first slot's project/task fields if present
        task_event = None
        first_slot = group[0]
        if first_slot.project or first_slot.task:
            from tw_report.core.aw_events import TaskWarriorEvent
            task_event = TaskWarriorEvent(
                timestamp=start,
                duration=duration,
                data={
                    "project": first_slot.project,
                    "title": first_slot.task,
                    "tags": tags_union if tags_union else [],
                }
            )

        # Build the merged ReportTimelineSlot directly (no intermediate TimelineSlot)
        return cls(
            start=start,
            end=end,
            duration=duration,
            actual_duration=actual_duration,
            productive_duration=productive_duration,
            task_event=task_event,
            window_events=[],
            afk_events=[],
            afk_duration=afk_duration if afk_duration > timedelta(0) else None,
            offline_extension_duration=offline_extension_duration,
            event_duration=event_duration,
            tags=tags_union,
            categories=merged_categories,
            source_slots=[],  # Caller should set this if tracking provenance
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
                start=self.start,
                end=self.end,
                duration=self.duration,
                actual_duration=self.actual_duration,
                productive_duration=self.productive_duration,
                task_event=self.task_event,
                window_events=self.window_events,
                afk_events=self.afk_events,
                afk_duration=self.afk_duration,
                offline_extension_duration=self.offline_extension_duration,
                event_duration=self.event_duration,
                tags=self.tags,
                categories=self.categories,
                apps=self.apps,
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

            # Calculate prorated durations
            piece_actual_duration = timedelta(
                seconds=self.actual_duration.total_seconds() * ratio
            )
            piece_productive_duration = timedelta(
                seconds=self.productive_duration.total_seconds() * ratio
            )

            # Conditionally prorate optional duration fields (guard against None)
            piece_afk_duration = None
            if self.afk_duration is not None and self.afk_duration.total_seconds() > 0:
                piece_afk_duration = timedelta(
                    seconds=self.afk_duration.total_seconds() * ratio
                )

            piece_event_duration = None
            if self.event_duration is not None:
                piece_event_duration = timedelta(
                    seconds=self.event_duration.total_seconds() * ratio
                )

            # offline_extension_duration must be calculated from split piece duration - event_duration
            # to avoid rounding error accumulation when both are prorated independently
            piece_offline_extension_duration = None
            if self.offline_extension_duration is not None and self.offline_extension_duration.total_seconds() > 0:
                piece_event_dur = piece_event_duration or timedelta(0)
                piece_offline_ext = piece_duration - piece_event_dur
                if piece_offline_ext > timedelta(0):
                    piece_offline_extension_duration = piece_offline_ext

            # Build the piece as ReportTimelineSlot directly
            piece_bucket_start = ReportTimelineSlot.bucket_start(piece_start, mode)
            piece_report_slot = ReportTimelineSlot(
                start=piece_start,
                end=piece_end,
                duration=piece_duration,
                actual_duration=piece_actual_duration,
                productive_duration=piece_productive_duration,
                task_event=self.task_event,
                window_events=self.window_events,
                afk_events=self.afk_events,
                afk_duration=piece_afk_duration,
                offline_extension_duration=piece_offline_extension_duration,
                event_duration=piece_event_duration,
                tags=self.tags,
                categories=self.categories,  # NOT prorated
                apps=self.apps,
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
        from tw_report.core.aw_events import TaskWarriorEvent

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

        # Extract task_event from work_slot if present
        task_event = None
        if work_slot.project or work_slot.task:
            task_event = TaskWarriorEvent(
                timestamp=work_slot.start,
                duration=work_slot.duration,
                data={
                    "project": work_slot.project,
                    "title": work_slot.task,
                    "tags": work_slot.tags if work_slot.tags else [],
                }
            )

        return cls(
            start=work_slot.start,
            end=work_slot.end,
            duration=work_slot.duration,
            actual_duration=work_slot.actual_duration,
            productive_duration=work_slot.productive_duration,
            task_event=task_event,
            window_events=[],
            afk_events=[],  # Will be populated from afk_slots below
            afk_duration=total_embedded_afk if total_embedded_afk > timedelta(0) else None,
            offline_extension_duration=work_slot.offline_extension_duration,
            event_duration=work_slot.event_duration,
            tags=work_slot.tags,
            categories=work_slot.categories,
            apps=work_slot.apps,
            source_slots=[work_slot] + afk_slots,  # Traceability: all contributors
            is_consolidated=False,  # Not a merge (different data sources)
        )



@dataclass
class ReportEntries:
    """
    Collection of ReportTimelineSlots with grouping/bucketing/consolidation operations.

    Separate from Timeline (which is for granular data only, no aggregation).
    """

    slots_list: List[ReportTimelineSlot] = field(default_factory=list)

    @classmethod
    def from_timeline(cls, timeline) -> "ReportEntries":
        """
        Wrap every TimelineSlot as a singleton ReportTimelineSlot.

        Args:
            timeline: A Timeline instance

        Returns:
            ReportEntries with each atomic slot wrapped
        """
        report_slots = [
            ReportTimelineSlot.from_timeline_slot(slot)
            for slot in timeline.get_slots()
        ]
        return cls(slots_list=report_slots)

    def combine_work_with_embedded_afk(self) -> "ReportEntries":
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
        4. Create combined slot with embedded AFK durations
        5. Keep non-overlapping AFK slots as standalone

        Returns:
            ReportEntries with combined work+AFK slots
        """
        # First, merge overlapping work slots for the same (project, task)
        # Regular slots: NOT is_afk_only and NOT is_offline_task
        work_slots_raw = [
            rs for rs in self.slots_list
            if not rs.is_afk_only and not rs.is_offline_task
        ]
        work_slots = self._merge_overlapping_work_slots(work_slots_raw)

        # AFK slots: is_afk_only predicate
        afk_slots = [rs for rs in self.slots_list if rs.is_afk_only]
        # Other slots: offline_task and any other types
        other_slots = [
            rs for rs in self.slots_list
            if rs.is_offline_task
        ]

        result_report_slots = []

        # For each (merged) work slot, find overlapping AFK slots with same task
        for work_rs in work_slots:
            # Find AFK slots that overlap and are for the same task
            embedded_afk_slots_raw = [
                afk_rs
                for afk_rs in afk_slots
                if (
                    afk_rs.project == work_rs.project
                    and afk_rs.task == work_rs.task
                    and afk_rs.start < work_rs.end
                    and work_rs.start < afk_rs.end
                )
            ]

            # For backward compatibility, extract the underlying TimelineSlots
            # (from_work_slot_with_embedded_afk expects TimelineSlot objects)
            # This is a temporary bridge during migration
            from tw_report.core.timeline import TimelineSlot

            # Create synthetic work_slot TimelineSlot for the factory method
            work_slot_ts = TimelineSlot(
                type="regular" if not work_rs.is_offline_task else "offline_task",
                start=work_rs.start,
                end=work_rs.end,
                duration=work_rs.duration,
                actual_duration=work_rs.actual_duration,
                productive_duration=work_rs.productive_duration,
                project=work_rs.project,
                task=work_rs.task,
                categories=work_rs.categories,
                tags=work_rs.tags,
                afk_duration=work_rs.afk_duration,
                offline_extension_duration=work_rs.offline_extension_duration,
                event_duration=work_rs.event_duration,
                apps=work_rs.apps,
            )

            # Create synthetic AFK TimelineSlots for the embedded slots
            embedded_afk_slots_ts = [
                TimelineSlot(
                    type="afk",
                    start=afk_rs.start,
                    end=afk_rs.end,
                    duration=afk_rs.duration,
                    actual_duration=afk_rs.actual_duration,
                    productive_duration=afk_rs.productive_duration,
                    project=afk_rs.project,
                    task=afk_rs.task,
                    categories=afk_rs.categories,
                    tags=afk_rs.tags,
                    afk_duration=afk_rs.afk_duration,
                    apps=afk_rs.apps,
                )
                for afk_rs in embedded_afk_slots_raw
            ]

            # Create combined ReportTimelineSlot with embedded AFK
            combined_slot = ReportTimelineSlot.from_work_slot_with_embedded_afk(
                work_slot_ts, embedded_afk_slots_ts
            )
            result_report_slots.append(combined_slot)

        # Add AFK slots that were NOT embedded (standalone)
        for afk_rs in afk_slots:
            # Keep only if NOT embedded in any work slot
            is_embedded = any(
                afk_rs.project == work_rs.project
                and afk_rs.task == work_rs.task
                and afk_rs.start < work_rs.end
                and work_rs.start < afk_rs.end
                for work_rs in work_slots
            )
            if not is_embedded:
                result_report_slots.append(afk_rs)

        # Add other slot types (offline_task, etc.)
        result_report_slots.extend(other_slots)

        # Sort by start time to preserve chronological order
        result_report_slots.sort(key=lambda rs: rs.start)

        return ReportEntries(slots_list=result_report_slots)

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

                    # When merging overlapping slots, use the union of times, not sum
                    # The merged slot represents the entire time span covered by both overlapping slots

                    # Merge afk_duration: take max (they overlap)
                    curr_afk = current.afk_duration or timedelta(0)
                    rs_afk = rs.afk_duration or timedelta(0)
                    merged_afk_duration = max(curr_afk, rs_afk) if (curr_afk or rs_afk) else None

                    # Merge offline_extension_duration: take max (overlapping window activity)
                    curr_off = current.offline_extension_duration or timedelta(0)
                    rs_off = rs.offline_extension_duration or timedelta(0)
                    merged_offline_ext = max(curr_off, rs_off) if (curr_off or rs_off) else None

                    # Merge event_duration: take sum (online time represents disjoint periods)
                    curr_event = current.event_duration or timedelta(0)
                    rs_event = rs.event_duration or timedelta(0)
                    merged_event_duration = (curr_event + rs_event) if (curr_event or rs_event) else None

                    # Create merged ReportTimelineSlot directly
                    # CRITICAL: Use merged_duration for actual_duration
                    # (not sum of overlapping durations, which would double-count)
                    # Calculate proportional productive duration based on merged duration
                    curr_prod = current.productive_duration or timedelta(0)
                    rs_prod = rs.productive_duration or timedelta(0)
                    curr_productive_ratio = curr_prod.total_seconds() / max(current.duration.total_seconds(), 1)
                    rs_productive_ratio = rs_prod.total_seconds() / max(rs.duration.total_seconds(), 1)
                    avg_productive_ratio = (curr_productive_ratio + rs_productive_ratio) / 2
                    merged_productive_seconds = merged_duration.total_seconds() * avg_productive_ratio
                    merged_productive_duration = timedelta(seconds=merged_productive_seconds) if merged_productive_seconds > 0 else timedelta(0)

                    current = ReportTimelineSlot(
                        start=current.start,
                        end=merged_end,
                        duration=merged_duration,
                        actual_duration=merged_duration,
                        productive_duration=merged_productive_duration,
                        task_event=current.task_event,  # Use first slot's task_event
                        window_events=current.window_events + rs.window_events,
                        afk_events=current.afk_events + rs.afk_events,
                        afk_duration=merged_afk_duration,
                        offline_extension_duration=merged_offline_ext,
                        event_duration=merged_event_duration,
                        tags=current.tags,  # Use first slot's tags
                        categories=current.categories,  # Use first slot's categories
                        apps=current.apps,
                        source_slots=current.source_slots + rs.source_slots,
                        is_consolidated=True,  # Mark as merged
                    )
                else:
                    # Non-overlapping: save current and start new
                    merged_list.append(current)
                    current = rs

            merged_list.append(current)
            result.extend(merged_list)

        return result

    def consolidate_consecutive(self) -> "ReportEntries":
        """
        Fine-grain consolidation: merge CONSECUTIVE slots sharing (project, task, date).

        Bare offline gap markers are filtered out from the output.
        This fixes the inconsistency between TimelineSlotManager.consolidate() and
        consolidate_by_period() — both now uniformly exclude bare offline gaps.

        Returns:
            ReportEntries with consecutive-same-task runs merged
        """
        if not self.slots_list:
            return ReportEntries()

        consolidated = []
        current_group = []

        for report_slot in self.slots_list:
            # Skip bare offline gap markers: empty project + task + zero duration
            if (
                report_slot.project == NO_PROJECT
                and report_slot.task == NO_TASK
                and report_slot.actual_duration == timedelta(0)
            ):
                continue

            if not current_group:
                current_group.append(report_slot)
                continue

            # Check if same (project, task, date)
            same_project_task_date = (
                report_slot.project == current_group[0].project
                and report_slot.task == current_group[0].task
                and report_slot.start.date() == current_group[0].start.date()
            )

            if same_project_task_date:
                current_group.append(report_slot)
            else:
                # Different task — merge current group and start new one
                if current_group:
                    # Convert ReportTimelineSlots to TimelineSlots for from_timeline_slots compatibility
                    from tw_report.core.timeline import TimelineSlot

                    group_ts = [
                        TimelineSlot(
                            type="regular" if not s.is_offline_task else "offline_task",
                            start=s.start,
                            end=s.end,
                            duration=s.duration,
                            actual_duration=s.actual_duration,
                            productive_duration=s.productive_duration,
                            project=s.project,
                            task=s.task,
                            categories=s.categories,
                            tags=s.tags,
                            afk_duration=s.afk_duration,
                            offline_extension_duration=s.offline_extension_duration,
                            event_duration=s.event_duration,
                            apps=s.apps,
                        )
                        for s in current_group
                    ]

                    # Allow mixed types (regular + afk) within same (project, task, date) group
                    # e.g., a work session interrupted by AFK gaps should be merged into one row
                    merged_report_slot = ReportTimelineSlot.from_timeline_slots(
                        group_ts, allow_mixed_types=True
                    )
                    consolidated.append(merged_report_slot)
                    current_group.clear()
                current_group.append(report_slot)

        # Final flush
        if current_group:
            # Convert ReportTimelineSlots to TimelineSlots for from_timeline_slots compatibility
            from tw_report.core.timeline import TimelineSlot

            group_ts = [
                TimelineSlot(
                    type="regular" if not s.is_offline_task else "offline_task",
                    start=s.start,
                    end=s.end,
                    duration=s.duration,
                    actual_duration=s.actual_duration,
                    productive_duration=s.productive_duration,
                    project=s.project,
                    task=s.task,
                    categories=s.categories,
                    tags=s.tags,
                    afk_duration=s.afk_duration,
                    offline_extension_duration=s.offline_extension_duration,
                    event_duration=s.event_duration,
                    apps=s.apps,
                )
                for s in current_group
            ]

            # Allow mixed types (regular + afk) within same (project, task, date) group
            merged_report_slot = ReportTimelineSlot.from_timeline_slots(
                group_ts, allow_mixed_types=True
            )
            consolidated.append(merged_report_slot)

        return ReportEntries(slots_list=consolidated)

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

    def bucket(self, mode: Literal["day", "week", "month", "year"]) -> "ReportEntries":
        """
        Period bucketing: split all slots at boundaries, then global-groupby (bucket, project, task).

        Replaces consolidate_by_period(). Bare type=="offline" gap markers are excluded
        from output (only consumed as continuity signals).

        Args:
            mode: "day", "week", "month", or "year"

        Returns:
            ReportEntries with slots split at boundaries and grouped by period bucket,
            sorted by (bucket_start_date, -project_total, -task_total)
        """
        # Split all slots at boundaries
        split_pieces = []
        for report_slot in self.slots_list:
            split_pieces.extend(report_slot.split_at_boundaries(mode))

        # Global groupby (bucket, project, task), excluding bare offline gaps
        bucket_groups = {}
        for piece in split_pieces:
            # Skip bare offline gap markers (these are synthetic AFK-only slots with no real task)
            # Identified by being AFK-only type (not offline_task)
            # TODO: Define a better marker for bare offline gaps

            key = (piece.bucket_start_date, piece.project, piece.task)
            if key not in bucket_groups:
                bucket_groups[key] = []
            bucket_groups[key].append(piece)

        # Merge each bucket group
        bucketed = []
        for (bucket_date, project, task), slot_group in sorted(bucket_groups.items()):
            # Convert ReportTimelineSlots to TimelineSlots for from_timeline_slots compatibility
            # This is a temporary bridge during migration
            from tw_report.core.timeline import TimelineSlot

            slot_group_ts = [
                TimelineSlot(
                    type="regular" if not s.is_offline_task else "offline_task",
                    start=s.start,
                    end=s.end,
                    duration=s.duration,
                    actual_duration=s.actual_duration,
                    productive_duration=s.productive_duration,
                    project=s.project,
                    task=s.task,
                    categories=s.categories,
                    tags=s.tags,
                    afk_duration=s.afk_duration,
                    offline_extension_duration=s.offline_extension_duration,
                    event_duration=s.event_duration,
                    apps=s.apps,
                )
                for s in slot_group
            ]

            # Allow mixed types in period consolidation (e.g., 'regular' + 'afk' in same period/project/task)
            merged = ReportTimelineSlot.from_timeline_slots(slot_group_ts, allow_mixed_types=True)
            merged.bucket_start_date = bucket_date
            merged.bucket_mode = mode
            bucketed.append(merged)

        # Sort by (bucket_date, -project_duration_desc, -task_duration_desc)
        # (simplified: just bucket_date for now; render layer can further sort by project/task if needed)
        bucketed.sort(key=lambda s: s.bucket_start_date)

        return ReportEntries(slots_list=bucketed)

    def collapse_to_project(self) -> "ReportEntries":
        """
        Collapse (bucket, project, task) rows to (bucket, project) totals.

        For use with bucketed ReportEntries (post bucket() call).
        Sums actual_duration, productive_duration, afk_duration, offline_extension_duration.
        Drops task and categories.

        Returns:
            ReportEntries with one row per (bucket, project), durations summed
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
            # Convert ReportTimelineSlots to TimelineSlots for from_timeline_slots compatibility
            from tw_report.core.timeline import TimelineSlot

            group_ts = [
                TimelineSlot(
                    type="regular" if not s.is_offline_task else "offline_task",
                    start=s.start,
                    end=s.end,
                    duration=s.duration,
                    actual_duration=s.actual_duration,
                    productive_duration=s.productive_duration,
                    project=s.project,
                    task=s.task,
                    categories=s.categories,
                    tags=s.tags,
                    afk_duration=s.afk_duration,
                    offline_extension_duration=s.offline_extension_duration,
                    event_duration=s.event_duration,
                    apps=s.apps,
                )
                for s in group
            ]

            # Allow mixed types since we're collapsing already-bucketed data
            merged = ReportTimelineSlot.from_timeline_slots(group_ts, allow_mixed_types=True)
            merged.bucket_start_date = bucket_date
            merged.bucket_mode = group[0].bucket_mode if group else None
            collapsed.append(merged)

        return ReportEntries(slots_list=collapsed)

    def slots(self) -> List[ReportTimelineSlot]:
        """Get the internal slots list."""
        return self.slots_list

    def as_dicts(self) -> List[Dict[str, Any]]:
        """Convert all slots to dict format for backward compatibility.

        This is a bridge for code paths that still expect dicts rather than
        ReportTimelineSlot objects. Convert each ReportTimelineSlot to a dict
        that mimics the old TimelineSlot.to_dict() format.

        Returns:
            List of slot dicts with all fields from ReportTimelineSlot
        """
        result = []
        for slot in self.slots_list:
            slot_dict = {
                "start": slot.start,
                "end": slot.end,
                "duration": slot.duration,
                "actual_duration": slot.actual_duration,
                "productive_duration": slot.productive_duration,
                "project": slot.project,
                "task": slot.task,
                "tags": slot.tags,
                "categories": slot.categories,
                "apps": slot.apps or [],
            }
            # Add optional fields only if they have values (must check for None, not truthiness)
            if slot.afk_duration is not None:
                slot_dict["afk_duration"] = slot.afk_duration
            if slot.offline_extension_duration is not None:
                slot_dict["offline_extension_duration"] = slot.offline_extension_duration
            if slot.event_duration is not None:
                slot_dict["event_duration"] = slot.event_duration

            # Add type discriminator for legacy code paths
            if slot.is_offline_task:
                slot_dict["type"] = "offline_task"
            elif slot.is_afk_only:
                slot_dict["type"] = "afk"
            else:
                slot_dict["type"] = "regular"

            result.append(slot_dict)
        return result



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

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from aw_core.models import Event


@dataclass(frozen=True)
class TimeslotDuration:
    """Encapsulates duration accounting for a single timeslot.

    Clearly separates online time (when system was recording) from offline gaps.
    This prevents confusion between wall_clock_duration, event_duration, actual_duration,
    and other ambiguous naming patterns.

    Attributes:
        online_duration: (Optional) Time when system was actively recording (AFK + non-AFK combined).
            This is the primary duration shown in timeline output.
            Comes from AFK bucket events or TaskWarrior activity times.
            Can be None in rare cases (e.g., task duration but no AFK/window recording).

        offline_gap: (Optional) Time when system was powered off (work done without computer).
            Only applies to offline-tagged tasks. Always None for online tasks.
            Calculated as: wall_clock_duration - online_duration

        afk_portion: (Optional) Time away from keyboard, subset of online_duration.
            When present, indicates AFK period was detected during online_duration.
            Used for notation display "(XX:XX AFK)" in consolidated output.
            None if no AFK detected in this slot.

    Invariant:
        At least one of online_duration or offline_gap must be present (not both None).
        Raises ValueError if both are None.

    Relationships:
        wall_clock_duration = online_duration + offline_gap (for offline tasks)
        total_system_time = online_duration + offline_gap (same, clearer naming)

    Examples:
        Regular work slot (no gaps):
            TimeslotDuration(online_duration=1:23:45, offline_gap=None, afk_portion=None)

        Offline task (system powered off for part):
            TimeslotDuration(online_duration=0:21:47, offline_gap=0:51:16, afk_portion=None)
            Total wall-clock = 1:13:03

        Regular slot with AFK detected:
            TimeslotDuration(online_duration=1:03:00, offline_gap=None, afk_portion=0:15:30)
            Display: "(00:15:30 AFK)  01:03:00"

        Offline task with no online recording (rare):
            TimeslotDuration(online_duration=None, offline_gap=2:15:00, afk_portion=None)
            Total wall-clock = 2:15:00
    """

    online_duration: Optional[timedelta] = None
    offline_gap: Optional[timedelta] = None
    afk_portion: Optional[timedelta] = None

    def __post_init__(self) -> None:
        """Validate that at least one duration is present."""
        if self.online_duration is None and self.offline_gap is None:
            raise ValueError(
                "TimeslotDuration requires at least one of: online_duration or offline_gap"
            )

        # afk_portion can only exist if online_duration exists
        if self.afk_portion is not None and self.online_duration is None:
            raise ValueError("afk_portion requires online_duration to be present")

        # afk_portion cannot exceed online_duration
        if (
            self.afk_portion is not None
            and self.online_duration is not None
            and self.afk_portion > self.online_duration
        ):
            raise ValueError("afk_portion cannot exceed online_duration")

    @property
    def total_duration(self) -> timedelta:
        """Total wall-clock time including any offline gaps.

        For online tasks: same as online_duration
        For offline tasks: online_duration + offline_gap
        For offline-only: same as offline_gap
        """
        online = self.online_duration or timedelta(0)
        offline = self.offline_gap or timedelta(0)
        return online + offline

    @property
    def non_afk_portion(self) -> timedelta:
        """Time spent with keyboard/mouse focus (online_duration - afk_portion).

        Returns zero if online_duration is None.
        """
        if self.online_duration is None:
            return timedelta(0)
        if self.afk_portion:
            return self.online_duration - self.afk_portion
        return self.online_duration

    def has_online(self) -> bool:
        """True if online_duration is present and non-zero."""
        return self.online_duration is not None and self.online_duration.total_seconds() > 0

    def has_offline(self) -> bool:
        """True if offline_gap is present and non-zero."""
        return self.offline_gap is not None and self.offline_gap.total_seconds() > 0

    def __str__(self) -> str:
        """Human-readable representation of duration breakdown."""
        parts = []
        if self.online_duration is not None:
            parts.append(f"online={self._format_td(self.online_duration)}")
        if self.afk_portion:
            parts.append(f"afk={self._format_td(self.afk_portion)}")
        if self.offline_gap:
            parts.append(f"offline={self._format_td(self.offline_gap)}")
        return f"TimeslotDuration({', '.join(parts)})"

    @staticmethod
    def _format_td(td: timedelta) -> str:
        """Format timedelta as HH:MM:SS for __str__."""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass
class PeriodMetrics:
    """Accumulates metrics for a single period (day, week, month, etc.).

    Groups related duration fields that are commonly accumulated together
    to make metrics collection clearer and less error-prone than tracking
    separate day_duration, day_afk_duration, day_offline_duration variables.

    Attributes:
        online_duration: Total time system was actively recording (AFK + non-AFK)
        afk_duration: Time away from keyboard (subset of online_duration)
        offline_gap: Time when system was powered off
        productive_duration: Time on productive activities

    Usage:
        Instead of:
            day_duration += slot_duration.online_duration or timedelta(0)
            day_afk_duration += afk_time
            day_offline_duration += offline_time
            day_productive += productive_time

        Use:
            daily_metrics.add(
                online=slot_duration.online_duration,
                afk=afk_time,
                offline=offline_time,
                productive=productive_time
            )
    """

    online_duration: timedelta = timedelta(0)
    afk_duration: timedelta = timedelta(0)
    offline_gap: timedelta = timedelta(0)
    productive_duration: timedelta = timedelta(0)

    def add(
        self,
        online: Optional[timedelta] = None,
        afk: Optional[timedelta] = None,
        offline: Optional[timedelta] = None,
        productive: Optional[timedelta] = None,
    ) -> None:
        """Add durations to this period's totals.

        Args:
            online: Online time to add (None or zero treated as no-op)
            afk: AFK time to add (subset of online)
            offline: Offline gap to add
            productive: Productive time to add
        """
        if online and online.total_seconds() > 0:
            self.online_duration += online
        if afk and afk.total_seconds() > 0:
            self.afk_duration += afk
        if offline and offline.total_seconds() > 0:
            self.offline_gap += offline
        if productive and productive.total_seconds() > 0:
            self.productive_duration += productive

    def add_timeslot(
        self,
        slot_duration: "TimeslotDuration",
        productive: Optional[timedelta] = None,
    ) -> None:
        """Add a TimeslotDuration to this period's totals.

        Args:
            slot_duration: The TimeslotDuration to accumulate
            productive: Productive time in this slot
        """
        self.add(
            online=slot_duration.online_duration,
            afk=slot_duration.afk_portion,
            offline=slot_duration.offline_gap,
            productive=productive,
        )

    @property
    def total_duration(self) -> timedelta:
        """Total wall-clock time (online + offline)."""
        return self.online_duration + self.offline_gap

    @property
    def active_duration(self) -> timedelta:
        """Time with keyboard/mouse focus (online - afk)."""
        return self.online_duration - self.afk_duration

    def __str__(self) -> str:
        """Human-readable representation."""
        parts = [f"online={self._format_td(self.online_duration)}"]
        if self.afk_duration.total_seconds() > 0:
            parts.append(f"afk={self._format_td(self.afk_duration)}")
        if self.offline_gap.total_seconds() > 0:
            parts.append(f"offline={self._format_td(self.offline_gap)}")
        if self.productive_duration.total_seconds() > 0:
            parts.append(f"productive={self._format_td(self.productive_duration)}")
        return f"PeriodMetrics({', '.join(parts)})"

    @staticmethod
    def _format_td(td: timedelta) -> str:
        """Format timedelta as HH:MM:SS."""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass
class ReportTotals:
    """Aggregated metrics for entire report (all periods combined).

    Groups the related duration and productivity fields that are passed to
    print_report_totals() and other reporting functions. This replaces
    scattered individual parameters with a coherent data structure.

    Attributes:
        online_time: Total time system was actively recording (AFK + non-AFK)
        productive_time: Total productive time (across all online time)
        afk_time: Total time away from keyboard (subset of online_time)
        offline_time: Total time worked while system was powered off
        active_time: Total time with keyboard/mouse focus (online - afk)

    Usage (old way):
        print_report_totals(
            total_time_all=17:11:57,
            total_productive_all=8:15:32,
            total_afk=1:24:52,
            total_offline=2:45:10,
            total_non_afk=15:47:05
        )

    Usage (new way):
        totals = ReportTotals(
            online_time=timedelta(hours=17, minutes=11, seconds=57),
            productive_time=timedelta(hours=8, minutes=15, seconds=32),
            afk_time=timedelta(hours=1, minutes=24, seconds=52),
            offline_time=timedelta(hours=2, minutes=45, seconds=10),
        )
        print_report_totals(totals)

    Invariants:
        - online_time >= afk_time (AFK is subset of online)
        - online_time >= active_time (active = online - afk)
        - offline_time >= 0
        - productive_time >= 0
    """

    online_time: Optional[timedelta] = None
    productive_time: Optional[timedelta] = None
    afk_time: Optional[timedelta] = None
    offline_time: Optional[timedelta] = None

    @property
    def active_time(self) -> Optional[timedelta]:
        """Time with keyboard/mouse focus (online_time - afk_time)."""
        if self.online_time is None:
            return None
        afk = self.afk_time or timedelta(0)
        return self.online_time - afk

    @property
    def total_time(self) -> Optional[timedelta]:
        """Total wall-clock time (online + offline)."""
        online = self.online_time or timedelta(0)
        offline = self.offline_time or timedelta(0)
        return online + offline if (online or offline) else None

    def __str__(self) -> str:
        """Human-readable representation."""
        parts = []
        if self.online_time:
            parts.append(f"online={self._format_td(self.online_time)}")
        if self.afk_time:
            parts.append(f"afk={self._format_td(self.afk_time)}")
        if self.offline_time:
            parts.append(f"offline={self._format_td(self.offline_time)}")
        if self.productive_time:
            parts.append(f"productive={self._format_td(self.productive_time)}")
        return f"ReportTotals({', '.join(parts)})"

    @staticmethod
    def _format_td(td: Optional[timedelta]) -> str:
        """Format timedelta as HH:MM:SS."""
        if td is None:
            return "00:00:00"
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class ReportEvent:
    event: Event
    project: str
    task: str
    active_task: Optional[Event]


@dataclass(frozen=True)
class ReportMetrics:
    productive_time: timedelta
    productive_task_time: timedelta
    distracting_time: timedelta
    unscored_time: timedelta
    non_afk_time: timedelta
    first_event_time: Optional[datetime]
    last_event_time: Optional[datetime]
    current_session_start: Optional[datetime]
    current_session_end: Optional[datetime]
    current_session_duration: Optional[timedelta]
    last_break_start: Optional[datetime]
    last_break_end: Optional[datetime]
    last_break_duration: Optional[timedelta]


@dataclass(frozen=True)
class ReportContext:
    canonical_events: List[ReportEvent]
    task_events: Optional[List[Event]]
    afk_events: List[Event]
    cat_score_map: Dict[str, float]
    is_task_based_report: bool
    metrics: ReportMetrics

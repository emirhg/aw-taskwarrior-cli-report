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
        online_duration: Time when system was actively recording (AFK + non-AFK combined).
            This is the primary duration shown in timeline output.
            Comes from AFK bucket events or TaskWarrior activity times.

        offline_gap: Time when system was powered off (work done without computer).
            Only applies to offline-tagged tasks. Always None for online tasks.
            Calculated as: wall_clock_duration - online_duration

        afk_portion: (Optional) Time away from keyboard, subset of online_duration.
            When present, indicates AFK period was detected during online_duration.
            Used for notation display "(XX:XX AFK)" in consolidated output.
            None if no AFK detected in this slot.

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
    """

    online_duration: timedelta
    offline_gap: Optional[timedelta] = None
    afk_portion: Optional[timedelta] = None

    @property
    def total_duration(self) -> timedelta:
        """Total wall-clock time including any offline gaps.

        For online tasks: same as online_duration
        For offline tasks: online_duration + offline_gap
        """
        return self.online_duration + (self.offline_gap or timedelta(0))

    @property
    def non_afk_portion(self) -> timedelta:
        """Time spent with keyboard/mouse focus (online_duration - afk_portion)."""
        if self.afk_portion:
            return self.online_duration - self.afk_portion
        return self.online_duration

    def __str__(self) -> str:
        """Human-readable representation of duration breakdown."""
        parts = [f"online={self._format_td(self.online_duration)}"]
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

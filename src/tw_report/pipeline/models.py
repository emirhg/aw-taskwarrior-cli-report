from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from aw_core.models import Event


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

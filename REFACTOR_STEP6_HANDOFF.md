# Step 6-11 Handoff: Merge TimelineSlot into ReportTimelineSlot

## Current Status ✅ Step 6.1 COMPLETE

**Completed**: Steps 1-5 + Step 6.1 (all committed, 37/67 tests passing)

1. ✅ Fixed broken test imports (ReportTimeline → ReportEntries)
2. ✅ Created core/aw_events.py with typed Event subclasses (32 tests)
3. ✅ Created structural predicate tests (9 tests, spec-first validation)
4. ✅ Threaded event_cls through event fetching
5. ✅ Replaced duck-typing with typed properties in task_matching.py and categories.py
6. ✅ **Step 6.1**: Merged TimelineSlot into ReportTimelineSlot class definition

**Clean commit state**: `git log --oneline | head -5`
```
ec7f3fa refactor: Step 6.1 — Merge TimelineSlot into ReportTimelineSlot class definition
[earlier steps]
```

**Test Status After Step 6.1:**
- ✅ 9 structural predicate tests (safety net) — 9/9 passing
- ✅ 32 aw_events unit tests — passing
- ✅ 1 report_slot construction test — passing
- ❌ 30 tests failing (mostly test_timeline.py using old TimelineSlot, ReportEntries methods need fixing)

---

## Step 6.1 COMPLETED ✅

All class-level structural changes are done:
- ✅ Class definition merged (direct fields, no more `slot=` wrapping)
- ✅ Properties added (project, task, is_offline_task, is_afk_only)
- ✅ Factory methods updated (from_timeline_slot, from_timeline_slots, from_work_slot_with_embedded_afk, split_at_boundaries)
- ✅ Backward-compat methods deleted (to_dict, to_timeline_slot, get_display_columns)
- ✅ Structural predicate tests passing (9/9)

**What broke:** 30 tests in test_report_slot.py and test_timeline.py need updates because:
1. Tests using `.type` property need to use `.is_offline_task` / `.is_afk_only` instead
2. Tests checking `.slot` attribute no longer have it
3. Tests using `.embedded_afk_slots` need updating (now just tracking via afk_events)
4. ReportEntries methods (`from_timeline`, `combine_work_with_embedded_afk`, etc.) still reference old structure

---

## Step 6.2-6.6: Complete factory methods and test migration (IN PROGRESS)

This is the structural core. **All downstream refactoring depends on this step being completed correctly.**

### 6.1: Update ReportTimelineSlot class definition

**File**: `src/tw_report/core/report_slot.py` (around line 235-380)

**Replace the class definition** with this new merged structure:

```python
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
```

### Immediate Next Steps (Resume from this point)

**Priority 1 (Blocking everything):**
1. Fix ReportEntries.from_timeline() — update to construct ReportTimelineSlot directly from Timeline
2. Fix ReportEntries.combine_work_with_embedded_afk() — still references embedded_afk_slots
3. Update test_report_slot.py assertions that check `.type` → use predicates
4. Update test_report_slot.py assertions that check `.embedded_afk_slots` → check `.afk_events` instead
5. Delete test_to_dict() and test_to_timeline_slot() (methods don't exist anymore)

**Priority 2 (Unblocks timeline tests):**
6. Decide: Keep Timeline/TimelineSlot for internal use, or delete it?
   - Currently test_timeline.py tests only TimelineSlot/Timeline (not ReportTimelineSlot)
   - Option A: Leave TimelineSlot/Timeline alone for now, ReportTimelineSlot is the new model
   - Option B: Delete TimelineSlot/Timeline since ReportTimelineSlot replaces it
   - **Recommendation**: Option A (keep both for now, easier migration path)

**Priority 3 (Fixes remaining 30 test failures):**
7. Update test_timeline.py and test_report_slot.py to use new predicate structure
8. Search for `.type ==` checks in tests → replace with predicates
9. Search for `.embedded_afk_slots` → replace with field access or comments explaining the change

### 6.2: Update factory methods (COMPLETED IN CODE, needs test fixes)

**Key changes**:
1. `from_timeline_slot(slot: TimelineSlot)` → Delete (no longer needed; `Timeline.to_report_timeline` just builds list directly)
2. `from_timeline_slots()` → Replace entire implementation
   - Remove line 474-477 that builds `TimelineSlot`
   - Instead, construct `ReportTimelineSlot` directly at line 474+
   - Replace `type=group[0].type` with structural predicates
   - Replace `project=group[0].project, task=group[0].task` with `task_event=group[0].task_event`
   - Keep: `start`, `end`, `duration`, `actual_duration`, `productive_duration` (unchanged)
   - Add: `afk_events=[]`, `window_events=[]` (empty for merged slots)
   - Change: `embedded_afk_slots=afk_slots` → Delete (no longer exists)

### 6.3: Update other methods that reference old fields

Search for and replace:
- `.type ==` checks → Use `.is_offline_task` / `.is_afk_only` properties
- `.project` reads → Now a property (already works)
- `.task` reads → Now a property (already works)
- `.slot.X` → Direct `self.X` (slots are now flat)
- `.embedded_afk_slots` → `.afk_events`
- `["type"]` → Use predicates instead

### 6.4: Delete old methods

- `get_display_columns()` at line 322 (dead code, not called anywhere)
- Delete the old delegating properties (type, start, end, etc.) — they're now actual fields

### 6.5: Update Timeline class

**File**: `src/tw_report/core/timeline.py`

1. Delete `TimelineSlot` class (lines 32-211)
2. Update `Timeline.to_report_timeline()` to return `ReportEntries.from_timeline(self)`
3. Rename methods if needed:
   - `get_slots_by_type()` → Delete (test-only, zero production callers)
   - Update tests to use `.is_afk_only` / `.is_offline_task` instead

### 6.6: Critical validation

**Run tests immediately after each sub-step**:
```bash
pytest tests/unit/test_slot_structural_predicates.py -xvs  # Should pass
pytest tests/unit/test_aw_events.py -q  # Should pass
pytest tests/test_report_slot.py -q  # Will fail initially; fix test constructions
pytest tests/test_timeline.py -q  # Will fail initially; fix test constructions
```

**Use structural predicate tests as the safety net** — they validate that `is_offline_task` and `is_afk_only` correctly classify all real production cases.

---

## Subsequent Steps (7-11)

Once Step 6 is solid and tests pass:

### Step 7: Update core/offline.py
- Change `OfflineTaskProcessor.get_synthetic_slot()` to return `ReportTimelineSlot` directly
- Replace duplicated project/task extraction with `event.project`/`.task` calls

### Step 8: Update pipeline/generation.py
- Fix `_merge_overlapping_events()` line 54: `type(current)(...)` instead of `Event(...)`
- Update `generate_gap_entries()` to return `List[ReportTimelineSlot]`
- Update `generate_timeline_data()` to construct `ReportTimelineSlot` at final step

### Step 9: Update pipeline/timeline_render.py (largest change)
- Change all function signatures from `List[Dict]` to `List[ReportTimelineSlot]`
- Replace `.get("type")` checks with `.is_afk_only` / `.is_offline_task`
- Replace `.get("project", NO_PROJECT)` with `.project` (property handles fallback)
- Delete `slot_with_name` workaround (line ~1009)
- Consolidate `DisplayColumns` (delete dead `get_display_columns()`, update `from_slot_dict()`)

### Step 10: Update cli/main.py
- Thread `event_cls=` through all `get_events()` calls
- Drop `TimelineSlot.from_dict()` round-trips
- Guard `rep.event.offline_extension_duration = ...` with `isinstance(rep.event, WindowEvent)`

### Step 11: Delete dead code
- Remove `TimelineSlotManager` class from `core/consolidation.py`
- Remove `consolidate_by_period()` function
- Remove `print_period_consolidated_report()` from `pipeline/timeline_render.py`
- Delete associated test files

---

## Imports to Add

At the top of `src/tw_report/core/report_slot.py`, add:

```python
from typing import TYPE_CHECKING, ...
from tw_report.core.filtering import NO_PROJECT, NO_TASK

if TYPE_CHECKING:
    from tw_report.core.aw_events import WindowEvent, AFKEvent, TaskWarriorEvent
```

---

## Testing Strategy

1. **After class definition**: `pytest tests/unit/test_slot_structural_predicates.py` — These 9 tests are your regression gate
2. **After factory methods**: `pytest tests/test_report_slot.py -k "test_from"` — Tests slot construction
3. **After Timeline updates**: `pytest tests/test_timeline.py` — Basic timeline operations
4. **After each downstream step**: Run relevant test module to catch regressions early

**Gold test**: `pytest tests/unit/ -q` should show 41/41 passing after Step 6 is complete.

---

## Risk Management

**Highest risk in Step 6**:
- Structural predicates: `is_offline_task` and `is_afk_only` must correctly classify all slots
- **Mitigation**: Run structural predicate tests after each method update
- **Validation**: Manual inspection of a few real slot instances from each producer

**Medium risk**:
- Factory methods: complex merge logic with many durations
- **Mitigation**: Unit tests already cover most cases; add prints if needed to debug

**Lower risk**:
- Property delegations: simple field reads
- **Mitigation**: Search-replace can handle most of these

---

## Implementation Notes

- **Do not delete `slot: TimelineSlot` field prematurely** — leave it until all methods are updated
- **Keep imports current**: Use `from_timeline_slots()` signatures to guide field names
- **Test incrementally**: Each sub-step should pass its tests before moving to the next
- **Commit between sub-steps**: Each 6.1, 6.2, 6.3, etc. should be a separate commit
- **Use structural predicates liberally**: Every branch that checks `.type` should use a predicate

---

## Files to Modify in Step 6

1. **src/tw_report/core/report_slot.py** — ReportTimelineSlot class + methods
2. **src/tw_report/core/timeline.py** — Delete TimelineSlot, update Timeline
3. **tests/test_report_slot.py** — Fix ~30-40 test constructions
4. **tests/test_timeline.py** — Fix ~20 test constructions

**Total estimated changes**: ~1000 lines (merging two classes + updating all call sites)

---

## Checkpoints for Resume

- After 6.1 (class def): Syntax should be correct but methods will fail
- After 6.2 (factories): Construction and merge should work
- After 6.3 (method updates): Most internal logic should compile
- After 6.4-6.5 (cleanup + Timeline): Old class removed, tests should pass

Each checkpoint is a natural breakpoint to stop, commit, and resume later.

# CLAUDE.md — tw-report Project Guide

This file provides project-specific instructions for Claude Code and related agents working on **tw-report**, a sophisticated timesheet report generator that correlates ActivityWatch activity with Taskwarrior tasks.

## Getting Started

1. **Project Overview**: Read `README.md` for the full feature set, architecture, and report types.
2. **Code Navigation**: Use `index.txt` as a quick reference guide to locate files and understand structure.
3. **Architecture Details**: See `docs/ARCHITECTURE.md` for the comprehensive design document.
4. **Period Consolidation**: See `docs/PERIOD_CONSOLIDATION.md` for the day/week/month/year consolidation feature.
5. **Current Session**: Check memory at `~/.claude/projects/-home-emirhg-Desktop-ianua-work-report/memory/MEMORY.md` for ongoing work and known issues.

## Project Structure

```
tw-report/
├── src/tw_report/                 # Main package (src-layout)
│   ├── cli/                        # CLI entry point (args.py, main.py)
│   ├── core/                       # Core business logic (consolidation, filtering, period, timeline)
│   ├── pipeline/                   # Data processing (generation, presenters, timeline_render, report_render)
│   └── utils/                      # Formatting, utilities
├── tests/                          # Unit and integration tests
│   ├── unit/                       # Unit tests
│   └── test_*.py                   # Root-level integration/manual tests
├── docs/                           # Architecture, features, design docs
├── README.md                       # Main documentation
├── index.txt                       # File/feature navigation guide
├── pyproject.toml                  # Package metadata, test config
└── CLAUDE.md                       # This file
```

## Key Concepts

### Core Data Model

The tool correlates two data sources:

- **ActivityWatch**: Window events (app, title, focus time), AFK periods
- **Taskwarrior**: Task events (project, task, duration, tags)

**Flow**: Raw events → **canonical_events** (temporal overlap correlation) → **metrics** (aggregation) → **reports** (hierarchical or timeline rendering)

### Consolidation Modes (Recent Feature)

Four new flags control aggregation granularity:

- `--consolidate-day` — One line per (day, project) with total duration
- `--consolidate-week` — ISO week (Mon-Sun) aggregation
- `--consolidate-month` — Calendar month aggregation  
- `--consolidate-year` — Calendar year aggregation

These flags **imply `--timesheet`** and auto-default to matching period windows (e.g., `--consolidate-week` defaults to `:week`).

**Detail Levels**: All consolidation modes respect `--detail-level` (1=project, 2+=task, 3+=categories).

See `docs/PERIOD_CONSOLIDATION.md` for complete feature documentation.

### Time Metric Definitions

The tool tracks three distinct time metrics with precise meanings:

- **Online Time** — Total time system was actively recording (AFK + non-AFK combined; from AFK bucket)
  - Includes: Keyboard/mouse idle periods (AFK) + focused work periods (non-AFK)
  - Excludes: Time when system was powered off (offline periods)
  - Formula: Sum of all AFK bucket events
  - Use case: Accounting for total system uptime during work session
  
- **Active Time** — Time with keyboard/mouse focus (non-AFK periods only)
  - Includes: Focused window activity, actual work time
  - Excludes: Idle time (AFK), offline time, gaps
  - Formula: Online time - AFK time
  - Use case: Measuring actual focused work duration
  
- **Offline Time** — Time worked while system was powered off (for offline-tagged tasks only)
  - Includes: TaskWarrior task duration when system was offline
  - Measured as: Wall-clock duration - online time from AFK bucket
  - Formula: `wall_clock_duration - event_duration` (where event_duration is from AFK bucket)
  - Use case: Tracking work done without computer (e.g., meetings, writing, thinking)

**Relationship**: `Total Day = Online Time + Offline Time`

## Development Workflows

### Adding a New Report Type or Mode

1. **CLI**: Add flag to `src/tw_report/cli/args.py`
2. **Pipeline**: Create render function in `src/tw_report/pipeline/timeline_render.py` or `hierarchical_render.py`
3. **Main dispatch**: Wire it in `src/tw_report/cli/main.py` (around line 399+)
4. **Tests**: Add tests in `tests/unit/test_rendering.py` or similar
5. **Docs**: Update `README.md` with example output

### Adding a Filter or Optimization

1. **Core logic**: Implement in `src/tw_report/core/` (e.g., `project_filtering.py`, `task_filtering.py`)
2. **Integration**: Wire into the event-fetch chain in `src/tw_report/cli/main.py` (around line 130+)
3. **Tests**: Unit tests in `tests/unit/`
4. **Docs**: Document in `README.md` or create a new `docs/FEATURE_NAME.md`

### Running Tests

```bash
# All unit tests
pytest tests/unit/ -q

# Specific test class or function
pytest tests/unit/test_consolidation.py::TestConsolidateByPeriod -xvs

# Integration tests (manual/slow)
pytest tests/test_timeline.py -xvs
```

### CLI Testing (Manual)

```bash
# Hierarchical report (default)
tw-report :week

# Timeline report
tw-report --timesheet :week

# Period consolidation with detail levels
tw-report --consolidate-month --detail-level 2 :year
tw-report --consolidate-week --detail-level 3 --project Climb :year
```

## Code Patterns

### Timeline Slot Grouping

The codebase groups slots at multiple granularities:

| Grouping | Location | Used By |
|----------|----------|---------|
| **(period, project, task)** | `consolidate_by_period()` | Period consolidation modes |
| **(date, project, task)** | `TimelineSlotManager.consolidate()` | `--consolidate` flag |
| **(date, project)** | `print_timeline_report()` rendering | Timeline display logic |

When modifying grouping behavior, check all three layers to ensure consistency.

### Detail Level Rendering

Detail levels control how much sub-row detail is shown:

- **Level 1**: Project only (no sub-rows)
- **Level 2**: Project + Task (no sub-rows)
- **Level 3+**: Categories, apps, titles (nested sub-rows via `_render_slot_detail()`)

See `src/tw_report/pipeline/timeline_render.py:174-211` for the `_render_slot_detail()` function that implements levels 3-5.

### Period Bucketing

New period-based features use consistent bucketing functions:

- **Day**: `date` (midnight to midnight)
- **Week**: ISO week Monday start (`date - timedelta(days=date.weekday())`)
- **Month**: First day of calendar month
- **Year**: January 1st

These match the period token definitions in `src/tw_report/core/period.py` (`:week`, `:month`, `:year` tokens).

## Filtering and Metrics Architecture (Session 2026-08-31)

### Critical Rule: Filter Before Calculating Metrics

**All metrics (Active Time, AFK, Offline) must be calculated from filtered data, not pre-calculated unfiltered context.**

When `--project`, `--task`, or other EventFilter arguments are used, the metrics displayed must match the entries displayed:

**Wrong** ❌ (used in sessions 2026-08-30):
```python
# This calculates metrics from ALL entries, then displays only filtered entries
afk_time = context.metrics.non_afk_time  # UNFILTERED pre-calculated value
display_entries = [e for e in all_entries if event_filter.should_include_entry(e)]
```

**Correct** ✅ (implemented in session 2026-08-31):
```python
# Filter first, then calculate metrics from filtered data
filtered_slots = [s for s in consolidated_slots if event_filter.should_include_entry(s)]
afk_time = compute_afk_offline_totals(filtered_slots)[0]  # Calculated from FILTERED slots
```

### Consolidation Pipeline (Main.py Flow)

The proper flow in `src/tw_report/cli/main.py` (lines ~1007-1114) is:

1. **Slot Generation** (unconditional, lines 1007-1005):
   - `generate_afk_and_offline_slots()` — Creates AFK slot objects
   - `convert_active_periods_to_slots()` — Creates active work slots
   - `generate_partitioned_task_slots()` — Creates task-based slots
   - Produces `final_dicts` (list of ReportTimelineSlot dicts)

2. **Period Grouping** (if using consolidation modes):
   - Group `final_dicts` by logical_date into `period_groups`
   - Call `report_entries.consolidate_by_task()` within each period
   - Produces `consolidated_slots` (deduplicated, period-consolidated)

3. **Apply EventFilter** (ALWAYS, before metrics):
   - `filtered_consolidated_slots = [s for s in consolidated_slots if event_filter.should_include_entry(...)]`
   - This is the ONLY correct data to calculate metrics from

4. **Calculate Metrics from Filtered Data**:
   - `slot_afk_time, slot_offline_time = compute_afk_offline_totals(filtered_consolidated_slots)`
   - `slot_active_time = sum(s.actual_duration for s in filtered_consolidated_slots)`
   - These are the ONLY correct values to display

5. **Render Reports**:
   - Timeline: Pass `consolidated_dicts` (pre-consolidated from main.py)
   - Hierarchical: Pass `report_data` (built from canonical_events) with `non_afk_time=slot_active_time`

### Two Report Data Models

**Timeline Report** (`src/tw_report/pipeline/timeline_render.py`):
- Receives pre-consolidated `consolidated_dicts` from main.py
- Uses slot-based rendering (one row per slot with breakdown columns)
- Metrics calculated once in main.py, passed into print_timeline_report()
- ✅ Correctly filters both display and metrics

**Hierarchical Report** (`src/tw_report/pipeline/report_render.py`):
- Receives `report_data` structure (aggregated by project hierarchy)
- Uses aggregation-based rendering (project tree with totals)
- Metrics calculated in main.py from filtered consolidated_slots
- ⚠️ **Known Issue**: Displays unfiltered `report_data` entries but uses filtered metrics
  - Timeline shows correct filtered counts AND filtered metrics
  - Hierarchical shows correct filtered metrics but unfiltered entry list
  - Architectural mismatch that requires filtering `report_data` itself (not yet implemented)

### Pattern: Calculating Metrics Correctly

When adding new metrics or report types, follow this pattern (from commits 65381e2, 3cf6de7):

```python
# 1. Consolidate slot data
period_groups = ...  # Group by period
consolidated_slots = [consolidate_group_by_task(group) for group in period_groups]

# 2. ALWAYS filter before calculating
filtered_slots = [s for s in consolidated_slots 
                  if event_filter.should_include_entry({'project': s.project, 
                                                        'task': s.task, 
                                                        'type': 'regular'})]

# 3. Calculate all metrics from FILTERED slots
from src.tw_report.pipeline.timeline_render import compute_afk_offline_totals
slot_afk_time, slot_offline_time = compute_afk_offline_totals(filtered_slots)
slot_active_time = sum(s.actual_duration or timedelta(0) for s in filtered_slots)

# 4. Never use context.metrics.non_afk_time or other pre-calculated unfiltered values
# 5. Pass filtered values to report rendering
```

### Known Limitations & Future Work

1. **Hierarchical report filtering** (not yet implemented):
   - Currently displays unfiltered `report_data` while metrics are filtered
   - Fix would require filtering the `report_data` structure itself before rendering
   - Impact: User sees all entries in hierarchical view even when filtering by --project
   - Timeline view is correct (both display and metrics filtered)

2. **EventFilter scoping**:
   - Currently applies at the slot level (project/task matching)
   - App-level filtering (--app) not yet integrated into consolidation path
   - Works in non-consolidation mode but missing from --consolidate-{day,week,month,year}

## Recent Work & Current Status (Session 2026-09-01)

### Phase 2 & 3 Complete: Builder Consolidation + Breaks Column ✅
- **Test Status**: 492 unit tests passing, 0 failing (all tests green ✅)
- **Phase 2 Completion**: Unified all slot construction into single sweep-line builder
  - Deleted 4253 LOC of dead code (5 generators, OfflineTaskProcessor, legacy tests)
  - Guaranteed non-overlapping slots at construction time
  - Fixed overlapping slots bug where reported time exceeded wall-clock time
  - Commits: 2fc4d30 (massive cleanup), 9d6e75f, f76d09c (builder integration), ab350b9, 982b7a4
- **Phase 3 Completion**: Added Breaks Column feature with TDD approach
  - 21 TDD tests created before implementation (all passing ✅)
  - Breaks display gap durations (HH:MM:SS) in leftmost column
  - Integrated with header rendering and gap detection logic
  - Commit: 8661061, 982b7a4
- **Test Suite**: Fixed 2 pre-existing failures in test_task_filtering.py (commit a5afd97)
  - Root cause: Test data using wrong field names ("title" vs "task")
  - Result: All 492 tests now passing

### Key Learnings & Architectural Decisions

1. **Slot Generation Runs Unconditionally** (main.py, lines ~1007-1005)
   - Originally gated inside `if grouping_mode in ["day","week","month","year"]:`
   - Now runs for both timeline and hierarchical paths
   - Enables consistent metrics calculation across all report types
   - No performance impact: no new data fetches, only in-memory interval math

2. **EventFilter Must Precede Metrics** (critical pattern)
   - Session 2026-08-30 bug: metrics calculated from unfiltered `context.metrics` while display was filtered
   - Example: `--project Ecosistema` showed active time 50:11:23 (unfiltered) with only ~20 hours of entries visible
   - Fix: Calculate `slot_active_time` from `filtered_consolidated_slots` instead of pre-calculated context
   - Result: Metrics now match displayed entries exactly

3. **Two Report Models Have Different Display Paths**
   - Timeline uses `consolidated_dicts` (pre-consolidated from main.py) — filters both display and metrics ✅
   - Hierarchical uses `report_data` (aggregated by project) — displays unfiltered entries with filtered metrics ⚠️
   - Architectural issue remains open (hierarchical filtering not yet implemented)

### Completed Major Features & Optimizations

#### Timeline Gap Detection & Visual Separation (2026-07-23)
- Blank lines appear between work sessions with gaps > 5 minutes
- Improves readability by visually separating work sessions from breaks/shutdowns
- Configurable threshold (default: 5 minutes)

#### Timeline Duplicate Slot Deduplication (2026-07-23)
- Handles overlapping ActivityWatch `not-afk` events (window recovery)
- Merges overlapping work slots via `_merge_overlapping_work_slots()` in `report_slot.py`

#### AFK False-Positive Detection (2026-07-28, Phases 1-3 Complete)
- Detects when system was offline but AFK continued reporting
- Splits AFK into offline + online portions at first window event
- All 14 tests passing, ready for end-to-end verification

### Performance Optimization: OFFLINE Window Event Fetching (2026-07-22)
- **10x speedup** for `--task <uuid> --timesheet :all` queries (95s → 10s)
- Fixed bottleneck where OFFLINE task reconciliation fetched entire period windows (186K events)
- Now uses time-range optimization to fetch only windows overlapping task events
- Commit: 06075fb

### Phase 5: Timeline Rendering Restoration (2026-07-02)
- Restored broken Phase 5 timeline rendering from commit 69aeca3
- Fixed metrics calculation (AFK, project tracking, focus time)
- All 288 tests passing, 6 bonus xpassed fixes

### Period-Level Consolidation Modes (2026-07-07)
- Added `--consolidate-day/week/month/year` flags
- Order-independent dict-keyed grouping (unlike the fine-grain `--consolidate`)
- Auto-default period windows based on consolidation mode
- Flags imply `--timesheet` automatically
- Full `--detail-level` support (1-5)
- Integration with EventFilter (respects `--exclude-non-project`, etc.)
- 8 comprehensive unit tests

## Debugging Utilities

Debug scripts exist in the project root:

- `debug_profile.py` — Profile time/memory for slow commands
- `debug_full_pipeline.py` — Trace the full event pipeline
- `debug_uuid_mismatch.py` — Investigate UUID correlation issues

Run with: `python debug_*.py`

## Git Workflow

- **Feature branches**: Each feature gets a dedicated worktree (`git worktree add`)
- **Task lifecycle**: Tasks move from `planning/` → `ready/` → `in-progress/` → `completed/` on the documentation branch
- **Commit message format**: Include the phase/increment number; use co-authorship (`Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>`)
- **Merges**: After implementation, document agent creates a merge-ready commit, then implementer merges to main

## Testing & Verification

### Unit Tests
- `tests/unit/test_consolidation.py` — Consolidation logic (61 tests)
- `tests/unit/test_args.py` — CLI argument parsing
- `tests/unit/test_filtering.py` — Event filtering and auto-detection
- Other `test_*.py` — Component-specific tests

### Integration Tests (Slow, Manual)
- `tests/test_timeline.py` — Full timeline rendering pipeline
- `tests/test_consolidation_migration.py` — Data transformation correctness

## Known Limitations & Workarounds

1. **No app-level detail in consolidation modes**: Period consolidation shows categories/apps for detail_level >= 3 only; app filtering is still not as granular as the fine-grain `--consolidate` mode.

2. **Performance**: `--consolidate-month` with detail_level >= 3 and large datasets may be slow due to category merging overhead.

3. **UTC assumption**: All time handling assumes UTC; local time zones are not supported (by design, to match ActivityWatch behavior).

## References & Links

- **README.md** — Full feature documentation and examples
- **docs/ARCHITECTURE.md** — Phase 12 comprehensive architecture  
- **docs/PERIOD_CONSOLIDATION.md** — Period consolidation feature guide
- **docs/TASK_FILTER_AUTO_DETECTION.md** — Auto-detection for task IDs/UUIDs
- **docs/PROJECT_FILTER_RESOLUTION.md** — Project ID/UUID auto-detection
- **index.txt** — File-by-file navigation and hot spots

## Performance Optimization Patterns & Learnings

### How to Diagnose Performance Issues (Critical Workflow)

**Real example: 95-second command reduced to 10 seconds (10x speedup)**

When a command is unexpectedly slow:

1. **Add instrumentation at entry/exit of major functions** (use `time.perf_counter()`)
   - Don't just profile the entire command — you'll get time spent inside AW client initialization, network calls, etc.
   - Add timing around data fetching, processing stages, and rendering
   - This will immediately reveal where the 100+ seconds are actually going

2. **Follow the data, not your assumptions**
   - Initial belief: "AFK optimization isn't working, need to optimize rendering"
   - Reality after profiling: "generate_gap_entries is spending 2.8s on build_categories_from_window_events()"
   - Deeper profiling: "It's iterating through 186,279 window events 4 times"
   - Root cause: "OFFLINE task reconciliation is re-fetching the entire period's windows (1970-2026)"

3. **Look for secondary fetches that bypass optimizations**
   - Optimization 1 (AFK): Skip windows entirely for detail_level ≤ 2 ✅
   - Optimization 2 (Time-range): Fetch windows only for task time windows ✅
   - **Bug**: Code path for OFFLINE task reconciliation was re-fetching windows for entire period ✅ FOUND THE BUG
   - Lesson: When an optimization exists but doesn't deliver expected speedup, check if a secondary code path bypasses it

4. **Reuse existing patterns instead of creating new logic**
   - The fix didn't invent a new optimization strategy
   - It reused `_fetch_events_for_ranges(client, "window", task_time_ranges)` that already existed
   - Cost: 1 conditional check + reuse existing function = 6 lines changed
   - Result: 186K → 1.9K events (99% reduction), 95s → 10s

### Key Insights for Future Performance Work

**Time-range optimization is powerful for sparse data over large periods**
- When filtering by task UUID over `:year` or `:all` period:
  - Task events are sparse (71 events over 56 years)
  - Tasks occur in ~50 disjoint time windows
  - Fetching window events for entire period: 100K+ events
  - Fetching window events only for task windows: 1-5K events
  - This explains why the fix was 10x faster

**The unaccounted time is the real bottleneck**
- Initial profiling showed 3s accounted, 102s unaccounted
- The 3s was rendering (fast after optimization)
- The 102s was in data fetching (what we actually needed to optimize)
- Lesson: If profiling accounts for <50% of total time, the missing time is where the problem is

**Check all code paths when optimizations seem broken**
- AFK optimization path: working correctly (skip windows, use AFK)
- OFFLINE reconciliation path: re-fetching windows anyway, undoing the optimization
- These paths only intersect when OFFLINE-tagged tasks exist
- Lesson: Test optimizations with realistic data (this project has all tasks tagged "offline")

**Don't commit to algorithmic fixes too quickly**
- Initial hypothesis: "generate_gap_entries is doing something expensive with 30 AFK events"
- Truth: "generate_gap_entries is fine; it's iterating through 186K window events"
- The code was already fast — it just had too much data
- Lesson: Measure first, optimize data volume before optimizing algorithms

### When to Apply This Pattern

Use this approach when:
- User reports "command X is taking too long" (subjectively slow, no clear reason)
- Optimization exists but doesn't seem to help
- Large time periods (`:year`, `:all`) are slow but short periods (`:today`) are fast
- The slow command is rare/optional (not on critical path)

Don't use this for:
- Obvious algorithmic problems (O(n²) when O(n) is possible)
- Known bottlenecks (database queries, network roundtrips without batching)
- Regression diagnosis (use git bisect instead)

## When to Escalate

- **Agent type mismatch**: Use **implementer** for code changes, **planner** for design, **documentation** for task lifecycle moves, **version_control** for commit message reviews.
- **Multi-step refactors**: Use **workspace** agent for parallel-development (worktree) setup.
- **New report types**: Use **planner** to review design before **implementer** codes it.
- **Performance issues**: Add timing instrumentation first; follow the data to the real bottleneck; reuse existing patterns.

## Contact & Feedback

- **Issues/feedback**: See `README.md` "Known Issues" section or open a GitHub issue
- **Code review**: Use `/code-review ultra` for a thorough multi-agent review of complex changes
- **Documentation updates**: Update `index.txt` and `README.md` when adding features; keep them in sync

---

**Last Updated**: 2026-09-01 (Phase 2 & 3 COMPLETE: Builder consolidation + Breaks Column feature + All 492 tests passing)

**Maintainers**: Emir Herrera González (user) + Claude Haiku 4.5 (AI assistant)

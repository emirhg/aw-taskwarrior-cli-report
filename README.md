# TW-Report: Timesheet Report Generator

A sophisticated timesheet reporting tool that correlates ActivityWatch activity data with Taskwarrior tasks, generating hierarchical and timeline-based work reports with productivity metrics.

## Overview

`tw-report.py` bridges ActivityWatch (time tracking) and Taskwarrior (task management) to answer: **"Where did my time go, and what was I supposed to be working on?"**

The tool:
- Fetches window activity from ActivityWatch (what apps/windows were focused)
- Fetches task events from Taskwarrior (what tasks were active)
- Correlates them temporally to attribute window time to tasks
- Categorizes activities (Coding, Communication, etc.) via configurable regex rules
- Generates hierarchical or timeline reports showing time spent by project/task/category/app
- Calculates productivity scores based on category weights

## Architecture

### Data Flow

```
ActivityWatch buckets
    ├─ aw-watcher-window_{hostname}     → window events (app, title, duration)
    ├─ aw-watcher-afk_{hostname}        → AFK/not-afk periods (keyboard activity)
    └─ aw-watcher-taskwarrior_{hostname}→ task events (project, task, tags, duration)
                        ↓
        categorize_event()               → apply regex rules → $category field
                        ↓
        build_canonical_events()         → correlate window with task (temporal overlap)
                        ↓
        compute_metrics()                → aggregate productive/distracting/unscored time
                        ↓
    ┌───────────────────┴───────────────────┐
    ↓                                        ↓
aggregate_hierarchy()                 generate_timeline_data()
(Project > Task > Category > App)     (time slots, continuity grouping)
    ↓                                        ↓
HierarchicalReport.present()          TimelineReport.present()
```

### Key Modules

- **tw-report.py** — Main script; argument parsing, event fetching, orchestration
- **report_pipeline.py** — Core pipeline: canonical event building, hierarchy aggregation, metrics computation
- **report_models.py** — Data classes (ReportEvent, ReportMetrics, ReportContext)
- **report_presenters.py** — Report rendering (HierarchicalReport, TimelineReport)

## Features

### Report Types

#### Hierarchical Report (default)
Complete example with summary total:
```
▶ Project: No project assigned (19.71)                                  3:48:31
  • Task: No task assigned (19.71)                                      3:48:31

▶ Project: Ecosistema > Cultivo > Higuera (0.10)                        0:00:18
  • Task: Control de plagas (0.10)                                      0:00:18

▶ Project: Ecosistema > Tratamiento de residuos > Orgánicos (0.00)      0:18:44
  • Task: Disposición de restos de cocina (0.00)                        0:18:44

                                                Total Time: 0:19:02  [prod   0%]
================================================================================
```

**Key features:**
- Projects grouped by productivity score (descending)
- Nested hierarchy: Project > Task > Category > App > Title
- Parenthesized score shows total productivity points for that level
- Right-aligned summary total showing total tracked time and productivity percentage
- Excludes "No project assigned" sentinel from actual project tracking

#### Timeline Report (`--timesheet`)
Complete example with summary:
```
Period: :today (2026-06-18 to 2026-06-18)
Online Time: 5:31:22 (2026-06-18 12:00 to 2026-06-18 20:00)
  • Active Time: 4:02:13
  • AFK time: 1:29:09
  • Project Tracking: 7.9% (0:19:02)
  • Focus time: 1.6% (0:00:18)
...
Wk  Date       Day
W25 2026-06-18 Thu
       12:00-12:11  ▶ No project ▶▶ No task           0:10:27  [prod   0%]
      *12:11-12:16  ▶ No project ▶▶ No task           0:04:55  [   AFK   ]
       17:18-17:19  ▶ Ecosistema > Higuera ▶▶ Control de plagas 0:00:18  [prod 100%]
       17:20-17:38  ▶ Ecosistema > Orgánicos ▶▶ Disposición... 0:18:44  [prod   0%]
      *18:07-18:53  ▶ No project ▶▶ No task           0:46:13  [   AFK   ]

                                                Total Time: 5:29:26  [prod  36%]
================================================================================
```

**Key features:**
- Continuous time slots showing actual work sessions
- **Visual gap separation**: Blank lines appear between work sessions with gaps > 5 minutes
  - Helps distinguish work sessions from breaks, system shutdowns, or mode changes
  - Improves readability and makes work session boundaries clear
  - Threshold is configurable (default: 5 minutes)
- `[prod XX%]` shows productivity percentage for that slot
- `[AFK]` marks keyboard/mouse idle periods
- Right-aligned summary total (same format as hierarchical)
- Asterisk `*` marks AFK periods

### Time Period Selection

- `:today` — Current day
- `:yesterday` — Previous day
- `:week` — Current week (Mon-today)
- `:lastweek` — Previous week
- `:month` — Current month (1st-today)
- `:lastmonth` — Previous month
- `:year` — Current year (Jan 1-today)
- `:lastyear` — Previous calendar year
- `:all` — All history
- `2026-06-18` — Specific date
- `2026-06-18 2026-06-25` — Date range

### Filtering

- `--project PATTERN` — Show only matching projects (partial match, repeatable for OR)
- `--task PATTERN` — Filter by task name
- `--app PATTERN` — Filter by application
- `--exact` — Use exact (case-insensitive) matching instead of partial
- `--exclude-project NAME` — Exclude exact project match
- `--exclude-task NAME` — Exclude exact task
- `--exclude-app NAME` — Exclude exact app

### Categorization

Activities are categorized via regex rules from ActivityWatch settings:
```json
{
  "classes": [
    {
      "name": ["Coding"],
      "rule": {"type": "regex", "regex": "kitty|vim|code", "ignore_case": true},
      "data": {"score": 10.0}
    },
    {
      "name": ["Communication", "Chat"],
      "rule": {"type": "regex", "regex": "slack|discord|telegram"},
      "data": {"score": 3.0}
    }
  ]
}
```

**Productivity scores:**
- Positive: productive activities (Coding, Work, etc.)
- Negative: distracting (Social Media, Games, etc.)
- Zero: neutral (Writing, Research, etc.)

### Special Handling: OFFLINE Tasks

For Taskwarrior tasks tagged `+offline`:

**Problem**: Offline work (no window events recorded) would show zero or minimal duration because the tool normally measures time from window focus periods.

**Solution**: For OFFLINE tasks, sum all **valid "sandwiched" sessions** between consecutive task events, where each session is **Event1 + Gap + Event2**.

**How it works:**
- For each pair of consecutive task events of the same OFFLINE task
- Calculate: `Event1_duration + Gap + Event2_duration` = one session
- Only include sessions where the task is "sandwiched" (no other tasks active, no unassigned windows in the gap)
- Sum all valid sessions to get total offline duration
- Creates "Offline" category with zero productivity score
- Can be completely hidden with `--exclude-offline` flag

**Example output (consistent across both report types):**

Hierarchical report with `--detail-level 3` (default behavior):
```
▶ Project: Ecosistema > Tratamiento de residuos > Orgánicos (0.00)    0:18:44
  • Task: Disposición de restos de cocina (0.00)                      0:18:44
    - Offline (0.00)............................... 0:18:44

                                                Total Time: 0:19:02  [prod   0%]
```

Timeline report with `--timesheet --detail-level 3`:
```
       17:20-17:38  ▶ Ecosi... > Orgánicos ▶▶ Disposición de restos de cocina 0:18:44  [prod   0%]
                     - Offline                                           0:18:44
       17:38-18:04  ▶ No project assigned ▶▶ No task assigned 0:25:49  [prod  32%]
```

Both report types now display consistent category information. The "Offline" category appears in hierarchical reports at detail-level 2+ and in timeline reports at detail-level 3+.

With `--exclude-offline` flag (hides all OFFLINE tasks):
```
▶ Project: Ecosistema > Cultivo > Higuera (0.10)                      0:00:18
  • Task: Control de plagas (0.10)                                    0:00:18

                                                Total Time: 0:00:18  [prod 100%]
```

**Why this matters**: This allows tracking work done away from the computer (writing, reading, meetings) that doesn't generate window events but is recorded in Taskwarrior.

### Consolidation

`--consolidate` — Merge consecutive time slots of same task (even with AFK gaps unless `--ignore-offline`):
```
Before:  Task A 10:00-11:00  [AFK gap]  Task A 13:00-14:00
After:   Task A 10:00-14:00 (2:00 actual, 1:00 AFK break shown separately)
```

### Detail Levels

- **1**: Project only
- **2**: Project + Task (default)
- **3**: + Category
- **4**: + App
- **5**: + Window Title

## Installation

### From source (development)
```bash
git clone <repository>
cd work_report
pip install -e .
```

### After installation
```bash
# Console script (installed via pip install -e .)
tw-report :today

# Or use the development wrapper
./bin/tw-report :today
```

## Usage Examples

### Basic daily report
```bash
tw-report :today
```

### This week with timeline view
```bash
tw-report :week --timesheet
```

### Specific project, consolidated sessions
```bash
tw-report :today --project Ecosistema --timesheet --consolidate
```

### Exclude offline work from timeline
```bash
tw-report :today --timesheet --exclude-offline
```

### Deep dive on a specific task
```bash
tw-report :today --task "Control de plagas" --detail-level 5
```

### All Coding activity this month
```bash
tw-report :month --app kitty vim --sort-by-duration
```

## Dependencies

- **Python 3.8+** — Type hints, f-strings, TOML support
- **ActivityWatch** (`aw-client ≥0.5.15`, `aw-core ≥0.5.17`) — Event fetching and transformation
- **Taskwarrior** (via aw-watcher-taskwarrior) — Task events in ActivityWatch
- **tomli ≥1.1.0** (Python <3.11 only) — TOML config file parsing

## Configuration

### Config File (TOML)

User configuration files are loaded from (in order):
1. `$XDG_CONFIG_HOME/tw-report/config.toml` (if XDG_CONFIG_HOME is set)
2. `~/.config/tw-report/config.toml` (XDG Base Directory fallback)

If the config file doesn't exist, all settings fall back to defaults or CLI arguments.

**Example config file:**
```toml
# ~/.config/tw-report/config.toml
detail_level = 3
exclude_projects = ["Personal", "Test"]
terminal_width = 120
categories_file = "/custom/path/categories.json"
```

**Supported settings:**
- `detail_level` (1-5, default: 4) — Report detail level
- `exclude_projects` (list) — Projects to exclude from reports
- `exclude_tasks` (list) — Tasks to exclude from reports
- `exclude_apps` (list) — Apps to exclude from reports
- `terminal_width` (int) — Force terminal width for formatting
- `categories_file` (string) — Path to custom categories JSON file

**Precedence:** CLI arguments > config file > built-in defaults
- CLI arguments always override config file
- Config file settings override defaults
- Non-existent config file is silently ignored

### Categories File

Default location: `~/.config/activitywatch/aw-server/settings.json`

Override with `--categories /path/to/custom.json` or via config file:
```toml
categories_file = "/path/to/custom.json"
```

### Sorting Options

- `--sort-by-duration` — Descending by time spent
- `--sort-alphabetically` — A-Z (overrides score sorting)
- Default: By productivity score (highest first)

### Score Filtering

- `--min-score 5.0` — Hide activities below score 5
- `--max-score 0.0` — Hide productive activities (show only distracting/neutral)

## Output Metrics

### Report Header

- **Online Time** — Total time system was actively recording (AFK + non-AFK combined; excludes periods when system was powered off)
- **Active Time** — Total non-AFK time with window focus (focused work periods only)
- **AFK time** — Keyboard/mouse idle periods during the day (inactive but system still recording)
- **Project Tracking %** — Time attributed to tasks (vs. untracked background work)
- **Focus time %** — Task time spent on high-score (productive) category activities
- **Overall productivity %** — Productive time as percentage of total active time
- **Task Productivity Score** — Sum of all per-hour scores across tracked tasks
- **Current Session / Last Break** — Most recent work period and pause duration

### Report Summary Total (Bottom of Report)

Both hierarchical and timeline reports show a unified summary line:
```
                                                Total Time: 0:19:02  [prod   0%]
```

**Fields:**
- **Total Time**: Sum of all tracked time (excluding "No project assigned" sentinel)
- **[prod XX%]**: Productivity percentage = (productive minutes / total minutes) × 100
  - **Productivity minutes**: Time spent in high-score categories (positive score)
  - **Example**: 30 min total, 18 min in "Coding" (score 10+) = [prod 60%]
  
**Format notes:**
- Right-aligned to terminal width for visual consistency
- Same format used in both hierarchical and timeline reports
- Provides quick overview of tracked time quality

## Architecture Notes

### Duration Measurement

**By default (window-based):**
- Task duration = sum of **window event durations** that overlap with the task
- A window event is any period a user was focused on an app/window (kitty, browser, etc.)
- Gaps between window events (task pause) are not counted
- **Advantage**: Accurate representation of active time
- **Disadvantage**: Offline work (no window events) shows zero duration

**For OFFLINE-tagged tasks:**
- Task duration = sum of all **valid sandwiched sessions** between consecutive task events
- Each session = Event1 duration + Gap + Event2 duration (only if no other tasks or interruptions during gap)
- Filters out window events for OFFLINE tasks (they're not counted)
- **Advantage**: Captures work done away from computer, excluding task switches and interruptions
- **Disadvantage**: Requires proper task event markers (start/resume events) to be recorded
- **See**: Special Handling: OFFLINE Tasks section

### Event Correlation

Window events are matched to task events via **temporal overlap**:
```python
event.timestamp < task.timestamp + task.duration
and task.timestamp < event.timestamp + event.duration
```

When multiple tasks overlap a window event, the **first task in list order** is used (no prioritization).

**Important**: The task event's duration only determines whether it overlaps with window events. For duration calculation, the window event durations are what gets summed (unless task is OFFLINE-tagged).

### Continuity in Timeline

Consecutive window events for the **same (project, task, taskwarrior_event) triplet** are grouped into a single timeline slot, even if different apps/windows were focused. This shows "how long you worked on this task" rather than "how long kitty was focused."

### Gap Markers

- **`[AFK]`** — Keyboard/mouse idle (user away)
- **`[OFFLINE]`** — Computer offline or ActivityWatch not running (gap > 2 minutes)
- **`[offline_extension]`** — OFFLINE period attached to OFFLINE-tagged task

### Productivity Score Calculation

Per-hour score: `event.duration_hours × category.score`

Example: 15 minutes of Coding (score 10) = 0.25 hours × 10 = 2.5 points

**In reports:**
- Each project/task/category shows a score in parentheses: `(0.10)`, `(10.25)`
- Sum of all scores across a task = total productivity contribution
- Negative scores indicate distracting activities (time wasted)
- Zero scores are neutral (no productivity value assigned)

### Report Format Consistency

Both hierarchical and timeline reports use **identical formatting** for the summary total line:
- **Format**: `Total Time: HH:MM:SS  [prod XX%]`
- **Alignment**: Right-aligned to terminal width
- **Content**: Total tracked time and productivity percentage
- **Purpose**: Quick overview of work session quality at a glance

This consistency allows users to switch between report types without re-learning the output format.

## Troubleshooting

### "No activity found for the specified period"
- Check ActivityWatch is running and recording
- Verify time period contains actual activity (check with `:all`)
- Look in "No project assigned" section — time is still counted even if not tracked to a task

### Tasks show minimal duration (much less than expected)
- **Normal behavior**: Duration = window focus time only
- Only time when you actively had the app/window focused is counted
- Gaps between focus periods (thinking, coffee breaks) are excluded
- **Solution for offline work**: Tag task with `+offline` to use full task duration

### Tasks not appearing in report at all
- Verify aw-watcher-taskwarrior is running and connected to ActivityWatch
- Check task was active during the period (use `tws` to verify)
- Ensure task event overlaps with window activity (or use `+offline` tag)
- Try `--timesheet` view to see if task appears there with different formatting

### OFFLINE task showing zero or wrong duration
- Ensure task has `+offline` tag (case-sensitive in ActivityWatch)
- Verify task event exists in ActivityWatch bucket
- Check task event timestamps in ActivityWatch match expected times
- Confirm `--exclude-offline` flag is NOT set (unless you want to hide OFFLINE tasks)

### Wrong productivity percentage
- Check category score is correct in settings.json (should be positive for productive work)
- Remember: `[prod XX%]` = productive time / total time
- Verify category regex matches your window titles (use `--detail-level 5` to see actual titles)
- Negative scores count as distracting time and reduce productivity percentage

### Categories not matching
- Verify regex rules are correct in settings.json
- Test regex patterns separately with your actual window titles
- Window title might not match expected pattern (check `--detail-level 5` to see exact titles)
- Remember: matching is case-insensitive by default (unless `ignore_case: false` in config)

### Report formatting looks wrong
- Check terminal width — right-aligned lines require minimum width
- Verify output is not piped/redirected (pipes affect width calculation)
- Try wider terminal if summary line appears truncated

## Running Tests

### Setup
```bash
# Install with dev dependencies
pip install -e .[dev]
```

### Run tests
```bash
# All tests (excludes live-server tests if no AW instance is running)
pytest

# Only unit tests (fast, no external dependencies)
pytest tests/unit/ -v

# With coverage report
pytest --cov=tw_report --cov-report=term-missing

# Specific test file
pytest tests/unit/test_filtering.py -v

# Specific test class/function
pytest tests/unit/test_filtering.py::TestEventFilterBasics::test_basic_filtering -v
```

### Test organization
- **`tests/unit/`** — Fast, isolated unit tests (462 tests, 15 currently failing)
  - Core logic: filtering, consolidation, OFFLINE processing
  - CLI argument parsing
  - Config loading and settings resolution
  - Formatting utilities
  - Pipeline processors

- **`tests/integration/`** — Full-pipeline tests (marked with `@pytest.mark.live_server`)
  - Requires running ActivityWatch instance
  - Run with: `pytest -m live_server` (or just `pytest` if AW is running)
  - Skipped automatically if no AW server found

### Pre-commit
```bash
# Check code style
ruff check src/ tests/

# Auto-format code
ruff format src/ tests/

# Type checking
mypy src/

# All at once
ruff check . && ruff format . --check && mypy src/ && pytest
```

## Performance

### Execution Time

Recent optimizations have significantly improved performance:

| Command | Duration | Notes |
|---------|----------|-------|
| `tw-report :today` | <1s | Single-day report (cached data) |
| `tw-report :week` | 1-2s | Week aggregation |
| `tw-report :month` | 2-5s | Month aggregation |
| `tw-report :year` | 5-15s | Full year (depends on event density) |
| `tw-report --task <uuid> --timesheet :all` | ~10s | Task-specific with 56-year period (10x speedup via window time-range optimization) |

### Performance Optimizations

#### 1. AFK-Based Optimization (detail_level ≤ 2)
- Skips expensive window bucket fetch entirely
- Uses AFK events for OFFLINE task reconciliation instead
- **Impact:** 6-5x faster for timesheet reports with default detail level

#### 2. Window Event Time-Range Filtering
- When filtering by task UUID or specific time periods, fetches window events only for time windows where task events exist
- Dramatically reduces data volume for sparse task data
- **Example:** Fetching windows for :year with sparse task data:
  - Without optimization: 100K+ events, 120+ seconds
  - With optimization: 2K events, 15-20 seconds

#### 3. OFFLINE Task Window Reconciliation (2026-07-22)
- When reconciling window events with OFFLINE tasks, reuses task time-range optimization
- Prevents full-period window fetch (e.g., 186K events for 56 years)
- **Impact:** 10x speedup for `--task <uuid> --timesheet :all` queries (95s → 10s)

### Profiling

To profile a slow command:
```bash
python -m cProfile -s cumtime -m tw_report.cli.main --timesheet :all 2>&1 | head -50
```

Or use the built-in debug scripts:
```bash
python debug_profile.py  # Profile time/memory for a command
python debug_full_pipeline.py  # Trace the full event pipeline
```

## Recent Work & Status (Session 2026-09-02)

### CRITICAL FIX: Unified Pipeline Architecture ✅ COMPLETE

**The Problem**: Two independent slot-building paths caused metrics divergence
- Timeline report: Built slots → filtered → calculated metrics
- Hierarchical report: Pre-filtered events → built slots → consolidated → aggregated
- **Result**: Identical data showed different totals (86-second discrepancies observed in production)
- **Example**: Mercado laboral showed 00:08:00 in `--by-project` but 00:06:34 in timeline view

**The Solution**: Single unified pipeline (Commit 07ed47d)
1. Build slots once from unfiltered events (builder needs complete data for correct classification)
2. Filter slots once at output point
3. Feed both report modes (timeline & hierarchical) from identical filtered data
4. No pre-filtering or separate consolidation needed

**Verification**: ✅ Production-ready
- 3/3 convergence tests pass (both paths produce identical totals)
- 519/519 unit tests pass (0 failures, 0 regressions)
- CLI manual verification: `:today` and `:yesterday` show identical metrics between timeline and `--by-project` reports
- Example: Both show Active Time 01:12:31 + AFK time 00:03:10 + Online 01:15:41 + Total Time 01:15:41

**Impact**: Eliminated silent divergence risk — both report types now guaranteed to show identical metrics

### Previous Session Work (Session 2026-09-01)

**Phase 2: Builder Consolidation & Code Cleanup** ✅ COMPLETE
- Eliminated 5 independent slot generators (4253 LOC deleted)
- Unified all slot construction into single sweep-line builder: `build_timeslot_timeline()`
- Guaranteed non-overlapping slots at construction time
- Fixed overlapping slots bug that was causing reported time > wall-clock time
- Cleaned up: removed `OfflineTaskProcessor`, `partition_task_duration()`, legacy test files
- Result: Codebase is cleaner, more maintainable, guaranteed correctness

**Phase 3: Breaks Column Feature** ✅ COMPLETE
- Added visual display of break durations between work sessions
- TDD approach: 21 comprehensive tests created before implementation
- Breaks Column displays gap durations (HH:MM:SS format) in leftmost column
- Updated DisplayColumns structure and header rendering
- Integrated break detection logic with gap separator rendering
- All tests passing: 21 breaks column tests + 37 timeline/rendering tests + 519 total unit tests

**Test Suite Health** ✅ PERFECT
- **Total**: 519 unit tests passing (all sessions)
- **Regressions**: 0
- **Test coverage**: Timeline rendering, consolidation, filtering, breaks detection, metrics calculation, convergence validation

### Known Limitations

1. **Performance** — `--consolidate-month` with detail_level >= 3 and large datasets may be slower due to category merging overhead.

2. **UTC assumption** — All time handling assumes UTC; local time zones not supported (by design, to match ActivityWatch behavior).

## Contributing

### Code style
- **Formatter:** `ruff format` (Black-compatible)
- **Linter:** `ruff check` (E, F, I, UP, B, SIM rules)
- **Type checker:** `mypy` (permissive to start, ratcheting up over time)
- **Line length:** 100 characters (per `pyproject.toml`)

### Adding features
1. Create a feature branch
2. Add tests first (TDD-style preferred)
3. Implement the feature
4. Run `ruff format .` and `ruff check .`
5. Run `pytest` (all tests must pass)
6. Update docs if user-facing
7. Submit PR with clear description

### Module boundaries
- **`cli/`** — Argument parsing, entry point
- **`core/`** — Business logic (filtering, consolidation, task matching)
- **`pipeline/`** — Data transformation and aggregation
- **`utils/`** — Pure helper functions (formatting, logging)
- **`exceptions.py`** — Custom exception hierarchy
- **`config.py`** — Configuration loading

## Future Enhancements

- [x] Modular package structure (Phases 0-12)
- [x] Config file support (TOML, XDG paths) (Phase 11)
- [x] Comprehensive test coverage (262+ unit tests) (Phases 4-9)
- [x] CI/CD pipeline (GitHub Actions) (Phase 3)
- [ ] Multi-project filtering consolidation (merge results)
- [ ] Export to CSV/JSON for external analysis
- [ ] Comparison reports (week-over-week)
- [ ] Activity trends (productivity over time)
- [ ] Integration with other time trackers (Toggl, RescueTime)
- [ ] Web UI for interactive exploration

## License

Part of the Ianua project.

## Author

Emir Herrera González <emir.herrera@gmail.com>

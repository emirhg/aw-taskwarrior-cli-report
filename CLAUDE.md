# CLAUDE.md — tw-report Project Guide

This file provides project-specific instructions for Claude Code and related agents working on **tw-report**, a sophisticated timesheet report generator that correlates ActivityWatch activity with Taskwarrior tasks.

## Getting Started

1. **Project Overview**: Read `README.md` (556 lines) for the full feature set, architecture, and report types.
2. **Code Navigation**: Use `index.txt` (362 lines) as a quick reference guide to locate files and understand structure.
3. **Architecture Details**: See `docs/ARCHITECTURE.md` for the Phase 12 comprehensive design document.
4. **Period Consolidation**: See `docs/PERIOD_CONSOLIDATION.md` for the new day/week/month/year consolidation feature.

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

## Recent Major Features

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

## When to Escalate

- **Agent type mismatch**: Use **implementer** for code changes, **planner** for design, **documentation** for task lifecycle moves, **version_control** for commit message reviews.
- **Multi-step refactors**: Use **workspace** agent for parallel-development (worktree) setup.
- **New report types**: Use **planner** to review design before **implementer** codes it.
- **Performance issues**: Profile first (`debug_profile.py`), then decide between algorithm or architectural fixes.

## Contact & Feedback

- **Issues/feedback**: See `README.md` "Known Issues" section or open a GitHub issue
- **Code review**: Use `/code-review ultra` for a thorough multi-agent review of complex changes
- **Documentation updates**: Update `index.txt` and `README.md` when adding features; keep them in sync

---

**Last Updated**: 2026-07-07 (Phase: Period consolidation detail-level support)

**Maintainers**: Emir Herrera González (user) + Claude Haiku 4.5 (AI assistant)

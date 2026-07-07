# Period-Level Consolidation (Day / Week / Month / Year)

**Status:** ✅ Complete  
**Tests:** 8 new unit tests, all passing (61/61 consolidation + args tests)  
**Feature:** `--consolidate-day`, `--consolidate-week`, `--consolidate-month`, `--consolidate-year`

## Overview

Four new CLI flags collapse activity to coarser time granularities, answering questions like: "How much time did I spend on Climb per week this year?" without the noise of one row per (date, project, task).

Each flag shows **one line per (period, project)** with just total duration + productivity %, with no start/end time range (which no longer makes sense for a whole day/week/month/year of scattered activity).

### Usage Examples

```bash
# See time spent per week on Climb for a year
tw-report --project Climb :year --timesheet --consolidate-week

# See time spent per month on all projects
tw-report :year --timesheet --consolidate-month

# See time spent per day on a specific task for a month range
tw-report "2026-04-01 2026-04-30" --task "Documentar" --consolidate-day

# See total time spent on all projects this year (one line!)
tw-report :year --timesheet --consolidate-year
```

## Output Format

### Week Example
```
W15 2026-04-06 - 2026-04-12
     ▶ Organización > Climb Institute        10:25:58  [prod   0%]
                                  Week total (tracked):  10:25:58  [prod   0%]

W16 2026-04-13 - 2026-04-19
     ▶ Organización > Climb Institute        14:21:53  [prod   0%]
                                  Week total (tracked):  14:21:53  [prod   0%]
```

### Month Example
```
2026-04 April
     ▶ Organización > Climb Institute        25:27:55  [prod   0%]
                                 Month total (tracked):  25:27:55  [prod   0%]

2026-05 May
     ▶ Organización > Climb Institute        89:56:27  [prod   0%]
                                 Month total (tracked):  89:56:27  [prod   0%]
```

### Year Example
```
2026
     ▶ Organización > Climb Institute       119:50:49  [prod   0%]
                                  Year total (tracked):  119:50:49  [prod   0%]
```

## Period Definitions

- **Day:** Calendar day (00:00-23:59:59)
- **Week:** ISO week, Monday-Sunday (matches `:week` period syntax)
- **Month:** Calendar month, 1st-last day
- **Year:** Calendar year, Jan 1-Dec 31

## Design Principles

### 1. Order-Independent Grouping
Unlike the existing `--consolidate` (which does a consecutive-run merge within the same (date, project, task) group), these modes use a **dict-keyed group-by** across the entire slot list. Every slot for a given (period_bucket, project) is summed together **regardless of order or task**. This gives the true "time spent on X in period Y" view.

### 2. Mutually Exclusive Flags
The four new flags (`--consolidate-day/week/month/year`) are mutually exclusive with each other and with the existing `--consolidate` flag. Only one can be used per invocation:

```bash
tw-report --consolidate-day --consolidate-week :month  # ✗ Error: not allowed
tw-report --consolidate --consolidate-day :month       # ✗ Error: not allowed
tw-report --consolidate-day :month                     # ✓ OK
```

### 3. Universal Filter Compatibility
These modes work with **any** filter (`--project`, `--task`, `--app`) since they operate on already-filtered `slots` (the EventFilter is applied first, then consolidation happens on the result). This allows queries like:

```bash
tw-report --task 48 :month --consolidate-month         # Time per month on task 48
tw-report --app Slack :year --consolidate-week         # Slack time per week
```

### 4. Intuitive Sorting
Within each period, projects are **sorted by descending duration** (most time spent first), making it easy to scan which projects dominated that period.

```
2026-05 May
     ▶ Project A (biggest consumer)      50:00:00  [prod 10%]
     ▶ Project B                         30:00:00  [prod  5%]
     ▶ Project C                         10:00:00  [prod  2%]
```

## Implementation

### New Function: `consolidate_by_period()`
Located in `core/consolidation.py`. Takes a flat list of slot dicts and a period mode, returns a sorted list of aggregated dicts with fields:
- `period_start`: The start date of the period bucket (used for grouping and sorting)
- `project`: Project name
- `duration` / `actual_duration`: Total time in that (period, project)
- `productive_duration`: Total productive time
- `afk_duration`: Total AFK time (accumulated from type="afk" slots in the same group)

Excludes `type="offline"` gap markers; includes `type="afk"` and `type="offline_task"` slots (they carry real project/duration data).

### New Function: `print_period_consolidated_report()`
Located in `pipeline/timeline_render.py`. Reuses:
- `print_report_header()` for the period/total-time header block (same metrics display as timeline report)
- `format_timeline_line()` and `format_duration_tracked_prod()` for per-project line rendering

Prints one line per (period, project), then a period-level total, no start/end times shown.

### CLI Changes
`cli/args.py`: Added four flags to a mutually-exclusive group with the existing `--consolidate` flag.

### Main Dispatch
`cli/main.py`: Early detection of which consolidation mode is set; dispatches to `print_period_consolidated_report()` if period mode is active, otherwise uses the standard timeline report flow (which may still use `--consolidate` for fine-grain consolidation).

## Testing

**8 new unit tests** in `tests/unit/test_consolidation.py::TestConsolidateByPeriod`:
- ✅ `test_consolidate_by_day` — one entry per day per project
- ✅ `test_consolidate_by_week` — one entry per ISO week per project
- ✅ `test_consolidate_by_month` — one entry per calendar month per project
- ✅ `test_consolidate_by_year` — one entry per calendar year per project
- ✅ `test_consolidate_by_period_multiple_projects` — different projects create separate entries
- ✅ `test_consolidate_by_period_excludes_offline_gaps` — gap markers are excluded
- ✅ `test_consolidate_by_period_includes_afk` — AFK time accumulates per group
- ✅ `test_consolidate_by_period_sorting` — sorted by period then descending duration

All tests use minimal dict fixtures matching TimelineSlot's contract.

## Comparison: `--consolidate` vs Period Modes

| Aspect | `--consolidate` | `--consolidate-{day\|week\|month\|year}` |
|--------|---|---|
| **Granularity** | Fine-grain (per date, project, task) | Coarse-grain (per period, project only) |
| **Grouping** | Order-dependent consecutive runs | Order-independent dict-keyed |
| **Shows time range** | Yes (start-end times on same line) | No (no time range makes sense) |
| **Best for** | Detailed timesheet, hourly accountability | Summary view, "time spent on X per period" |
| **Works with** | `--timesheet --consolidate` together | Can be used alone; ignores `--timesheet` |

## Edge Cases

### Cross-Month / Cross-Year Slots
If a single session spans midnight (very rare, usually only in all-nighters), it's **split proportionally** by the upstream `split_slots_spanning_days()` function in `print_timeline_report()`, so each day gets its fair share of duration/productive_duration. This happens before consolidation, so the consolidation function never sees a slot that spans multiple days.

### No Activities in Period
Prints: `No activity found for the specified period.` (same as timeline report).

### Mixed Projects in Period
Each project gets its own line, sorted by descending duration. The period total is the sum of all projects in that period.

### AFK Slots
Accumulated into the `afk_duration` field of their (period, project) group. If an AFK period has `project: "No project"`, it still gets its own entry unless there's other activity under "No project" in that same period.

## Future Enhancements

1. **Relative date grouping** — e.g., `--consolidate-last-7-days` (would just be a new period mode internally)
2. **CSV/JSON export** — structured output for data analysis
3. **Comparison** — `--consolidate-week --compare-to-last-year` to see week-over-week change
4. **Filtering within consolidation** — e.g., show only projects >5 hours in a period

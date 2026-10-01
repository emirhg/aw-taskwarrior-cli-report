# Project Architecture

## Overview

`tw-report` is a world-class Python CLI project using **src-layout** structure with modular extraction, comprehensive testing, and CI/CD pipeline. The application has been fully refactored into organized subpackages.

**Project structure:** Phases 0-12 complete ✅
- **Phases 1-2:** Dead code removal, packaging foundation, logging, CI/CD
- **Phases 3-8:** Modular extraction (CLI, core, pipeline, utils)
- **Phases 9-10:** Test hardening, entry point wiring
- **Phases 11-12:** Config-file support, documentation

## Directory Structure

```
work_report/
├── bin/                           # Executable entry points
│   └── tw-report                  # Dev wrapper (calls src/tw_report/cli/main.py)
│
├── src/tw_report/                 # Main Python package
│   ├── __init__.py
│   │
│   ├── cli/                       # Command-line interface (Phase 4)
│   │   ├── __init__.py
│   │   ├── args.py                # Argument parsing (30+ CLI flags)
│   │   └── main.py                # Entry point orchestration
│   │
│   ├── core/                      # Core business logic
│   │   ├── __init__.py
│   │   ├── categories.py          # Category rules loading & matching (Phase 5)
│   │   
│   │   ├── events.py              # ActivityWatch event fetching (Phase 5)
│   │   ├── filtering.py           # EventFilter class
│   │   
│   │   ├── period.py              # Period keyword parsing (Phase 5)
│   │   ├── task_matching.py       # Task correlation logic (Phase 6)
│   │   ├── timeline.py            # Timeline slot data structures
│   │   └── consolidation.py       # Slot consolidation
│   │
│   ├── pipeline/                  # Data processing pipeline
│   │   ├── __init__.py
│   │   ├── models.py              # Data classes (ReportEvent, TimelineSlot, etc.)
│   │   ├── processors.py          # Pipeline functions (build_canonical_events, etc.)
│   │   ├── report_render.py       # Hierarchical report rendering (Phase 8a)
│   │   └── timeline_render.py     # Timeline report rendering (Phase 8b)
│   │
│   ├── utils/                     # Pure utility functions
│   │   ├── __init__.py
│   │   ├── formatting.py          # Duration/title formatting (Phase 7)
│   │   └── logging.py             # Structured logging configuration (Phase 2)
│   │
│   ├── config.py                  # TOML config loading & XDG paths (Phase 11)
│   └── exceptions.py              # Custom exception hierarchy (Phase 5)
│
├── tests/                         # Comprehensive test suite (262+ tests)
│   ├── conftest.py                # Pytest fixtures & configuration
│   │
│   ├── unit/                      # Unit tests (fast, no external deps)
│   │   ├── test_args.py           # CLI argument parsing (32 tests)
│   │   ├── test_categories.py     # Category loading & matching (18 tests)
│   │   ├── test_config.py         # Config file support (16 tests)
│   │   
│   │   ├── test_events.py         # Event fetching with mocks (13 tests)
│   │   ├── test_filtering.py      # EventFilter & issue regressions
│   │   ├── test_formatting.py     # Duration/title formatting (54 tests)
│   │   
│   │   ├── test_period.py         # Period keyword parsing (15 tests)
│   │   ├── test_report_render.py  # Hierarchical report output (15 tests)
│   │   ├── test_task_matching.py  # Task correlation (22 tests)
│   │   └── test_timeline_render.py # Timeline report output (11 tests)
│   │
│   └── integration/               # Full-pipeline tests (@pytest.mark.live_server)
│       ├── test_data_consistency.py
│       ├── test_events_preservation.py
│       └── test_overlap_source.py
│
├── docs/                          # Documentation
│   ├── ARCHITECTURE.md            # This file (updated Phase 12)
│   ├── specs/                     # Technical specifications
│   │   ├── SPECIFICATION_CHRONOLOGICAL_CONSISTENCY.md
│   │   └── SPECIFICATION_CONTINUOUS_SESSIONS.md
│   │
│   └── analysis/                  # Design & findings
│       ├── GAP_FILLING_ANALYSIS.md
│       └── NESTED_EVENTS_DISPLAY.md
│
├── .github/
│   └── workflows/
│       └── ci.yml                 # GitHub Actions CI/CD (Phase 3)
│
├── .pre-commit-config.yaml        # Pre-commit hooks (ruff check+format)
├── .gitignore
├── pyproject.toml                 # Build system, package config, tools
├── README.md                      # Quick start guide (updated Phase 12)
└── sentinel-warrior-cli/          # Separate tool (legacy, can be removed)
```

## Module Organization

### `tw_report/cli/` - Command-line Interface (Phase 4, 10)

**Purpose:** Argument parsing and CLI entry point orchestration.

- **`args.py` (Phase 4)**
  - `parse_args()`: Parse 20+ CLI flags (--project, --task, --detail-level, etc.)
  - `parse_positional_args()`: Disambiguate period keywords from search terms
  - `reorder_arguments()`: Handle flexible argument ordering
  - Clean separation between parsing and orchestration
  - 32 unit tests for complete flag coverage

- **`main.py` (Phase 10)**
  - Orchestrates event fetching, filtering, and report generation
  - Configures logging, resolves settings precedence
  - Loads user config via `config.py`
  - Dynamically loads monolith (temporary in Phase 10, will be fully modularized in Phase 11+)
  - **Console script:** `tw-report = "tw_report.cli.main:main"` (pyproject.toml)

### `tw_report/core/` - Core Business Logic

**Purpose:** Reusable, composable components for domain logic.

- **`period.py` (Phase 5)**
  - `parse_period()`: Parse period keywords (:today, :week, :month, etc.)
  - Supports date ranges and ISO date formats
  - Pure function, stdlib-only
  - 15 unit tests

- **`categories.py` (Phase 5)**
  - `load_categories()`: Load category rules from JSON
  - `compile_category_rules()`: Pre-compile regex patterns
  - `get_category_score()`: Retrieve category productivity score
  - `categorize_event()`: In-place event categorization
  - 18 unit tests covering valid/malformed JSON, matching logic

- **`events.py` (Phase 5)**
  - `get_bucket_id()`: Resolve ActivityWatch bucket names
  - `get_events()`: Fetch events from ActivityWatch with graceful degradation
  - Connection errors logged, returns empty list (no exception)
  - 13 unit tests with mocked ActivityWatchClient

- **`task_matching.py` (Phase 6)**
  - `find_active_task()`: Correlate window event with overlapping task
  - `get_task_info()`: Extract project/task from task event
  - `task_has_offline_tag()`: Detect OFFLINE tag (case-insensitive)
  - `build_offline_category_structure()`: Create Offline category dict
  - 22 unit tests including offline-tag detection

- **`filtering.py`**
  - `EventFilter`: Unified filtering for all entry types (regular, afk, offline, gap)
  - Handles `--exclude-non-project`, `--project`, `--task`, `--app`, `--exclude-*` flags
  - **Issue Fix:** #1 (OFFLINE task filtering), #3 (consistent filtering)
  - 40+ unit tests including issue regression tests (6 xpassed — known issues fixed)

- **`consolidation.py`**
  - `TimelineSlotManager`: Timeline slot management and merging
  - Consolidates same (date, project, task) entries
  - Smart handling of OFFLINE gaps
  - **Issue Fix:** #2 (gap consolidation)

- **`offline.py`**
  - `OfflineTaskProcessor`: Detects and processes OFFLINE-tagged tasks
  - Calculates durations excluding interruptions
  - Validates sessions against concurrent tasks
  - Results filtered through EventFilter
  - Constructs synthetic `offline_task` TimelineSlots with proper validation

- **`timeline.py`**
  - `Timeline`: In-memory timeline management
  - `TimelineSlot`: Immutable slot data structure with validation
  - Automatic sorting on insertion, safe round-tripping via to_dict()

### `tw_report/pipeline/` - Data Processing Pipeline

**Purpose:** Data transformation and output formatting.

- **`models.py`**
  - `ReportEvent`: Window event + associated task info
  - `TimelineSlot`: Immutable slot data (start, duration, project, task, etc.)
  - `ReportContext`: Container for all context data
  - `ReportMetrics`: Computed productivity metrics

- **`processors.py`**
  - Core pipeline functions:
    - `build_canonical_events()`: Correlate window events with tasks
    - `aggregate_hierarchy()`: Build project/task/category tree
    - `compute_metrics()`: Calculate totals and productivity scores
    - `build_context()`: Assemble ReportContext
    - `merge_overlapping_afk_periods()`: Data cleaning
    - `generate_timeline_data()`: Create timeline slots from events
    - `generate_gap_entries()`: Create AFK/gap markers

- **`report_render.py` (Phase 8a)**
  - `print_report_header()`: Render report header with metrics
  - `print_report()`: Hierarchical (project/task/category) report rendering
  - `print_summary_total()`: Summary line with duration and productivity percentage
  - Detail levels 1-5, sorting by duration or productivity
  - 15 unit tests with capsys golden-output testing

- **`timeline_render.py` (Phase 8b)**
  - `print_timeline_report()`: Timeline report rendering (--by-project mode)
  - `split_slots_spanning_days()`: Multi-day slot handling
  - Date/week-organized display with proportional duration allocation
  - Offline-task singleton handling
  - **Bug Fix:** EventFilter integration (Phase 8b) for consistent OFFLINE task filtering
  - 11 unit tests including multi-day slot splitting

### `tw_report/utils/` - Helper Utilities

**Purpose:** Pure, reusable helper functions.

- **`formatting.py` (Phase 7)**
  - Duration formatting: `format_duration()`, `format_duration_tracked_prod()`, etc.
  - Title sanitization: `sanitize_title()`, `normalize_title()`, `truncate_title()`
  - Project path abbreviation: `abbreviate_project_path()`
  - Terminal width detection: `get_terminal_width()` (fallback to 80)
  - 54 comprehensive unit tests (unicode titles, multi-hour durations, edge cases)

- **`logging.py` (Phase 2)**
  - `configure_logging()`: Set up structured logging for `tw_report` namespace
  - Supports `--detail-level` (INFO level) and `--by-day` (DEBUG level)
  - Stderr output with formatted messages

### `tw_report/config.py` - Configuration (Phase 11)

**Purpose:** TOML config file loading with XDG Base Directory support.

- `get_config_path()`: Resolve config path ($XDG_CONFIG_HOME or ~/.config)
- `load_user_config()`: Parse TOML, graceful on missing/malformed files
- `resolve_settings()`: Merge CLI args > config file > defaults
- `ResolvedSettings`: Frozen dataclass for immutable config
- 16 unit tests covering XDG resolution, TOML parsing, precedence

### `tw_report/exceptions.py` - Exception Hierarchy (Phase 5)

**Purpose:** Typed, documented exception hierarchy.

- `TwReportError(ValueError)`: Base exception class
- `ActivityWatchConnectionError(TwReportError)`: AW connection/HTTP errors
- `ConfigParsingError(TwReportError)`: TOML/category JSON parse errors
- All include CONTEXT docstrings per project convention

### `tests/` - Test Organization

**Unit Tests** (`tests/unit/`):
- Individual class/function behavior
- No external dependencies
- Fast execution (~0.2s)

**Integration Tests** (`tests/integration/`):
- Full pipeline behavior
- Real-world scenarios
- Slower but catch regressions

**Shared Fixtures** (`tests/conftest.py`):
- Common test data and helpers
- Issue-specific fixtures (Issue #1, #2, #3)
- Helper functions: `make_datetime()`, `make_event()`

## Import Pattern

All imports use the `tw_report` namespace:

```python
# Correct
from tw_report.core.filtering import EventFilter
from tw_report.pipeline.models import ReportEvent
from tw_report.pipeline.processors import build_canonical_events

# The `src/` directory is added to sys.path automatically:
# 1. In tw-report.py: sys.path.insert(0, "src/")
# 2. In conftest.py: Pytest configuration adds src/ to path
```

## Running the Project

### Install for development (Phase 2, 10)
```bash
pip install -e .              # Install with console script entry point
pip install -e .[dev]         # Install with dev dependencies (pytest, ruff, mypy)
```

### Execute
```bash
# Via installed console script (after pip install -e .)
tw-report :today --detail-level 2 --by-project

# Via development wrapper
./bin/tw-report :today --detail-level 2 --by-project

# Via Python module
python -m tw_report.cli.main :today --detail-level 2 --by-project
```

### Run tests
```bash
# Setup
pip install -e .[dev]

# All unit tests (262+ tests, ~1s)
pytest tests/unit/ -v

# Full suite (includes integration tests if AW running)
pytest -v

# Skip live-server tests (for CI or without AW)
pytest -m "not live_server"

# With coverage
pytest --cov=tw_report --cov-report=term-missing

# Specific test
pytest tests/unit/test_filtering.py::TestEventFilterBasics::test_basic_filtering -v
```

### Code quality
```bash
# Format check
ruff format --check .

# Auto-format
ruff format .

# Lint (E, F, I, UP, B, SIM)
ruff check .

# Type check
mypy src/

# All at once
ruff check . && ruff format . --check && mypy src/ && pytest
```

## Dependencies

**External:**
- `aw_core`: ActivityWatch data models
- `aw_transform`: Event filtering utilities
- `pytest`: Testing framework

**Internal:**
- `tw_report.core.*`: Filtering, consolidation, OFFLINE processing
- `tw_report.pipeline.*`: Data models and transformations

## Error Handling Strategy

### Custom Exception Hierarchy (Phase 5)

All errors extend from `tw_report.exceptions.TwReportError(ValueError)`:

```python
TwReportError(ValueError)  # Base exception
├── ActivityWatchConnectionError  # HTTP/connection issues
└── ConfigParsingError            # TOML/JSON parse errors
```

Each exception includes a **CONTEXT docstring** documenting:
- When the exception is raised
- Root causes
- Recommended user actions

### Logging & Graceful Degradation (Phase 2)

- **Connection errors:** Log as WARNING, return empty list (don't crash)
- **Config errors:** Raise `ConfigParsingError` with user-friendly message
- **Category errors:** Raise `ConfigParsingError` on malformed rules
- **Event errors:** Log and skip individual events (partial success)

### Logging Levels

- **WARNING:** Non-fatal errors (AW connection, category load failure)
- **INFO:** User-requested verbosity (--detail-level)
- **DEBUG:** Developer debugging (--by-day)

Example:
```bash
tw-report :today --detail-level          # INFO level logging
tw-report :today --by-day            # DEBUG level logging
tw-report :today                    # WARNING level (default)
```

## Performance Optimizations

The project includes several key optimizations to handle large time periods efficiently:

### AFK-Based Optimization (detail_level ≤ 2)
- **Location:** `src/tw_report/cli/main.py:237`, `src/tw_report/core/offline.py`
- **Impact:** 6-5x faster for default detail level
- **How it works:** Skips expensive window bucket fetch entirely; uses AFK events for OFFLINE task reconciliation instead

### Window Event Time-Range Filtering
- **Location:** `src/tw_report/cli/main.py:80-126` (_fetch_events_for_ranges, _get_time_ranges_from_events)
- **Impact:** 5-10x faster for sparse task data over large periods
- **How it works:** Extracts time windows from task events; fetches window/AFK events only for those windows, not entire period

### OFFLINE Task Window Reconciliation (2026-07-22)
- **Location:** `src/tw_report/cli/main.py:407-420`
- **Impact:** 10x faster for `--task <uuid> --by-project :all` queries
- **How it works:** Reuses time-range optimization when re-fetching windows for OFFLINE task reconciliation
- **Example:** 186K events → 1.9K events; 2.8s → 0.023s for gap generation

### Benchmark Results

```
Example: tw-report --task e7e9d2b1-9f68-484c-ad44-29c9e5889027 --by-project :all

Before optimization:  95+ seconds (1m 35s)
After optimization:   ~10 seconds

Data reduction:
  Window events fetched: 186,279 → 1,903 (99% reduction)
  generate_gap_entries: 2.8s → 0.023s (121x speedup)
```

## Design Principles

1. **Single Responsibility**: Each module has one clear purpose
2. **Composability**: Classes usable independently or together
3. **Testability**: Pure functions and dependency injection > global state
4. **Consistency**: Unified `EventFilter` interface for all entry types
5. **Separation of Concerns**: Core logic separate from presentation
6. **Immutability**: Data classes frozen where appropriate
7. **Type Safety**: Type hints throughout (mypy-checked)
8. **Fail Fast:** Validation in `__post_init__` for data classes

## Key Architectural Improvements (Phases 1-12)

| Before | After | Benefit |
|--------|-------|---------|
| 3872-line monolith | 13 focused modules | Maintainability, testability |
| Scattered filter logic (5+ locations) | `EventFilter` class | Single source of truth |
| No consolidation bounds handling | `TimelineSlotManager` | Clear slot merging logic |
| Inline OFFLINE processing | `OfflineTaskProcessor` | Reusable, testable component |
| Zero tests | 262+ unit tests | Regression prevention, confidence |
| No logging | Structured logging module | Observability, debugging |
| No CI/CD | GitHub Actions matrix (Py 3.8, 3.11) | Quality gates on every push |
| No packaging | Full pyproject.toml + console script | Installable, distributable |
| No config | TOML + XDG support (Phase 11) | User customization |
| Monolithic entry point | Modular cli/main.py | Clear orchestration |

## Future Improvements

- [ ] Full type hints (mypy strict mode)
- [ ] Web API for remote querying
- [ ] Export to CSV/JSON
- [ ] Week-over-week comparison reports
- [ ] Real-time dashboard mode
- [ ] Integration with other time trackers
- [ ] Offline sync to local cache (for no-network scenarios)
- [ ] Plugin system for custom processors
- [ ] Separate sentinel-warrior-cli into own repository

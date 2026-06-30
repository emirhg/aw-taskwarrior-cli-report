# Project Architecture

## Overview

`tw-report` is organized using a **src-layout** structure with clear separation between library code (`src/tw_report/`) and executable scripts (`tw-report.py`).

## Directory Structure

```
work_report/
├── bin/                           # Executable entry points
│   ├── tw-report                  # Main CLI script (wrapper)
│   ├── today.sh                   # Shell helper scripts
│   └── yesterday.sh
│
├── src/tw_report/                 # Main Python package
│   ├── __init__.py
│   │
│   ├── core/                      # Core business logic
│   │   ├── __init__.py
│   │   ├── filtering.py           # EventFilter class
│   │   ├── consolidation.py       # TimelineSlotManager class
│   │   └── offline.py             # OfflineTaskProcessor class
│   │
│   ├── pipeline/                  # Data processing pipeline
│   │   ├── __init__.py
│   │   ├── models.py              # Data structures (ReportEvent, ReportContext, etc.)
│   │   ├── processors.py          # Pipeline functions (build_canonical_events, etc.)
│   │   └── presenters.py          # Output formatting (HierarchicalReport, TimelineReport)
│   │
│   └── utils/                     # Helper utilities
│       └── __init__.py
│
├── tests/                         # All tests organized by type
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures
│   │
│   ├── unit/                      # Unit tests
│   │   ├── test_filtering.py      # EventFilter tests
│   │   ├── test_consolidation.py  # TimelineSlotManager tests
│   │   └── test_offline.py        # OfflineTaskProcessor tests
│   │
│   ├── integration/               # Integration tests
│   │   ├── test_report.py
│   │   ├── test_data_consistency.py
│   │   └── ...
│   │
│   └── fixtures/                  # Test data
│       └── sample_data.json
│
├── scripts/                       # Standalone utilities (not part of package)
│   ├── time_spent_today.py
│   ├── working_hours.py
│   └── reporte-diario.awk
│
├── docs/                          # Documentation
│   ├── ARCHITECTURE.md            # This file
│   ├── API.md                     # Module API reference
│   │
│   ├── specs/                     # Specifications
│   │   ├── SPECIFICATION_*.md
│   │   └── REQUIREMENTS.md
│   │
│   └── analysis/                  # Analysis & findings
│       ├── DATA_CONSISTENCY_FINDINGS.md
│       ├── ROOT_CAUSE_*.md
│       └── GAP_FILLING_*.md
│
├── tw-report.py                   # Main executable script
├── conftest.py                    # Pytest configuration (adds src/ to path)
├── pyproject.toml                 # Package metadata
├── setup.py                       # Installation script
├── .gitignore                     # Git ignore rules
├── README.md                      # Quick start guide
└── sentinel-warrior-cli/          # Separate CLI tool (consider separate repo)
```

## Module Organization

### `tw_report/core/` - Core Business Logic

**Purpose:** Reusable, composable components for filtering, consolidation, and OFFLINE processing.

- **`filtering.py` (EventFilter)**
  - Unified filtering logic for all entry types
  - Handles `--exclude-non-project`, `--project`, `--task`, `--app` flags
  - Entry types: regular, afk, offline, offline_task, gap
  - **Issue Fix:** #1 (OFFLINE task filtering), #3 (consistent filtering)

- **`consolidation.py` (TimelineSlotManager)**
  - Timeline slot management and merging
  - Consolidates same (date, project, task) entries
  - Smart handling of OFFLINE gaps
  - **Issue Fix:** #2 (gap consolidation)

- **`offline.py` (OfflineTaskProcessor)**
  - Detects and processes OFFLINE-tagged tasks
  - Calculates durations excluding interruptions
  - Validates sessions against concurrent tasks
  - Results filtered through EventFilter

### `tw_report/pipeline/` - Data Processing Pipeline

**Purpose:** Data transformation and output formatting.

- **`models.py`**
  - `ReportEvent`: Window event + associated task info
  - `ReportContext`: Container for all context data
  - `ReportMetrics`: Computed metrics

- **`processors.py`**
  - Core pipeline functions:
    - `build_canonical_events()`: Correlate window events with tasks
    - `aggregate_hierarchy()`: Build project/task/category tree
    - `compute_metrics()`: Calculate totals and productivity scores
    - `merge_overlapping_afk_periods()`: Data cleaning

- **`presenters.py`**
  - `HierarchicalReport`: Tree-based output (default)
  - `TimelineReport`: Timeline-based output (--timesheet)

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

### Execute the script
```bash
python tw-report.py --detail-level=2 --timesheet --consolidate :today
```

### Run tests
```bash
# All tests
python -m pytest tests/ -v

# Only unit tests
python -m pytest tests/unit/ -v

# Specific test
python -m pytest tests/unit/test_filtering.py::TestEventFilterBasics -v
```

### Install for development
```bash
pip install -e .
```

## Dependencies

**External:**
- `aw_core`: ActivityWatch data models
- `aw_transform`: Event filtering utilities
- `pytest`: Testing framework

**Internal:**
- `tw_report.core.*`: Filtering, consolidation, OFFLINE processing
- `tw_report.pipeline.*`: Data models and transformations

## Design Principles

1. **Single Responsibility**: Each module has one clear purpose
2. **Composability**: Classes can be used independently or together
3. **Testability**: Pure functions and dependency injection over global state
4. **Consistency**: Unified interface through EventFilter for all entry types
5. **Separation of Concerns**: Core logic separate from presentation

## Key Architectural Improvements

| Before | After | Benefit |
|--------|-------|---------|
| Scattered filter logic (5+ locations) | `EventFilter` class | Single source of truth |
| No consolidation bounds handling | `TimelineSlotManager` | Clear slot merging logic |
| Inline OFFLINE processing | `OfflineTaskProcessor` | Reusable, testable component |
| Mixed test locations | `tests/{unit,integration}/` | Better organization |
| Deep import paths | `tw_report.core.*` | Clear module hierarchy |

## Future Improvements

1. Extract CLI logic from tw-report.py into `tw_report/cli.py`
2. Add `tw_report/utils/` module for common helpers
3. Consider separating sentinel-warrior-cli into own repository
4. Add type hints throughout for better IDE support
5. Create pip-installable package with entry points

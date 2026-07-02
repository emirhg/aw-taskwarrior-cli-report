"""
tw-report CLI entry point.

This module serves as the console script entry point defined in pyproject.toml.
It delegates to the actual implementation. Phase 10 milestone: entry point wired.

In Phase 11-12, this will contain fully modularized orchestration logic after
remaining pipeline functions are extracted. For now, it calls the monolith main().
"""

import importlib.util
import sys
from pathlib import Path


def main():
    """Entry point for tw-report CLI."""
    # Load tw-report.py dynamically (temporary until full modularization)
    tw_report_path = Path(__file__).parent.parent.parent.parent / "tw-report.py"

    spec = importlib.util.spec_from_file_location("tw_report_monolith", tw_report_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load tw-report.py from {tw_report_path}")

    tw_report_module = importlib.util.module_from_spec(spec)
    sys.modules["tw_report_monolith"] = tw_report_module
    spec.loader.exec_module(tw_report_module)

    # Call the main function from the monolith
    tw_report_module.main()


if __name__ == "__main__":
    main()

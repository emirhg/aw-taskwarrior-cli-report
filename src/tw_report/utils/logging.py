"""
Logging configuration for tw-report.

Provides a centralized logging setup used across all modules. Each module
gets its own logger via logging.getLogger(__name__), which routes to the
tw_report root logger configured here.

Logging levels:
- WARNING (default): only errors and warnings
- INFO (--verbose): operational info (data sources, major steps)
- DEBUG (--debug): detailed traces, variable values, full exc_info

All output goes to stderr to keep stdout clean for pipeable output.
"""

import logging
import sys
from typing import Optional


def configure_logging(verbose: bool = False, debug: bool = False) -> None:
    """
    Configure the root logger for the tw_report namespace.

    Args:
        verbose: If True, set level to INFO (operational details)
        debug: If True, set level to DEBUG (detailed traces, overrides verbose)
    """
    logger = logging.getLogger("tw_report")

    # Only configure if not already configured (prevent duplicate handlers)
    if logger.handlers:
        return

    # Determine log level
    if debug:
        level = logging.DEBUG
        fmt = "%(levelname)s:%(name)s: %(message)s"
    elif verbose:
        level = logging.INFO
        fmt = "%(levelname)s: %(message)s"
    else:
        level = logging.WARNING
        fmt = "%(levelname)s: %(message)s"

    logger.setLevel(level)

    # Handler to stderr
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)

    # Suppress third-party library logging unless debugging
    if not debug:
        for lib_name in ["aw_client", "aw_core", "aw_transform"]:
            logging.getLogger(lib_name).setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger for the given module name.

    Convenience function following stdlib convention. Equivalent to
    logging.getLogger(__name__) in a module, but useful for lazy imports.

    Args:
        name: Logger name (defaults to "tw_report" root logger)

    Returns:
        Configured logger instance
    """
    if name is None:
        return logging.getLogger("tw_report")
    return logging.getLogger(f"tw_report.{name}" if not name.startswith("tw_report") else name)

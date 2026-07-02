"""
Custom exception hierarchy for tw-report.

Defines domain-specific exceptions for configuration, connectivity, and
validation errors. All exceptions subclass ValueError to match the existing
TimelineSlotValidationError convention, allowing them to be caught both
specifically and generically.

CONTEXT: This exception hierarchy replaces ad-hoc error handling (print to
stderr, continue with degraded results) with typed, catchable exceptions.
This enables caller code to make informed decisions about error handling
(fail hard vs. degrade gracefully), while maintaining visibility through
logging instead of silent swallows.
"""


class TwReportError(ValueError):
    """Base exception for tw-report domain errors.

    Subclasses ValueError to match the existing TimelineSlotValidationError
    pattern, ensuring all domain errors can be caught via except ValueError
    in addition to their specific types.

    CONTEXT: Subclassing ValueError (not bare Exception) follows the Python
    convention that user/domain errors are ValueError-like (expected failures,
    not catastrophic bugs). This allows code to distinguish between expected
    domain failures and unexpected programming errors.
    """

    pass


class ActivityWatchConnectionError(TwReportError):
    """Raised when ActivityWatch server is unreachable or unresponsive.

    This error occurs when:
    - Server is offline or not running
    - Network connectivity is broken
    - Server returns an unexpected response format

    Callers can catch this to decide whether to fail hard or degrade gracefully
    (continue with partial/missing data).
    """

    pass


class ConfigParsingError(TwReportError):
    """Raised when configuration file (JSON, TOML, etc.) is malformed.

    This error occurs when:
    - JSON/TOML syntax is invalid
    - Required fields are missing
    - Field types are incorrect

    Callers can catch this to provide helpful error messages indicating which
    config file failed and why.
    """

    pass


class CategoryValidationError(TwReportError):
    """Raised when category rule definitions are structurally invalid.

    This error occurs when:
    - Regex patterns fail to compile
    - Category rule structure doesn't match expected schema
    - Score values are out of acceptable range

    Callers can catch this to validate configuration before proceeding with
    report generation.
    """

    pass

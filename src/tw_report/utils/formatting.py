"""
Pure formatting utilities for duration, titles, and timeline display.

All functions are pure (no I/O side effects). Formatting is separated from
presentation to enable testing and reuse across different output formats.
"""

import re
import shutil
import unicodedata
from datetime import timedelta
from typing import Optional


def format_duration(duration: timedelta) -> str:
    """Format timedelta as HH:MM:SS string.

    Args:
        duration: Time interval to format

    Returns:
        String in HH:MM:SS format, zero-padded (e.g., "01:23:45", "00:05:30")
    """
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def format_duration_tracked_prod(
    tracked_duration: timedelta, productive_within: timedelta
) -> str:
    """Format duration plus [prod NN%] for tracked-slot totals.

    Shows the duration with productivity percentage in a fixed-width format,
    right-aligned to enable consistent visual alignment across multiple output lines.

    Args:
        tracked_duration: Total time tracked in this slot
        productive_within: Time spent on productive activities within the tracked duration

    Returns:
        String formatted as "HH:MM:SS  [prod XXX%]" with right-aligned percentage
        (e.g., "[prod 100%]", "[prod  53%]", "[prod   3%]")
    """
    base = format_duration(tracked_duration)
    if tracked_duration.total_seconds() <= 0:
        return base
    pct = productive_within.total_seconds() / tracked_duration.total_seconds() * 100
    label = f"[prod {pct:>3.0f}%]"
    return f"{base}  {label:>11}"


def format_afk_label(duration: timedelta) -> str:
    """Format AFK duration label with fixed-width padding.

    Matches the width of format_duration_tracked_prod output for visual alignment.

    Args:
        duration: AFK time to format

    Returns:
        String formatted as "HH:MM:SS  [   AFK   ]" (11-char label for alignment)
    """
    base = format_duration(duration)
    label = "[   AFK   ]"
    return f"{base}  {label:>11}"


def format_offline_label(duration: timedelta) -> str:
    """Format OFFLINE duration label with fixed-width padding.

    Matches the width of AFK labels for visual alignment.

    Args:
        duration: Offline time to format

    Returns:
        String formatted as "HH:MM:SS  [ OFFLINE ]" (11-char label for alignment)
    """
    base = format_duration(duration)
    label = "[ OFFLINE ]"
    return f"{base}  {label:>11}"


def format_duration_with_afk(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
) -> str:
    """Format duration with optional AFK notation for consolidated display.

    When afk_duration is present (consolidation with AFK breaks), includes
    AFK time notation. Otherwise, standard productivity format.

    Args:
        tracked_duration: Total time tracked in this slot
        productive_within: Time spent on productive activities
        afk_duration: Optional time spent away from keyboard (if present, included in output)

    Returns:
        String formatted as:
        - With AFK: "(HH:MM:SS AFK)  HH:MM:SS  [prod XX%]"
        - Without AFK: "HH:MM:SS  [prod XX%]"
    """
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    if afk_duration and afk_duration.total_seconds() > 0:
        afk_str = format_duration(afk_duration)
        return f"({afk_str} AFK)  {base_format}"

    return base_format


def format_duration_with_gaps(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
    offline_extension_duration: Optional[timedelta] = None,
) -> str:
    """Format duration with optional AFK and OFFLINE extension notation.

    For consolidation with multiple break types, shows all gap components in
    a single notation. Falls back to format_duration_with_afk if no gaps.

    Args:
        tracked_duration: Total time tracked
        productive_within: Time spent on productive activities
        afk_duration: Optional time away from keyboard
        offline_extension_duration: Optional offline (system not running) time

    Returns:
        String formatted as:
        - With gaps: "(HH:MM:SS AFK, HH:MM:SS OFFLINE)  HH:MM:SS  [prod XX%]"
        - Without gaps: "HH:MM:SS  [prod XX%]"
    """
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    gap_parts = []
    if afk_duration and afk_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(afk_duration)} AFK")
    if offline_extension_duration and offline_extension_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(offline_extension_duration)} OFFLINE")

    if gap_parts:
        gaps_str = ", ".join(gap_parts)
        return f"({gaps_str})  {base_format}"

    return base_format


def split_gaps_and_duration(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
    offline_extension_duration: Optional[timedelta] = None,
) -> tuple:
    """Format duration and gaps as separate components for column-based layout.

    Returns gaps and duration as separate strings for flexible formatting,
    allowing gaps to be displayed in a dedicated column.

    Args:
        tracked_duration: Total time tracked
        productive_within: Time spent on productive activities
        afk_duration: Optional time away from keyboard
        offline_extension_duration: Optional offline (system not running) time

    Returns:
        Tuple of (gaps_str, duration_str) where:
        - gaps_str: Normalized gap notation like "(HH:MM:SS AFK)" (empty if no gaps)
        - duration_str: Duration + productivity like "HH:MM:SS  [prod XX%]"
    """
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    gap_parts = []
    if afk_duration and afk_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(afk_duration)} AFK")
    if offline_extension_duration and offline_extension_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(offline_extension_duration)} OFFLINE")

    if gap_parts:
        gaps_str = ", ".join(gap_parts)
        return (f"({gaps_str})", base_format)

    return ("", base_format)


def format_offline_task_duration(
    wall_clock_duration: timedelta, event_duration: timedelta
) -> str:
    """Format duration for offline tasks showing offline/online time split.

    For tasks tagged as offline: shows time system was off (untracked) and time
    that was tracked while system was running. All offline time is assumed
    productive (system was powered off, no distractions).

    Productivity % = offline_duration / wall_clock_duration × 100

    Args:
        wall_clock_duration: Total time period (system on + off)
        event_duration: Time tracked while system was on (TaskWarrior activity)

    Returns:
        String formatted as "(HH:MM:SS OFF)  HH:MM:SS  [prod XX%]"
        where first time is offline period, second is online/tracked time
    """
    offline_duration = wall_clock_duration - event_duration
    offline_str = format_duration(offline_duration)
    online_str = format_duration(event_duration)
    if wall_clock_duration.total_seconds() > 0:
        pct = (
            offline_duration.total_seconds()
            / wall_clock_duration.total_seconds()
            * 100
        )
        label = f"[prod {pct:>3.0f}%]"
    else:
        label = "[prod   0%]"
    return f"({offline_str} OFF)  {online_str}  {label:>11}"


def get_terminal_width() -> int:
    """Get current terminal width, with graceful fallback.

    Returns:
        Terminal width in columns, or 80 if unable to determine
    """
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80


def normalize_title(title: str) -> str:
    """Remove notification counters from window titles.

    Removes patterns like:
    - "(7)" at start: "(7) WhatsApp" → "WhatsApp"
    - "(1)" at end: "Work/Job Hunting (1)" → "Work/Job Hunting"
    - "(2)" in middle: "Inbox (2) - Gmail" → "Inbox - Gmail"

    Used to aggregate similar window events across time by removing transient
    notification badges.

    Args:
        title: Original window title

    Returns:
        Title with notification counters removed and whitespace normalized
    """
    if not title:
        return title
    normalized = re.sub(r"\s*\(\d+\)\s*", " ", title)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def sanitize_title(title: str) -> str:
    """Clean window titles by removing emoji and unwanted Unicode.

    Preserves accented Latin characters (ñ, á, é, etc.) common in international
    window titles while filtering emoji and decorative symbols.

    Strategy:
    - ASCII (< 128): keep printable characters and whitespace
    - Latin-1 Supplement (0x0080-0x00FF): keep all (covers ñ, á, é, etc.)
    - Other ranges: keep only letters (Unicode category L*) and numbers (N*)

    Args:
        title: Window title potentially containing emoji/unwanted Unicode

    Returns:
        Cleaned title with emoji and symbols removed, accented chars preserved
    """
    if not title:
        return title
    title = normalize_title(title)
    result = []
    for c in title:
        code_point = ord(c)
        if code_point < 128:
            if c.isprintable() or c.isspace():
                result.append(c)
        elif 0x0080 <= code_point <= 0x00FF:
            result.append(c)
        else:
            category = unicodedata.category(c)
            if category[0] in ("L", "N"):
                result.append(c)
    return "".join(result)


def truncate_title(title: str, max_length: int = 60) -> str:
    """Truncate title to max_length with ellipsis if needed.

    Args:
        title: Title to truncate
        max_length: Maximum length before truncation (default 60)

    Returns:
        Original title if shorter than max_length, otherwise truncated with "…"
    """
    if not title:
        return title
    if len(title) <= max_length:
        return title
    return title[: max_length - 1] + "…"


def abbreviate_project_path(
    project: str, task: str = "", max_content_width: int = 100
) -> str:
    """Abbreviate hierarchical project path while preserving task description.

    For multi-level projects (e.g., "Platform > Web > Frontend"), keeps the
    most specific level (leaf) and abbreviates the root to first 5 chars.
    Single-level projects are returned unchanged.

    Args:
        project: Project path, potentially with " > " separators (hierarchical)
        task: Optional task name (used to decide abbreviation length)
        max_content_width: Maximum width before truncation (default 100)

    Returns:
        Abbreviated project path (e.g., "Platf... > Frontend")
    """
    if " > " not in project:
        return project

    parts = project.split(" > ")
    leaf = parts[-1]

    if len(parts) > 1:
        root = parts[0]
        root_abbrev = root[:5] + "..." if len(root) > 5 else root
        abbreviated = f"{root_abbrev} > {leaf}"
    else:
        abbreviated = leaf

    if task:
        full = f"{abbreviated} ▶▶ {task}"
        if len(full) <= max_content_width:
            return abbreviated

    return abbreviated


def format_timeline_columns(
    time_range: str,
    project: str,
    task: str,
    gaps: str,
    duration: str,
    project_width: int = 33,
    task_width: int = 40,
    no_project_sentinel: str = "No project assigned",
    right_align: bool = True,
) -> str:
    """Format timeline entry as fixed-width columns for alignment.

    Creates a columnar layout where project and task are in fixed-width columns,
    ensuring that gaps and duration stay aligned even when descriptions vary in length.
    Duration is right-aligned to terminal width when right_align=True.

    For "No project" entries, omits the task column decorator.

    Args:
        time_range: Time range like "00:00-11:30"
        project: Project name (e.g., "No project assigned" or "Ecosistema > Cultivo")
        task: Task name (e.g., "Revisar semillero" or "" for no project entries)
        gaps: Gap notation like "(3:48:32 AFK)" or "" if no gaps
        duration: Duration with productivity like "10:48:56  [prod  7%]"
        project_width: Fixed width for project column (default 33 chars)
        task_width: Fixed width for task column (default 40 chars)
        no_project_sentinel: Value that indicates "no project" (default "No project assigned")
        right_align: Right-align duration to terminal width (default True)

    Returns:
        Single-line formatted entry with fixed-width columns
    """
    # Build the line with fixed-width columns
    # Format: "time  ▶project_col   ▶▶task_col  gaps [padded to terminal width] duration"

    time_part = f"       {time_range}"  # Indent + time (7 spaces to align with date lines)

    # Project column: "▶ project_name" padded to fixed width
    project_part = f"▶ {project}".ljust(project_width + 2)  # +2 for "▶ "

    # Task column: "▶▶ task_name" padded to fixed width
    # IMPORTANT: Always pad to task_width to maintain column alignment
    # Special case: if project is "no project", skip task decorator (just padding)
    if project == no_project_sentinel:
        task_part = " " * (task_width + 4)
    elif task:
        # Pad the decorated task to the fixed column width
        task_part = f"▶▶ {task}".ljust(task_width + 4)  # +4 for "▶▶ "
    else:
        task_part = " " * (task_width + 4)

    # Build the complete line with fixed columns and right-aligned right section
    # Format: "time  project  task  [right-aligned: gaps  duration]"

    left_part = f"{time_part}  {project_part}  {task_part}"
    gaps_part = gaps if gaps else ""

    # Build the right section (gaps + duration) and right-align it
    if gaps_part:
        right_part = f"{gaps_part}  {duration}"
    else:
        right_part = duration

    # Right-align the right section to terminal width
    if right_align:
        width = get_terminal_width()
        # Pad left_part to push right_part to the right edge
        # Subtract 2 to account for the 2-space separator
        full_line = left_part.ljust(width - len(right_part) - 2) + "  " + right_part
    else:
        full_line = left_part + "  " + right_part

    # Trim excessive trailing spaces only at the very end
    return full_line.rstrip()


def format_timeline_line(
    left_part: str, duration_str: str = "", max_left_width: int = 100
) -> str:
    """Format timeline line with truncated content and right-aligned duration.

    CRITICAL DESIGN CHOICE (Phase 5 regression fix, 2026-07-02):
    ============================================================

    This function uses terminal-width based padding (ljust(width - len(duration) - 1))
    rather than fixed-column padding. This was chosen after a failed attempt to use
    fixed-column alignment (max_left_width=70), which:
      - Created 0-padding when content was already at max width
      - Resulted in duration appearing immediately after truncated content
      - Broke consolidated rendering with extra padding spaces

    The terminal-width approach works correctly for ALL rendering paths:
      1. Simple timeline (non-consolidated): Dynamic padding fills to screen width
      2. Consolidated+detail rendering: Works with varied content lengths
      3. Multi-day spanning: Handles proportional duration allocation

    ALGORITHM:
    ==========
    1. Truncate left_part to max_left_width chars if needed (add "..." if truncated)
    2. Pad left_part to (terminal_width - duration_length - 1) chars using ljust()
    3. Append single space + duration string

    EXAMPLE (terminal width 120, content 50 chars, duration "4:36:02" = 7 chars):
      left_part (before):   "     00:00 - 04:36  ▶ Project > Task"  (50 chars)
      left_part (after):    "     00:00 - 04:36  ▶ Project > Task                                         "  (padded to 112)
      final:                "     00:00 - 04:36  ▶ Project > Task                                          4:36:02"
                                                                    ^~112 chars padding~^1 space^duration

    PARAMETERS:
      left_part:        Pre-formatted content (time range + project/task + details)
      duration_str:     Duration string to right-align (e.g., "4:36:02", "0:13:47")
      max_left_width:   Maximum chars before truncation (default 100, used by consolidated rendering)

    RETURNS:
      Formatted line with left_part padded to terminal width and duration right-aligned

    NOTE:
      - Truncation adds "..." (3 chars) when left_part exceeds max_left_width
      - Terminal width fallback is 80 if detection fails
      - Lines naturally fit within terminal width by design
    """
    width = get_terminal_width()

    # Truncate left part if it exceeds max width
    if len(left_part) > max_left_width:
        left_part = left_part[: max_left_width - 3] + "..."

    # Right-align duration
    if duration_str:
        return left_part.ljust(width - len(duration_str) - 1) + " " + duration_str
    return left_part

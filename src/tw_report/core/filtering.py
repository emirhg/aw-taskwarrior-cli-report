"""
Unified event filtering logic for tw-report.

This module centralizes all filtering logic that was previously scattered
across tw-report.py in 5+ different locations. It provides a single,
consistent interface for filtering any type of entry (regular, AFK, OFFLINE, etc.).

ISSUES FIXED:
- Issue #1: Filters can now be applied to synthetic OFFLINE task slots
- Issue #3: All entry types now filtered consistently (not just AFK slots)
"""

from typing import Any, Dict, List, Optional

# Sentinel values (imported from tw-report.py)
NO_PROJECT = "No project assigned"
NO_TASK = "No task assigned"


class EventFilter:
    """
    Unified filtering logic for all entry types in timeline/hierarchical reports.

    Replaces scattered filter logic from:
    - apply_filters() function (lines 791-859 in tw-report.py)
    - Inline filtering in generate_timeline_data() (line 915)
    - Inline filtering in main() for gap_entries (lines 3822-3857)
    - Inline filtering for synthetic OFFLINE slots (lines 3720-3808)

    KEY FEATURE: Consistent behavior across entry types.
    App-level filtering (--app) is supported for both timeline and consolidation modes.
    """

    def __init__(
        self,
        project_patterns: Optional[List[str]] = None,
        task_patterns: Optional[List[str]] = None,
        app_patterns: Optional[List[str]] = None,
        exclude_projects: Optional[List[str]] = None,
        exclude_tasks: Optional[List[str]] = None,
        exclude_apps: Optional[List[str]] = None,
        exclude_non_project: bool = False,
        exact_match: bool = False,
        search_term: Optional[str] = None,
    ):
        """
        Initialize filter with configuration.

        Args:
            project_patterns: List of project name patterns to include
            task_patterns: List of task name patterns to include
            app_patterns: List of application name patterns to include
            exclude_projects: List of exact project names to exclude
            exclude_tasks: List of exact task names to exclude
            exclude_apps: List of exact app names to exclude
            exclude_non_project: If True, exclude entries without a project
            exact_match: If True, use exact matching instead of substring
            search_term: General search term (applies to projects and tasks)
        """
        self.project_patterns = project_patterns or []
        self.task_patterns = task_patterns or []
        self.app_patterns = app_patterns or []
        self.exclude_projects = exclude_projects or []
        self.exclude_tasks = exclude_tasks or []
        self.exclude_apps = exclude_apps or []
        self.exclude_non_project = exclude_non_project
        self.exact_match = exact_match

        # Add search term to patterns (search applies to projects and tasks)
        if search_term:
            self.project_patterns = [search_term] + self.project_patterns
            self.task_patterns = [search_term] + self.task_patterns

    def should_include_entry(self, entry: Dict[str, Any], entry_type: str = "regular") -> bool:
        """
        Universal filter decision for ANY entry type.

        This is the single method that replaces 5+ scattered filter checks
        throughout tw-report.py.

        Args:
            entry: Dictionary with keys like "project", "task", "app", "type", "duration", etc.
            entry_type: Type of entry being filtered:
                - "regular": Normal timeline/hierarchical entries
                - "afk": AFK (away from keyboard) slots
                - "offline": OFFLINE gap markers
                - "offline_task": Synthetic OFFLINE task slots (Issue #1 fix)
                - "gap": Any gap/break entry

        Returns:
            True if entry should be included in report
            False if entry should be filtered out

        ISSUE #3 FIX: All entry types now follow the same logical flow,
        ensuring consistent behavior. Previously, different filter logic
        was applied to different entry types, leading to inconsistencies.
        """
        # Extract entry fields with safe defaults
        project = entry.get("project", NO_PROJECT)
        task = entry.get("task", NO_TASK)
        app = entry.get("app", "")

        # --- STEP 1: Exclusions (highest priority) ---
        # If in exclusion list, always exclude (no other check matters)
        if self._is_excluded(project, self.exclude_projects):
            return False
        if self._is_excluded(task, self.exclude_tasks):
            return False
        if self._is_excluded(app, self.exclude_apps):
            return False

        # --- STEP 2: Handle --exclude-non-project flag ---
        # This is where Issue #1 and #3 are fixed
        if self.exclude_non_project:
            if entry_type in ("regular", "offline_task"):
                # For work entries, must have a tracked project
                # ISSUE #1 FIX: Synthetic OFFLINE task slots now checked here
                if project == NO_PROJECT:
                    return False
            elif entry_type in ("afk", "offline", "gap"):
                # For gaps/breaks, only exclude if completely untracked
                # (both project and task are unassigned or empty)
                # ISSUE #3 FIX: Now treat OFFLINE gaps same as AFK gaps
                task_unassigned = task == NO_TASK or task == "" or task is None
                if project == NO_PROJECT and task_unassigned:
                    return False

        # --- STEP 3: Handle inclusion patterns ---
        # If patterns specified, entry must match at least one
        # Combine all inclusion patterns
        all_patterns = self.project_patterns + self.task_patterns
        all_names = [project, task]

        # Check inclusion patterns (only if patterns specified)
        if all_patterns:
            if not self._matches_any(all_names, all_patterns):
                return False

        # Check app-specific filter (separate from project/task patterns)
        if self.app_patterns:
            if not self._matches_any([app], self.app_patterns):
                return False

        # Passed all filters - include this entry
        return True

    # --- Helper Methods ---

    def _matches_any(self, names: List[str], patterns: List[str]) -> bool:
        """
        Check if any name matches any pattern.

        Args:
            names: List of names to check (e.g., ["Project1", "Task1"])
            patterns: List of patterns to match against

        Returns:
            True if at least one name matches at least one pattern
            False if no matches found
        """
        if not patterns:
            return True  # No patterns = accept all

        for name in names:
            for pattern in patterns:
                if self._match_single(name, pattern):
                    return True
        return False

    def _match_single(self, name: str, pattern: str) -> bool:
        """
        Match a single name against a single pattern.

        Args:
            name: Name to check
            pattern: Pattern to match against

        Returns:
            True if name matches pattern (exact or substring based on exact_match flag)
            False if no match
        """
        if not name or not pattern:
            return False

        if self.exact_match:
            # Exact match (case-insensitive)
            return name.lower() == pattern.lower()
        else:
            # Substring match (case-insensitive)
            return pattern.lower() in name.lower()

    def _is_excluded(self, name: str, exclusions: List[str]) -> bool:
        """
        Check if name is in the exclusion list.

        Exclusions always use exact match (case-insensitive), never substring.

        Args:
            name: Name to check
            exclusions: List of exact names to exclude

        Returns:
            True if name is in exclusion list
            False if name is not excluded
        """
        if not name or not exclusions:
            return False

        # Exact match (case-insensitive)
        return any(name.lower() == e.lower() for e in exclusions)

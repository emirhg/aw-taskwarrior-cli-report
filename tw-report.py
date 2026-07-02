#!/bin/env python
# author: "Emir Herrera González" <emir.herrera@gmail.com>
#
# Generates a timesheet report using data from ActivityWatch buckets.
#
# This script fetches activity data for the specified period, correlates it with
# Taskwarrior tasks, and generates a hierarchical report showing time spent on
# projects, tasks, and specific applications or categories.
#
# By default, it reports on today's activity, excluding time spent away from
# the keyboard (AFK) and only showing activity that occurred during a
# tracked Taskwarrior task.
#
# Features:
# - Human-readable time periods (:today, :week, :month, etc.)
# - Correlation with Taskwarrior projects and tasks.
# - Categorization of activities (e.g., Coding, Communication).
# - Hierarchical, terminal-friendly report format.
# - Customizable through command-line arguments and a categories JSON file.
#
# This module serves as the command-line entry point for tw-report.
# The actual orchestration logic is in tw_report.cli.main.

from tw_report.cli.main import main

if __name__ == "__main__":
    main()

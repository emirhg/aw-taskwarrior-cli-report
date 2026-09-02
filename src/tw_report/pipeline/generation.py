"""
Timeline data generation - PHASE 2 REFACTOR: Migrated to unified builder.

This module previously contained 5 separate slot generators. As of Phase 2 refactor,
all slot construction has been consolidated into build_timeslot_timeline() in
src/tw_report/core/timeslot_builder.py.

This module is now deprecated and kept only for historical reference.

NOTE: All legacy generator functions have been removed in Phase 2 refactor:
# - generate_afk_and_offline_slots() → build_timeslot_timeline()
# - generate_partitioned_task_slots() → build_timeslot_timeline()
# - generate_untracked_gap_events() → build_timeslot_timeline()
# - convert_active_periods_to_slots() → build_timeslot_timeline()
# - generate_timeline_data() → Integrated into main.py via builder
#
# The unified builder (build_timeslot_timeline) handles all slot construction,
# guaranteeing non-overlapping, properly-classified slots with correct duration breakdowns.

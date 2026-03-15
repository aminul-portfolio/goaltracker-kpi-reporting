# apps/exports/contracts.py
"""
CSV export contracts (column order). Keep these stable.
These are part of the Proof Pack "dataset contract".
"""

# Contract versions
EXPORT_CONTRACT_V1 = "exports.v1"
EXPORT_CONTRACT_V2 = "exports.v2"

# Backwards-compat alias (older code may still read this)
# If you want, you can change this to V1, but V2 is recommended going forward.
EXPORT_CONTRACT_VERSION = EXPORT_CONTRACT_V2


# -------------------------
# v1 headers (legacy)
# -------------------------
SESSIONS_V1_HEADERS = [
    "session_id",
    "goal",
    "category",
    "start_at_local",
    "end_at_local",
    "duration_minutes",
    "effective_minutes",
    "quality_level",
    "multiplier",
    "mae_block",
    "deliverable",
    "notes",
]

DAY_SNAPSHOTS_V1_HEADERS = [
    "day_key",
    "goal",
    "wake_at_local",
    "sleep_at_local",
    "target_minutes",
    "raw_minutes",
    "effective_minutes",
    "effective_pct",
    "rating",
    "reflection",
]


# -------------------------
# v2 headers (Power BI)
# -------------------------
FACT_SESSIONS_V2_HEADERS = [
    "session_id",
    "goal_id",
    "category_id",
    "work_item_id",
    "date",               # local date key (YYYY-MM-DD) -> join to dim_date[date]
    "start_at_local",
    "end_at_local",
    "duration_minutes",
    "effective_minutes",
    "quality_level",
    "multiplier",
    "mae_block",
    "deliverable",
    "notes",
    "created_at_utc",
]

DIM_GOAL_V2_HEADERS = [
    "goal_id",
    "goal_name",
    "start_date",
    "duration_days",
    "is_active",
]

DIM_CATEGORY_V2_HEADERS = [
    "category_id",
    "goal_id",
    "category_name",
    "sort_order",
    "archived",
]

DIM_WORK_ITEM_V2_HEADERS = [
    "work_item_id",
    "goal_id",
    "title",
    "status",
    "planned_minutes",
    "due_date",
    "archived",
]

DIM_DATE_V2_HEADERS = [
    "date",          # YYYY-MM-DD
    "year",
    "month",
    "month_name",
    "day",
    "day_name",
    "iso_week",
    "week_start_date",
    "is_weekend",
]

SPRINT_SETTINGS_V2_HEADERS = [
    "sprint_start_date",
    "sprint_days",
    "sprint_end_date",
]

DIM_TAG_GROUP_V2_HEADERS = [
    "tag_group_id",
    "name",
    "sort_order",
    "archived",
]

DIM_TAG_V2_HEADERS = [
    "tag_id",
    "tag_group_id",
    "name",
    "sort_order",
    "archived",
]

BRIDGE_SESSION_TAG_V2_HEADERS = [
    "session_id",
    "tag_id",
    "created_at_utc",
]

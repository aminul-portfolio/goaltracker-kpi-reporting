# apps/exports/urls.py
from django.urls import path
from . import views

app_name = "exports"

urlpatterns = [
    # ✅ index page
    path("", views.exports_index, name="index"),

    # v1
    path("sessions.csv", views.export_sessions_csv, name="sessions_csv"),
    path("day_snapshots.csv", views.export_day_snapshots_csv, name="day_snapshots_csv"),

    # v2
    path("v2/fact_sessions.csv", views.export_fact_sessions_v2_csv, name="fact_sessions_v2_csv"),
    path("v2/dim_goal.csv", views.export_dim_goal_v2_csv, name="dim_goal_v2_csv"),
    path("v2/dim_category.csv", views.export_dim_category_v2_csv, name="dim_category_v2_csv"),
    path("v2/dim_work_item.csv", views.export_dim_work_item_v2_csv, name="dim_work_item_v2_csv"),
    path("v2/dim_date.csv", views.export_dim_date_v2_csv, name="dim_date_v2_csv"),
    path("v2/sprint_settings.csv", views.export_sprint_settings_v2_csv, name="sprint_settings_v2_csv"),

    # optional tags
    path("v2/dim_tag_group.csv", views.export_dim_tag_group_v2_csv, name="dim_tag_group_v2_csv"),
    path("v2/dim_tag.csv", views.export_dim_tag_v2_csv, name="dim_tag_v2_csv"),
    path("v2/bridge_session_tag.csv", views.export_bridge_session_tag_v2_csv, name="bridge_session_tag_v2_csv"),
]

# apps/goals/admin.py
from django.contrib import admin

from .models import Goal, Category, TrackerSettings
from .models import Goal, Category, TrackerSettings, WorkItem

@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "start_date", "duration_days", "monthly_target_minutes", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "archived")
    list_filter = ("archived",)
    search_fields = ("name",)
    ordering = ("archived", "sort_order", "name")
    list_editable = ("sort_order", "archived")


@admin.register(TrackerSettings)
class TrackerSettingsAdmin(admin.ModelAdmin):
    """
    Singleton settings. Keep it simple: one row only.
    """
    list_display = (
        "target_bedtime",
        "daily_target_minutes",
        "net_points_cap",
        "mae_noon_cutoff",
        "mae_evening_cutoff",
        "exceptional_min_minutes",
        "exceptional_max_per_day",
        "enforce_active_day_bounds",
    )

    def has_add_permission(self, request):
        # allow only one settings row
        count = TrackerSettings.objects.count()
        return count == 0

    def has_delete_permission(self, request, obj=None):
        # prevent accidental deletion
        return False
# File: apps/goals/admin.py



@admin.register(WorkItem)
class WorkItemAdmin(admin.ModelAdmin):
    list_display = ("name", "goal", "status", "planned_minutes", "due_date", "archived", "sort_order", "created_at")
    list_filter = ("status", "archived", "goal")
    search_fields = ("name", "goal__name")
    ordering = ("archived", "sort_order", "name")
    list_editable = ("status", "planned_minutes", "due_date", "archived", "sort_order")
    readonly_fields = ("created_at",)

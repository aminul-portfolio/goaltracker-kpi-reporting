# apps/tracker/admin.py
from django.contrib import admin

from .models import ActiveDay, ActiveTimer, Session

# Optional: only if you added tag models
try:
    from .models import TagGroup, Tag, SessionTag
except Exception:
    TagGroup = Tag = SessionTag = None


@admin.register(ActiveDay)
class ActiveDayAdmin(admin.ModelAdmin):
    list_display = ("goal", "wake_at", "sleep_at", "is_open", "updated_at", "created_at")
    list_filter = ("is_open", "goal")
    ordering = ("-wake_at",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ActiveTimer)
class ActiveTimerAdmin(admin.ModelAdmin):
    list_display = (
        "goal",
        "category",
        "quality_level",
        "deliverable",
        "is_running",
        "current_start_at",
        "accumulated_minutes",
        "updated_at",
    )
    list_filter = ("is_running", "quality_level", "goal", "category")
    ordering = ("-updated_at",)
    readonly_fields = ("updated_at",)


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = (
        "goal",
        "category",
        "work_item",  # safe method below
        "quality_level",
        "start_at",
        "end_at",
        "duration_minutes",
        "effective_minutes",
        "mae_block",
        "deliverable",
        "created_at",
    )
    list_filter = ("goal", "category", "quality_level", "mae_block")
    search_fields = ("deliverable", "notes")
    ordering = ("-start_at",)
    readonly_fields = ("created_at",)

    def work_item(self, obj):
        wi = getattr(obj, "work_item", None)
        return getattr(wi, "name", "") if wi else ""
    work_item.short_description = "WorkItem"


# Tags admin (only if models exist)
if TagGroup:
    @admin.register(TagGroup)
    class TagGroupAdmin(admin.ModelAdmin):
        list_display = ("name", "sort_order", "archived", "created_at")
        list_filter = ("archived",)
        search_fields = ("name",)
        ordering = ("archived", "sort_order", "name")
        list_editable = ("sort_order", "archived")
        readonly_fields = ("created_at",)

if Tag:
    @admin.register(Tag)
    class TagAdmin(admin.ModelAdmin):
        list_display = ("name", "group", "sort_order", "archived", "created_at")
        list_filter = ("archived", "group")
        search_fields = ("name", "group__name")
        ordering = ("group", "archived", "sort_order", "name")
        list_editable = ("sort_order", "archived")
        readonly_fields = ("created_at",)

if SessionTag:
    @admin.register(SessionTag)
    class SessionTagAdmin(admin.ModelAdmin):
        list_display = ("session", "tag", "created_at")
        list_filter = ("tag",)
        search_fields = ("session__id", "tag__name")
        ordering = ("-created_at",)
        readonly_fields = ("created_at",)

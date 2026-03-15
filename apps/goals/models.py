# apps/goals/models.py
from datetime import date, time

from django.db import models


class Goal(models.Model):
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    start_date = models.DateField(default=date.today)
    duration_days = models.PositiveIntegerField(default=30)

    monthly_target_minutes = models.PositiveIntegerField(default=19800)  # 330h
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class TrackerSettings(models.Model):
    """
    Singleton settings row.
    """

    # Time + targets
    target_bedtime = models.TimeField(default=time(23, 59))
    daily_target_minutes = models.PositiveIntegerField(default=660)  # 11h
    monthly_target_minutes = models.PositiveIntegerField(default=19800)  # optional, keep goal override
    net_points_cap = models.IntegerField(default=4)

    # MAE cutoffs
    mae_noon_cutoff = models.TimeField(default=time(12, 0))
    mae_evening_cutoff = models.TimeField(default=time(17, 0))

    # Exceptional rules
    exceptional_min_minutes = models.PositiveIntegerField(default=45)
    exceptional_max_per_day = models.PositiveIntegerField(default=2)

    # ✅ NEW: strict session bounds (Wake -> now) while day is open
    enforce_active_day_bounds = models.BooleanField(default=True)

    def __str__(self):
        return "TrackerSettings"



class WorkItemStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    IN_PROGRESS = "in_progress", "In Progress"
    DELIVERED = "delivered", "Delivered"
    BLOCKED = "blocked", "Blocked"


class WorkItem(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="work_items")
    name = models.CharField(max_length=160)

    status = models.CharField(
        max_length=20,
        choices=WorkItemStatus.choices,
        default=WorkItemStatus.PLANNED,
    )

    planned_minutes = models.PositiveIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True)

    sort_order = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["goal", "status"]),
            models.Index(fields=["archived", "sort_order", "name"]),
        ]
        ordering = ["archived", "sort_order", "name"]

    def __str__(self):
        return self.name

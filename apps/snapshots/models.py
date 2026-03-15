# apps/snapshots/models.py
from __future__ import annotations

from datetime import timedelta

from django.db import models

from apps.goals.models import Goal


class DaySnapshot(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="day_snapshots")

    # Day key is the London-local date of wake_at
    day_key = models.DateField()

    wake_at = models.DateTimeField()
    sleep_at = models.DateTimeField()

    sessions_count = models.PositiveIntegerField(default=0)
    exceptional_count = models.PositiveIntegerField(default=0)

    raw_minutes = models.PositiveIntegerField(default=0)
    effective_minutes = models.PositiveIntegerField(default=0)

    target_minutes = models.PositiveIntegerField(default=0)

    raw_pct = models.FloatField(default=0.0)
    effective_pct = models.FloatField(default=0.0)

    rating = models.CharField(max_length=20, default="Good")  # Good / Better / Excellent / Behind
    reflection = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("goal", "day_key"),)
        indexes = [
            models.Index(fields=["goal", "day_key"]),
            models.Index(fields=["day_key"]),
        ]
        ordering = ["-day_key"]

    def __str__(self) -> str:
        return f"{self.goal_id} {self.day_key}"


class WeekSnapshot(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="week_snapshots")

    week_start = models.DateField()  # Monday
    week_end = models.DateField()    # next Monday (exclusive)

    days_count = models.PositiveIntegerField(default=0)

    raw_minutes = models.PositiveIntegerField(default=0)
    effective_minutes = models.PositiveIntegerField(default=0)

    target_minutes = models.PositiveIntegerField(default=0)

    raw_pct = models.FloatField(default=0.0)
    effective_pct = models.FloatField(default=0.0)

    rating = models.CharField(max_length=20, default="Good")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("goal", "week_start"),)
        indexes = [
            models.Index(fields=["goal", "week_start"]),
            models.Index(fields=["week_start"]),
        ]
        ordering = ["-week_start"]

    @property
    def week_end_inclusive(self):
        """
        Display helper: inclusive end date (Sunday) for a stored exclusive end (next Monday).
        """
        if not self.week_end:
            return None
        return self.week_end - timedelta(days=1)

    def __str__(self) -> str:
        return f"{self.goal_id} {self.week_start}"
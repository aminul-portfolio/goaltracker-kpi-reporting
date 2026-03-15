# apps/goals/management/commands/seed_demo.py
from __future__ import annotations

from datetime import date, time

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.goals.models import Goal, Category, TrackerSettings


DEFAULT_CATEGORIES = [
    ("Deep Work (Project)", 10),
    ("Learning (SQL/BI)", 20),
    ("Interview Prep", 30),
    ("Portfolio Polish", 40),
    ("Admin / Planning", 50),
    ("Health / Workout", 60),
]


class Command(BaseCommand):
    help = "Seed demo data: Goal + Categories + TrackerSettings (safe to re-run)."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        # 1) Settings (singleton)
        settings, created = TrackerSettings.objects.get_or_create(
            defaults={
                "target_bedtime": time(23, 59),
                "daily_target_minutes": 660,  # 11h
                "net_points_cap": 4,
                "mae_noon_cutoff": time(12, 0),
                "mae_evening_cutoff": time(17, 0),
                "exceptional_min_minutes": 45,
                "exceptional_max_per_day": 2,
                "enforce_active_day_bounds": True,
            }
        )

        # 2) Categories (idempotent)
        for name, sort_order in DEFAULT_CATEGORIES:
            Category.objects.get_or_create(
                name=name,
                defaults={"sort_order": sort_order, "archived": False},
            )

        # 3) Goal (make exactly one active goal)
        # deactivate any existing active goals (keeps history)
        Goal.objects.filter(is_active=True).update(is_active=False)

        goal, goal_created = Goal.objects.get_or_create(
            name="30-Day Data Analyst Sprint (330h)",
            defaults={
                "is_active": True,
                "start_date": date.today(),
                "duration_days": 30,
                "monthly_target_minutes": 19800,  # 330h
            },
        )
        if not goal.is_active:
            goal.is_active = True
            goal.save(update_fields=["is_active"])

        self.stdout.write(self.style.SUCCESS("✅ Seed complete"))
        self.stdout.write(f"- TrackerSettings: {'created' if created else 'exists'} (id={settings.id})")
        self.stdout.write(f"- Categories ensured: {len(DEFAULT_CATEGORIES)}")
        self.stdout.write(f"- Active Goal: {goal.name} (id={goal.id})")

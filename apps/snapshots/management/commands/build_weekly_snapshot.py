# apps/snapshots/management/commands/build_weekly_snapshot.py
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from zoneinfo import ZoneInfo

from apps.goals.models import Goal, TrackerSettings
from apps.snapshots.services import build_week_snapshot

TZ = ZoneInfo("Europe/London")


class Command(BaseCommand):
    help = "Build the current week's WeekSnapshot for the active goal."

    def handle(self, *args, **kwargs):
        goal = Goal.objects.filter(is_active=True).first()
        if not goal:
            self.stdout.write(self.style.ERROR("No active goal."))
            return

        settings = TrackerSettings.objects.first()

        now_local = timezone.localtime(timezone.now(), TZ).date()
        # Monday start
        weekday = now_local.weekday()  # Mon=0
        week_start = now_local - timedelta(days=weekday)

        snap = build_week_snapshot(goal=goal, week_start_local_date=week_start, settings=settings)
        self.stdout.write(self.style.SUCCESS(f"✅ WeekSnapshot built: {snap.week_start}"))

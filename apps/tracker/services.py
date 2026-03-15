# apps/snapshots/services.py
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.utils import timezone

from apps.tracker.enums import QualityLevel
from apps.tracker.models import Session
from apps.snapshots.models import DaySnapshot, WeekSnapshot

TZ = ZoneInfo("Europe/London")


def _sum_minutes(qs, field: str) -> int:
    v = qs.aggregate(total=Sum(field))["total"]
    return int(v or 0)


def _percent(done: int, target: int) -> float:
    if not target:
        return 0.0
    return round((done / target) * 100.0, 1)


def _rating_from_pct(eff_pct: float) -> str:
    if eff_pct >= 110:
        return "Excellent"
    if eff_pct >= 100:
        return "Better"
    if eff_pct >= 80:
        return "Good"
    return "Behind"


def build_day_snapshot(
    *,
    goal,
    wake_at,
    sleep_at,
    close_day: bool,
    reflection: str,
    settings=None,
):
    """
    Build/Upsert DaySnapshot for the London-local date of wake_at.
    Uses sessions with start_at in [wake_at, sleep_at).
    """
    now = timezone.now()
    sleep_at = min(sleep_at, now)

    day_key = timezone.localtime(wake_at, TZ).date()

    qs = Session.objects.filter(goal=goal, start_at__gte=wake_at, start_at__lt=sleep_at)

    raw = _sum_minutes(qs, "duration_minutes")
    eff = _sum_minutes(qs, "effective_minutes")

    sessions_count = qs.count()
    exceptional_count = qs.filter(quality_level=QualityLevel.EXCEPTIONAL).count()

    target_minutes = int(getattr(settings, "daily_target_minutes", 660) if settings else 660)

    raw_pct = _percent(raw, target_minutes)
    eff_pct = _percent(eff, target_minutes)

    rating = _rating_from_pct(eff_pct)

    snap, _ = DaySnapshot.objects.update_or_create(
        goal=goal,
        day_key=day_key,
        defaults={
            "wake_at": wake_at,
            "sleep_at": sleep_at,
            "sessions_count": sessions_count,
            "exceptional_count": exceptional_count,
            "raw_minutes": raw,
            "effective_minutes": eff,
            "target_minutes": target_minutes,
            "raw_pct": raw_pct,
            "effective_pct": eff_pct,
            "rating": rating,
            "reflection": (reflection or "").strip()[:200],
        },
    )
    return snap


def build_week_snapshot(*, goal, week_start_local_date, settings=None):
    """
    Build/Upsert WeekSnapshot for a Monday week_start (London local date).
    Week range: [Mon 00:00, next Mon 00:00) London.
    Aggregates DaySnapshots if they exist, else aggregates Sessions.
    """
    week_start_local = timezone.make_aware(datetime.combine(week_start_local_date, time.min), TZ)
    week_end_local = week_start_local + timedelta(days=7)

    week_start = week_start_local.astimezone(timezone.utc)
    week_end = week_end_local.astimezone(timezone.utc)

    # Prefer day snapshots (consistent with Wake->Sleep)
    days = DaySnapshot.objects.filter(
        goal=goal,
        day_key__gte=week_start_local_date,
        day_key__lt=week_end_local.date(),
    )

    if days.exists():
        raw = int(days.aggregate(total=Sum("raw_minutes"))["total"] or 0)
        eff = int(days.aggregate(total=Sum("effective_minutes"))["total"] or 0)
        days_count = days.count()
    else:
        qs = Session.objects.filter(goal=goal, start_at__gte=week_start, start_at__lt=week_end)
        raw = _sum_minutes(qs, "duration_minutes")
        eff = _sum_minutes(qs, "effective_minutes")
        days_count = 0

    daily_target = int(getattr(settings, "daily_target_minutes", 660) if settings else 660)
    target_minutes = daily_target * 7

    raw_pct = _percent(raw, target_minutes)
    eff_pct = _percent(eff, target_minutes)
    rating = _rating_from_pct(eff_pct)

    snap, _ = WeekSnapshot.objects.update_or_create(
        goal=goal,
        week_start=week_start_local_date,
        defaults={
            "week_end": week_end_local.date(),
            "days_count": days_count,
            "raw_minutes": raw,
            "effective_minutes": eff,
            "target_minutes": target_minutes,
            "raw_pct": raw_pct,
            "effective_pct": eff_pct,
            "rating": rating,
        },
    )
    return snap
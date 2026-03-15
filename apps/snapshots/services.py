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
    # Simple, explainable labels
    if eff_pct >= 110:
        return "Excellent"
    if eff_pct >= 100:
        return "Better"
    if eff_pct >= 80:
        return "Good"
    return "Behind"


def _day_bounds_local(day_key):
    """
    London-local calendar day bounds: [00:00, next 00:00).
    Returns (day_start_local, day_end_local).
    """
    day_start_local = timezone.make_aware(datetime.combine(day_key, time.min), TZ)
    day_end_local = day_start_local + timedelta(days=1)
    return day_start_local, day_end_local


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
    IMPORTANT: Session aggregation is calendar-day based (London local day_key),
    not only wake/sleep window, so snapshots cannot drift from Sessions.
    """
    now = timezone.now()

    # London-local calendar day (derived from wake_at)
    day_key = timezone.localtime(wake_at, TZ).date()

    # Calendar-day window (London local)
    day_start_local, day_end_local = _day_bounds_local(day_key)

    # Clamp any stored sleep_at to now + day end (avoid future)
    sleep_at = min(sleep_at, now, day_end_local)

    # Sessions counted for the calendar day (London)
    window_end = min(day_end_local, now)
    qs = Session.objects.filter(
        goal=goal,
        start_at__gte=day_start_local,
        start_at__lt=window_end,
    )

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


def upsert_day_snapshot_from_sessions(*, goal, day_key, settings=None):
    """
    Recompute DaySnapshot for a London-local day_key from Sessions.
    Preserves existing wake_at/sleep_at/reflection if already stored.
    This is designed for signals and bulk repair.
    """
    now = timezone.now()

    day_start_local, day_end_local = _day_bounds_local(day_key)
    window_end = min(day_end_local, now)

    qs = Session.objects.filter(
        goal=goal,
        start_at__gte=day_start_local,
        start_at__lt=window_end,
    )

    raw = _sum_minutes(qs, "duration_minutes")
    eff = _sum_minutes(qs, "effective_minutes")

    sessions_count = qs.count()
    exceptional_count = qs.filter(quality_level=QualityLevel.EXCEPTIONAL).count()

    target_minutes = int(getattr(settings, "daily_target_minutes", 660) if settings else 660)

    raw_pct = _percent(raw, target_minutes)
    eff_pct = _percent(eff, target_minutes)

    rating = _rating_from_pct(eff_pct)

    existing = (
        DaySnapshot.objects.filter(goal=goal, day_key=day_key)
        .only("wake_at", "sleep_at", "reflection")
        .first()
    )

    wake_at = existing.wake_at if (existing and existing.wake_at) else day_start_local
    sleep_at = existing.sleep_at if (existing and existing.sleep_at) else window_end
    sleep_at = min(sleep_at, window_end)  # never beyond window_end
    reflection = (existing.reflection if existing else "")[:200]

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
    week_start_local, _ = _day_bounds_local(week_start_local_date)
    week_end_local = week_start_local + timedelta(days=7)

    # Prefer day snapshots (consistent with day_key)
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
        qs = Session.objects.filter(
            goal=goal,
            start_at__gte=week_start_local,
            start_at__lt=week_end_local,
        )
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
# apps/snapshots/views.py
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from datetime import UTC, date, datetime, timedelta

from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils import timezone

from apps.goals.models import Goal, TrackerSettings
from apps.goals.rbac import require_login
from apps.tracker.models import Session
from apps.snapshots.models import DaySnapshot, WeekSnapshot
from apps.snapshots.services import build_week_snapshot

TZ = ZoneInfo("Europe/London")


def _get_active_goal():
    # Deterministic: avoids “random first()” when multiple active goals exist.
    return Goal.objects.filter(is_active=True).order_by("-id").first()


def _safe_settings():
    s = TrackerSettings.objects.first()
    if s:
        return s

    # Minimal fallback so History page can still refresh week snapshot.
    class _S:
        daily_target_minutes = 660  # 11h
        exceptional_max_per_day = 2

    return _S()


def _day_bounds_local(day_key: date):
    """
    London-local calendar day bounds: [00:00, next 00:00).
    Returns (day_start_local, day_end_local).
    """
    day_start_local = timezone.make_aware(datetime.combine(day_key, time.min), TZ)
    day_end_local = day_start_local + timedelta(days=1)
    return day_start_local, day_end_local


def _normalise_week_start_local(d: date) -> date:
    """Return the Monday (ISO week start) for a given local date."""
    return d - timedelta(days=d.weekday())


@require_login
def history(request):
    goal = _get_active_goal()
    if not goal:
        return render(request, "snapshots/history.html", {"error": "No active goal set."})

    now_utc = timezone.now()
    now_local = timezone.localtime(now_utc, TZ)

    # Refresh current ISO week snapshot (safe each request; service should update_or_create)
    settings = _safe_settings()
    week_start_local = _normalise_week_start_local(now_local.date())

    try:
        build_week_snapshot(
            goal=goal,
            week_start_local_date=week_start_local,
            settings=settings,
        )
    except Exception:
        # Non-fatal: still show history, but warn.
        messages.warning(request, "Could not refresh this week snapshot (showing last saved values).")

    days = DaySnapshot.objects.filter(goal=goal).order_by("-day_key")[:30]
    weeks = WeekSnapshot.objects.filter(goal=goal).order_by("-week_start")[:12]

    return render(
        request,
        "snapshots/history.html",
        {
            "goal": goal,
            "now_local": now_local,
            "days": days,
            "weeks": weeks,
        },
    )


@require_login
def day_detail(request, day_key: str):
    goal = _get_active_goal()
    if not goal:
        return render(request, "snapshots/day_detail.html", {"error": "No active goal set."})

    try:
        d = date.fromisoformat(day_key)
    except ValueError:
        messages.error(request, "Invalid day key.")
        return redirect("snapshots:history")

    snap = DaySnapshot.objects.filter(goal=goal, day_key=d).first()
    if not snap:
        # Helpful hint: snapshot exists but under a different goal
        alt = DaySnapshot.objects.filter(day_key=d).select_related("goal").first()
        if alt and alt.goal_id != goal.id:
            messages.error(
                request,
                "No DaySnapshot for the active goal. "
                f"This date exists under a different goal (id={alt.goal_id}). "
                "Activate the correct goal or rebuild snapshots for the active goal."
            )
        else:
            messages.error(request, "No DaySnapshot found for this date.")
        return redirect("snapshots:history")

    # IMPORTANT:
    # DaySnapshot totals are calendar-day based, so this list must match that same scope.
    day_start_local, day_end_local = _day_bounds_local(d)
    day_start_utc = day_start_local.astimezone(UTC)
    day_end_utc = day_end_local.astimezone(UTC)

    now_utc = timezone.now()

    # Clamp scope end:
    # - past day: scope_end = day_end
    # - today: scope_end = now
    # - future day: scope_end = day_start (empty range, clean UI)
    if now_utc <= day_start_utc:
        scope_end_utc = day_start_utc
    else:
        scope_end_utc = min(day_end_utc, now_utc)

    sessions = (
        Session.objects.filter(goal=goal, start_at__gte=day_start_utc, start_at__lt=scope_end_utc)
        .select_related("category")
        .order_by("-start_at")
    )

    return render(
        request,
        "snapshots/day_detail.html",
        {
            "goal": goal,
            "now_local": timezone.localtime(now_utc, TZ),
            "snap": snap,
            "sessions": sessions,
            # Template display (so “Scope” matches the same range as session list)
            "scope_start_at": day_start_utc,
            "scope_end_at": scope_end_utc,
        },
    )


@require_login
def week_detail(request, week_start: str):
    goal = _get_active_goal()
    if not goal:
        return render(request, "snapshots/week_detail.html", {"error": "No active goal set."})

    try:
        ws = date.fromisoformat(week_start)
    except ValueError:
        messages.error(request, "Invalid week key.")
        return redirect("snapshots:history")

    # Force Monday keys (prevents “mid-week” URLs producing confusing ranges)
    ws_monday = _normalise_week_start_local(ws)
    if ws != ws_monday:
        messages.info(request, "Adjusted week start to Monday for ISO week alignment.")
        return redirect("snapshots:week_detail", week_start=ws_monday.isoformat())

    settings = _safe_settings()

    # Always refresh to avoid stale week rows
    try:
        snap = build_week_snapshot(goal=goal, week_start_local_date=ws_monday, settings=settings)
    except Exception:
        messages.error(request, "Could not build week snapshot.")
        return redirect("snapshots:history")

    return render(
        request,
        "snapshots/week_detail.html",
        {
            "goal": goal,
            "now_local": timezone.localtime(timezone.now(), TZ),
            "snap": snap,
        },
    )
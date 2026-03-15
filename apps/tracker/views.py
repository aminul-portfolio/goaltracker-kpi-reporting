# apps/tracker/views.py  (today_view only)

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.shortcuts import render
from django.utils import timezone
from datetime import timezone as dt_timezone

from apps.goals.models import Category, Goal
from apps.goals.rbac import require_login
from apps.tracker.models import Session
from apps.tracker.services.active_state import active_day_for, active_timer_for, require_open_day

TZ = ZoneInfo("Europe/London")


def _get_active_goal():
    return Goal.objects.filter(is_active=True).order_by("-id").first()


def _categories_qs(goal: Goal):
    try:
        Category._meta.get_field("goal")
        return Category.objects.filter(goal=goal).order_by("name")
    except Exception:
        return Category.objects.all().order_by("name")


def _today_bounds_utc(now_local):
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)
    return day_start_local.astimezone(dt_timezone.utc), day_end_local.astimezone(dt_timezone.utc)


@require_login
def today_view(request):
    goal = _get_active_goal()
    if not goal:
        return render(request, "tracker/today.html", {"error": "No active goal set."})

    now = timezone.now()
    now_local = timezone.localtime(now, TZ)

    # -------------------------
    # Day (open + boundary flags)
    # -------------------------
    open_day = require_open_day(goal)  # open day only
    day_is_open = bool(open_day)

    # active_day for display (show last known day even if closed)
    active_day = open_day or active_day_for(goal)

    active_day_local_date = (
        timezone.localtime(open_day.wake_at, TZ).date()
        if (day_is_open and getattr(open_day, "wake_at", None))
        else None
    )
    day_is_today = bool(day_is_open and active_day_local_date == now_local.date())
    day_boundary_blocked = bool(day_is_open and not day_is_today)

    # -------------------------
    # Timer (state flags)
    # -------------------------
    timer = active_timer_for(goal)
    timer_is_running = bool(timer and getattr(timer, "is_running", False))

    timer_accum = int(getattr(timer, "accumulated_minutes", 0) or 0) if timer else 0
    timer_has_start = bool(timer and getattr(timer, "current_start_at", None))
    timer_is_paused = bool(timer and (not timer_is_running) and timer_accum > 0)

    # If a running timer started “yesterday” (London), Pause should be blocked
    timer_crossed_midnight = False
    if timer_is_running and timer_has_start:
        timer_crossed_midnight = (
            timezone.localtime(timer.current_start_at, TZ).date() != now_local.date()
        )

    # -------------------------
    # Button permissions (UI mirrors backend truth)
    # -------------------------
    can_start = bool(
        day_is_open
        and day_is_today
        and (not timer_is_running)
        and (timer_accum == 0)
        and (not timer_has_start)
    )

    can_pause = bool(
        day_is_open
        and day_is_today
        and timer_is_running
        and (not timer_crossed_midnight)
    )

    can_resume = bool(
        day_is_open
        and day_is_today
        and (not timer_is_running)
        and (timer_accum > 0)
    )

    # Stop+Save available if there's anything to save/clear
    can_stop = bool(timer and (timer_is_running or timer_is_paused or timer_has_start or timer_accum > 0))

    # ✅ Template-friendly “no-parentheses” flags
    timer_fields_disabled = bool(
        (not day_is_open)
        or timer_is_running
        or (day_boundary_blocked and (not timer_is_paused))
    )
    end_day_disabled = bool(can_stop)

    # -------------------------
    # Today sessions (London-day window)
    # -------------------------
    day_start_utc, day_end_utc = _today_bounds_utc(now_local)
    sessions = (
        Session.objects.filter(goal=goal, start_at__gte=day_start_utc, start_at__lt=day_end_utc)
        .select_related("category")
        .order_by("start_at", "id")
    )

    ctx = {
        "now_local": now_local,
        "goal": goal,

        # Day
        "active_day": active_day,
        "day_is_open": day_is_open,
        "active_day_local_date": active_day_local_date,
        "day_is_today": day_is_today,
        "day_boundary_blocked": day_boundary_blocked,
        "end_day_disabled": end_day_disabled,

        # Timer
        "timer": timer,
        "timer_is_running": timer_is_running,
        "timer_is_paused": timer_is_paused,
        "timer_crossed_midnight": timer_crossed_midnight,
        "timer_fields_disabled": timer_fields_disabled,

        # Buttons
        "can_start": can_start,
        "can_pause": can_pause,
        "can_resume": can_resume,
        "can_stop": can_stop,

        # Lists
        "sessions": sessions,
        "categories": _categories_qs(goal),
    }
    return render(request, "tracker/today.html", ctx)
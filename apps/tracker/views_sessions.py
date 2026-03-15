# apps/tracker/views_sessions.py
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo
from datetime import UTC

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.goals.models import Goal, TrackerSettings
from apps.goals.rbac import require_login
from apps.tracker.forms import SessionQuickAddForm
from apps.tracker.models import ActiveDay
from apps.tracker.services.active_state import require_open_day

TZ = ZoneInfo("Europe/London")


def _get_active_goal():
    return Goal.objects.filter(is_active=True).order_by("-id").first()


def _safe_settings():
    s = TrackerSettings.objects.first()
    if s:
        return s

    class _S:
        enforce_active_day_bounds = True
        exceptional_min_minutes = 45
        exceptional_max_per_day = 2

    return _S()


def _active_day_end_utc(active_day: ActiveDay):
    """
    End of that ActiveDay's calendar day in London (midnight).
    """
    if not active_day or not getattr(active_day, "wake_at", None):
        return None
    wake_local = timezone.localtime(active_day.wake_at, TZ)
    day_start_local = wake_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)
    return day_end_local.astimezone(UTC)


@require_login
def session_new(request):
    goal = _get_active_goal()
    if not goal:
        return render(request, "tracker/session_new.html", {"error": "No active goal set."})

    now = timezone.now()
    now_local = timezone.localtime(now, TZ)

    settings = _safe_settings()
    enforce_bounds = bool(getattr(settings, "enforce_active_day_bounds", True))

    # Open day (robust: OneToOne OR ForeignKey)
    open_day = require_open_day(goal)
    day_is_open = bool(
        open_day
        and getattr(open_day, "is_open", False)
        and getattr(open_day, "sleep_at", None) is None
    )

    # Block Quick Add if open day belongs to a previous date
    if day_is_open and getattr(open_day, "wake_at", None):
        open_day_date = timezone.localtime(open_day.wake_at, TZ).date()
        if open_day_date != now_local.date():
            messages.error(request, "Your open day is from a previous date. End Day, then Start Day for today.")
            return redirect("tracker:today")

    # If strict bounds are ON, Quick Add requires an open day
    if enforce_bounds and not day_is_open:
        messages.error(request, "Start Day first to add sessions.")
        return redirect("tracker:today")

    # Defaults: last 60 minutes, clamped to wake_at and that day's midnight (UTC)
    default_end = now
    if day_is_open:
        day_end_utc = _active_day_end_utc(open_day)
        if day_end_utc:
            default_end = min(default_end, day_end_utc)

    default_start = default_end - timedelta(minutes=60)

    if day_is_open and getattr(open_day, "wake_at", None):
        default_start = max(open_day.wake_at, default_start)

    active_day_for_form = open_day if day_is_open else None

    if request.method == "POST":
        form = SessionQuickAddForm(
            request.POST,
            goal=goal,
            settings=settings,
            active_day=active_day_for_form,
        )

        if form.is_valid():
            s = form.save(commit=False)
            s.goal = goal
            try:
                s.full_clean()
                s.save()
            except ValidationError as e:
                msg = "; ".join(getattr(e, "messages", [str(e)]))
                form.add_error(None, msg)
            else:
                messages.success(request, "Session saved.")
                return redirect("tracker:today")

        # Helpful hint for cross-midnight mistakes
        end_errs = [str(e).lower() for e in form.errors.get("end_at", [])]
        if any(("midnight" in e) or ("cross" in e) for e in end_errs):
            messages.info(
                request,
                "Tip: If your work crossed midnight, split it into two sessions "
                "(e.g., 23:39→00:00 and 00:00→02:46). Sessions must not cross midnight."
            )

        # Single banner (avoid duplicates)
        messages.error(request, "Please fix the errors below.")

    else:
        form = SessionQuickAddForm(
            initial={
                "start_at": timezone.localtime(default_start, TZ).replace(second=0, microsecond=0),
                "end_at": timezone.localtime(default_end, TZ).replace(second=0, microsecond=0),
            },
            goal=goal,
            settings=settings,
            active_day=active_day_for_form,
        )

    return render(
        request,
        "tracker/session_new.html",
        {
            "goal": goal,
            "form": form,
            "now_local": now_local,
        },
    )
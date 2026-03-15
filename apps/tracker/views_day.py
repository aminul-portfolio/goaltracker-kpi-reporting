# apps/tracker/views_day.py
from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from apps.goals.models import Goal
from apps.goals.rbac import require_login
from apps.tracker.models import ActiveDay, ActiveTimer
from apps.tracker.services.active_state import require_open_day


def _get_active_goal():
    # Deterministic: avoids random “first()” differences when multiple active goals exist.
    return Goal.objects.filter(is_active=True).order_by("-id").first()


def _timer_state_ok_for_day_change(timer: ActiveTimer | None) -> tuple[bool, str | None]:
    """
    Day boundary is not allowed while the timer is:
    - running
    - paused with accumulated minutes
    - in an inconsistent state (current_start_at set)
    """
    if not timer:
        return True, None

    if getattr(timer, "is_running", False):
        return False, "Stop & Save (or Pause) the timer before changing the day."

    if int(getattr(timer, "accumulated_minutes", 0) or 0) > 0:
        return False, "You have a paused timer. Stop & Save it before changing the day."

    if getattr(timer, "current_start_at", None):
        return False, "Timer state is inconsistent. Stop & Save (or reset) before changing the day."

    return True, None


def _active_day_goal_unique() -> bool:
    """
    Detect whether ActiveDay.goal is unique (OneToOne-like) so we can safely update_or_create.
    If goal is not unique (FK), we create a new row for each day.
    """
    try:
        f = ActiveDay._meta.get_field("goal")
        return bool(getattr(f, "unique", False) or getattr(f, "one_to_one", False))
    except Exception:
        return False


@require_login
def day_start(request):
    if request.method != "POST":
        return redirect("tracker:today")

    goal = _get_active_goal()
    if not goal:
        messages.error(request, "No active goal set.")
        return redirect("tracker:today")

    now = timezone.now()

    with transaction.atomic():
        timer = ActiveTimer.objects.select_for_update().filter(goal=goal).first()
        ok, msg = _timer_state_ok_for_day_change(timer)
        if not ok:
            messages.error(request, msg)
            return redirect("tracker:today")

        # If any open day exists (service handles OneToOne or FK), no-op
        open_day = require_open_day(goal)
        if open_day:
            messages.info(request, "Day already started.")
            return redirect("tracker:today")

        if _active_day_goal_unique():
            # OneToOne-ish: keep a single row per goal
            ActiveDay.objects.update_or_create(
                goal=goal,
                defaults={"wake_at": now, "sleep_at": None, "is_open": True},
            )
        else:
            # FK: create a fresh row per day
            ActiveDay.objects.create(goal=goal, wake_at=now, sleep_at=None, is_open=True)

    messages.success(request, "Day started.")
    return redirect("tracker:today")


@require_login
def day_end(request):
    if request.method != "POST":
        return redirect("tracker:today")

    goal = _get_active_goal()
    if not goal:
        messages.error(request, "No active goal set.")
        return redirect("tracker:today")

    now = timezone.now()

    with transaction.atomic():
        # Lock timer first (prevents race between stop/pause and day end)
        timer = ActiveTimer.objects.select_for_update().filter(goal=goal).first()
        ok, msg = _timer_state_ok_for_day_change(timer)
        if not ok:
            messages.error(request, msg)
            return redirect("tracker:today")

        # Use service for "open day" (works for OneToOne or FK)
        active_day = require_open_day(goal)
        if not active_day:
            messages.info(request, "No open day to end.")
            return redirect("tracker:today")

        # Lock the day row we are about to close
        active_day = (
            ActiveDay.objects.select_for_update()
            .filter(pk=active_day.pk)
            .first()
        )
        if not active_day or not getattr(active_day, "is_open", False):
            messages.info(request, "No open day to end.")
            return redirect("tracker:today")

        active_day.sleep_at = now
        active_day.is_open = False
        active_day.full_clean()

        update_fields = ["sleep_at", "is_open"]
        # Only include updated_at if your model actually has it
        if any(f.name == "updated_at" for f in active_day._meta.fields):
            update_fields.append("updated_at")

        active_day.save(update_fields=update_fields)

    messages.success(request, "Day ended.")
    return redirect("tracker:today")
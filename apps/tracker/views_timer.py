# apps/tracker/views_timer.py
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo
from datetime import timezone as dt_timezone
from datetime import UTC

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from apps.goals.models import Category, Goal, TrackerSettings
from apps.goals.rbac import require_login
from apps.snapshots.services import build_day_snapshot
from apps.tracker.enums import QualityLevel
from apps.tracker.models import ActiveDay, ActiveTimer, Session
from apps.tracker.services.active_state import require_open_day

TZ = ZoneInfo("Europe/London")


def _get_active_goal():
    return Goal.objects.filter(is_active=True).order_by("-id").first()


def _safe_settings():
    s = TrackerSettings.objects.first()
    if s:
        return s

    class _S:
        daily_target_minutes = 660
        exceptional_min_minutes = 45
        exceptional_max_per_day = 2

    return _S()


def _has_field(model_or_instance, field_name: str) -> bool:
    try:
        m = model_or_instance if hasattr(model_or_instance, "_meta") else model_or_instance.__class__
        return any(f.name == field_name for f in m._meta.fields)
    except Exception:
        return False


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _timer_state_ok_for_day_change(timer: ActiveTimer | None) -> tuple[bool, str | None]:
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
    try:
        f = ActiveDay._meta.get_field("goal")
        return bool(getattr(f, "unique", False) or getattr(f, "one_to_one", False))
    except Exception:
        return False


def _require_open_day_locked(goal: Goal) -> ActiveDay | None:
    qs = ActiveDay.objects.select_for_update().filter(goal=goal, is_open=True)
    if _has_field(ActiveDay, "sleep_at"):
        qs = qs.filter(sleep_at__isnull=True)
    return qs.order_by("-wake_at", "-id").first()


def _open_day_is_today(active_day: ActiveDay, now_local) -> bool:
    if not active_day or not getattr(active_day, "wake_at", None):
        return True
    return timezone.localtime(active_day.wake_at, TZ).date() == now_local.date()


def _active_day_end_utc(active_day: ActiveDay):
    """
    End of that ActiveDay’s calendar day in London (midnight).
    """
    wake_local = timezone.localtime(active_day.wake_at, TZ)
    day_start_local = wake_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)
    return day_end_local.astimezone(UTC)


def _day_window_end(active_day: ActiveDay, now_utc):
    """
    End boundary for saving sessions:
    - If sleep_at exists, end <= sleep_at
    - If open day is from previous date, end <= that day's midnight (London)
    - Else end <= now
    """
    end = now_utc

    if getattr(active_day, "sleep_at", None):
        end = min(end, active_day.sleep_at)

    # Clamp to that day's midnight (prevents spill into next day)
    if getattr(active_day, "wake_at", None):
        end = min(end, _active_day_end_utc(active_day))

    return end


def _timer_total_minutes(timer: ActiveTimer, end_at) -> int:
    total = int(getattr(timer, "accumulated_minutes", 0) or 0)
    if getattr(timer, "is_running", False) and getattr(timer, "current_start_at", None):
        seg = int((end_at - timer.current_start_at).total_seconds() // 60)
        total += max(0, seg)
    return max(0, total)


def _reset_timer(timer: ActiveTimer):
    timer.is_running = False
    timer.current_start_at = None
    timer.accumulated_minutes = 0
    timer.deliverable = ""
    timer.category_id = None
    timer.quality_level = QualityLevel.STANDARD

    update_fields = [
        "is_running",
        "current_start_at",
        "accumulated_minutes",
        "deliverable",
        "category",
        "quality_level",
    ]
    if _has_field(timer, "updated_at"):
        update_fields.append("updated_at")

    timer.save(update_fields=update_fields)


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

        open_day = require_open_day(goal)
        if open_day:
            messages.info(request, "Day already started.")
            return redirect("tracker:today")

        if _active_day_goal_unique():
            ActiveDay.objects.update_or_create(
                goal=goal,
                defaults={"wake_at": now, "sleep_at": None, "is_open": True},
            )
        else:
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
    reflection = (request.POST.get("reflection") or "").strip()
    settings = _safe_settings()

    with transaction.atomic():
        timer = ActiveTimer.objects.select_for_update().filter(goal=goal).first()
        ok, msg = _timer_state_ok_for_day_change(timer)
        if not ok:
            messages.error(request, msg)
            return redirect("tracker:today")

        active_day = require_open_day(goal)
        if not active_day:
            messages.info(request, "No open day to end.")
            return redirect("tracker:today")

        active_day = ActiveDay.objects.select_for_update().filter(pk=active_day.pk).first()
        if not active_day or not getattr(active_day, "is_open", False):
            messages.info(request, "No open day to end.")
            return redirect("tracker:today")

        if _has_field(active_day, "sleep_at"):
            active_day.sleep_at = now
        active_day.is_open = False
        active_day.full_clean()

        update_fields = ["is_open"]
        if _has_field(active_day, "sleep_at"):
            update_fields.append("sleep_at")
        if _has_field(active_day, "updated_at"):
            update_fields.append("updated_at")
        active_day.save(update_fields=update_fields)

    snap = build_day_snapshot(
        goal=goal,
        wake_at=active_day.wake_at,
        sleep_at=now,
        close_day=True,
        reflection=reflection,
        settings=settings,
    )
    messages.success(request, f"Day closed. Rating: {getattr(snap, 'rating', '—')}.")
    return redirect("snapshots:day_detail", day_key=snap.day_key.isoformat())


@require_login
def timer_start(request):
    if request.method != "POST":
        return redirect("tracker:today")

    goal = _get_active_goal()
    if not goal:
        messages.error(request, "No active goal set.")
        return redirect("tracker:today")

    now = timezone.now()
    now_local = timezone.localtime(now, TZ)

    category_raw = (request.POST.get("category") or "").strip()
    category_id = _safe_int(category_raw, None)
    if not category_id or not Category.objects.filter(pk=category_id).exists():
        messages.error(request, "Please select a valid category to start the timer.")
        return redirect("tracker:today")

    quality_level = (request.POST.get("quality_level") or QualityLevel.STANDARD).strip()
    if quality_level not in QualityLevel.values:
        quality_level = QualityLevel.STANDARD

    deliverable = (request.POST.get("deliverable") or "").strip()
    if quality_level == QualityLevel.EXCEPTIONAL and not deliverable:
        messages.error(request, "Deliverable is required for Exceptional sessions.")
        return redirect("tracker:today")

    with transaction.atomic():
        active_day = _require_open_day_locked(goal)
        if not active_day:
            messages.error(request, "Start Day first.")
            return redirect("tracker:today")

        if not _open_day_is_today(active_day, now_local):
            messages.error(request, "Open day is from a previous date. End Day, then Start Day for today.")
            return redirect("tracker:today")

        timer = ActiveTimer.objects.select_for_update().filter(goal=goal).first()
        if not timer:
            timer = ActiveTimer.objects.create(goal=goal)
            timer = ActiveTimer.objects.select_for_update().get(pk=timer.pk)

        if getattr(timer, "is_running", False):
            messages.info(request, "Timer already running.")
            return redirect("tracker:today")

        if int(getattr(timer, "accumulated_minutes", 0) or 0) > 0:
            messages.warning(request, "You have a paused timer. Please Resume or Stop & Save it first.")
            return redirect("tracker:today")

        if getattr(timer, "current_start_at", None):
            messages.warning(request, "Timer state looks inconsistent. Please Stop & Save (or reset) first.")
            return redirect("tracker:today")

        timer.category_id = category_id
        timer.quality_level = quality_level
        timer.deliverable = deliverable
        timer.is_running = True
        timer.current_start_at = now
        timer.accumulated_minutes = 0

        update_fields = [
            "category",
            "quality_level",
            "deliverable",
            "is_running",
            "current_start_at",
            "accumulated_minutes",
        ]
        if _has_field(timer, "updated_at"):
            update_fields.append("updated_at")

        timer.save(update_fields=update_fields)

    messages.success(request, f"Timer started at {now_local:%H:%M}.")
    return redirect("tracker:today")


@require_login
def timer_pause(request):
    if request.method != "POST":
        return redirect("tracker:today")

    goal = _get_active_goal()
    if not goal:
        messages.error(request, "No active goal set.")
        return redirect("tracker:today")

    now = timezone.now()
    now_local = timezone.localtime(now, TZ)

    with transaction.atomic():
        active_day = _require_open_day_locked(goal)
        if not active_day:
            messages.error(request, "Start Day first.")
            return redirect("tracker:today")

        if not _open_day_is_today(active_day, now_local):
            messages.error(request, "Open day is from a previous date. Use Stop + Save (clamps to midnight), then End Day.")
            return redirect("tracker:today")

        timer = ActiveTimer.objects.select_for_update().filter(goal=goal).first()
        if not timer or not timer.is_running or not timer.current_start_at:
            messages.info(request, "No running timer to pause.")
            return redirect("tracker:today")

        seg_end = min(now, _day_window_end(active_day, now))
        seg = int((seg_end - timer.current_start_at).total_seconds() // 60)

        timer.accumulated_minutes = int(getattr(timer, "accumulated_minutes", 0) or 0) + max(0, seg)
        timer.is_running = False
        timer.current_start_at = None

        update_fields = ["accumulated_minutes", "is_running", "current_start_at"]
        if _has_field(timer, "updated_at"):
            update_fields.append("updated_at")

        timer.save(update_fields=update_fields)
        elapsed = timer.accumulated_minutes

    messages.success(request, f"Timer paused. Elapsed: {elapsed} min.")
    return redirect("tracker:today")


@require_login
def timer_resume(request):
    if request.method != "POST":
        return redirect("tracker:today")

    goal = _get_active_goal()
    if not goal:
        messages.error(request, "No active goal set.")
        return redirect("tracker:today")

    now = timezone.now()
    now_local = timezone.localtime(now, TZ)

    with transaction.atomic():
        active_day = _require_open_day_locked(goal)
        if not active_day:
            messages.error(request, "Start Day first.")
            return redirect("tracker:today")

        if not _open_day_is_today(active_day, now_local):
            messages.error(request, "Open day is from a previous date. End Day, then Start Day for today.")
            return redirect("tracker:today")

        timer = ActiveTimer.objects.select_for_update().filter(goal=goal).first()
        if not timer:
            messages.error(request, "No timer exists. Start the timer first.")
            return redirect("tracker:today")

        if getattr(timer, "is_running", False):
            messages.info(request, "Timer already running.")
            return redirect("tracker:today")

        if int(getattr(timer, "accumulated_minutes", 0) or 0) <= 0:
            messages.info(request, "No paused timer to resume.")
            return redirect("tracker:today")

        timer.is_running = True
        timer.current_start_at = now

        update_fields = ["is_running", "current_start_at"]
        if _has_field(timer, "updated_at"):
            update_fields.append("updated_at")

        timer.save(update_fields=update_fields)

    messages.success(request, f"Timer resumed at {now_local:%H:%M}.")
    return redirect("tracker:today")


@require_login
def timer_stop_and_save(request):
    if request.method != "POST":
        return redirect("tracker:today")

    goal = _get_active_goal()
    if not goal:
        messages.error(request, "No active goal set.")
        return redirect("tracker:today")

    now = timezone.now()

    with transaction.atomic():
        active_day = _require_open_day_locked(goal)
        if not active_day:
            messages.error(request, "Start Day first.")
            return redirect("tracker:today")

        timer = (
            ActiveTimer.objects.select_for_update()
            .select_related("category")
            .filter(goal=goal)
            .first()
        )
        if not timer:
            messages.error(request, "No timer exists.")
            return redirect("tracker:today")

        # Apply POST overrides (typically only present when paused / fields enabled)
        update_fields = []

        if "category" in request.POST:
            posted_cat = (request.POST.get("category") or "").strip()
            new_cat_id = _safe_int(posted_cat, None)
            if new_cat_id and Category.objects.filter(pk=new_cat_id).exists():
                if new_cat_id != getattr(timer, "category_id", None):
                    timer.category_id = new_cat_id
                    update_fields.append("category")

        if "quality_level" in request.POST:
            posted_q = (request.POST.get("quality_level") or "").strip()
            if posted_q in QualityLevel.values and posted_q != getattr(timer, "quality_level", None):
                timer.quality_level = posted_q
                update_fields.append("quality_level")

        if "deliverable" in request.POST:
            posted_deliverable = (request.POST.get("deliverable") or "").strip()
            cur_deliverable = (getattr(timer, "deliverable", "") or "").strip()
            if posted_deliverable != cur_deliverable:
                timer.deliverable = posted_deliverable
                update_fields.append("deliverable")

        if update_fields:
            if _has_field(timer, "updated_at"):
                update_fields.append("updated_at")
            timer.save(update_fields=update_fields)

        if not getattr(timer, "category_id", None):
            messages.error(request, "Please select a category before saving the session.")
            return redirect("tracker:today")

        # ✅ Clamp end_at to the active-day window (prevents crossing into next day)
        end_at = _day_window_end(active_day, now)

        total_min = _timer_total_minutes(timer, end_at)
        if total_min <= 0:
            messages.info(request, "Timer duration is 0 minutes; nothing saved.")
            _reset_timer(timer)
            return redirect("tracker:today")

        settings = _safe_settings()
        q = timer.quality_level

        start_at = end_at - timedelta(minutes=total_min)

        # Clamp start_at to wake_at (never before start day)
        if getattr(active_day, "wake_at", None) and start_at < active_day.wake_at:
            start_at = active_day.wake_at
            total_min = int((end_at - start_at).total_seconds() // 60)

        if total_min <= 0:
            messages.info(request, "Session falls outside the current day window; nothing saved.")
            _reset_timer(timer)
            return redirect("tracker:today")

        # Exceptional minimum minutes rule (demote if not enough)
        if q == QualityLevel.EXCEPTIONAL and total_min < settings.exceptional_min_minutes:
            q = QualityLevel.HIGH
            messages.warning(request, f"Exceptional requires ≥{settings.exceptional_min_minutes} min. Saved as High.")

        # Exceptional max-per-day rule (demote if exceeded)
        if q == QualityLevel.EXCEPTIONAL:
            exc_count = (
                Session.objects.filter(
                    goal=goal,
                    start_at__gte=active_day.wake_at,
                    end_at__lte=end_at,
                    quality_level=QualityLevel.EXCEPTIONAL,
                ).count()
            )
            if exc_count >= settings.exceptional_max_per_day:
                q = QualityLevel.HIGH
                messages.warning(request, "Exceptional limit reached (max/day). Saved as High.")

        deliverable = (getattr(timer, "deliverable", "") or "").strip()
        if q == QualityLevel.EXCEPTIONAL and not deliverable:
            messages.error(request, "Deliverable is required for Exceptional sessions.")
            return redirect("tracker:today")

        notes = "(Timer session)"
        if deliverable:
            notes += f": {deliverable}"

        s = Session(
            goal=goal,
            category_id=timer.category_id,
            start_at=start_at,
            end_at=end_at,
            quality_level=q,
            deliverable=deliverable,
            notes=notes,
        )
        s.full_clean()
        s.save()

        _reset_timer(timer)

    messages.success(request, f"Saved session: {total_min} min ({q}).")
    return redirect("tracker:today")
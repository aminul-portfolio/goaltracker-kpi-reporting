# apps/dashboard/views.py
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from apps.goals.models import Goal, TrackerSettings
from apps.goals.rbac import require_login
from apps.tracker.models import Session
from apps.tracker.services.active_state import active_day_for, active_timer_for

TZ = ZoneInfo("Europe/London")

DAILY_BREAKDOWN_PER_PAGE = 5  # <-- change this if you want 10/15/etc.


def _get_active_goal():
    # Deterministic: avoids random “first()” differences when multiple active goals exist.
    return Goal.objects.filter(is_active=True).order_by("-id").first()


def _safe_settings():
    s = TrackerSettings.objects.first()
    if s:
        return s

    class _S:
        daily_target_minutes = 660  # 11h
        exceptional_max_per_day = 2

    return _S()


def _sum_minutes(qs, field_name: str) -> int:
    val = qs.aggregate(total=Sum(field_name))["total"]
    return int(val or 0)


def _percent(done: int, target: int) -> float:
    if not target:
        return 0.0
    return round((done / target) * 100.0, 1)


def _fmt_hours(minutes: int) -> float:
    return round((minutes or 0) / 60.0, 2)


def _clamp(n, lo, hi):
    return max(lo, min(hi, n))


def _bar_pct(pct: float, cap: float = 100.0) -> float:
    try:
        return float(_clamp(pct, 0.0, cap))
    except Exception:
        return 0.0


def _window_bounds_local(goal: Goal):
    start_date = goal.start_date
    duration_days = int(getattr(goal, "duration_days", 30))
    start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=TZ)
    end_local = start_local + timedelta(days=duration_days)  # exclusive end
    return start_local, end_local, duration_days


@require_login
def dashboard_v1(request):
    goal = _get_active_goal()
    if not goal:
        return render(request, "dashboard/index.html", {"error": "No active goal set."})

    settings = _safe_settings()

    now = timezone.now()
    now_local = timezone.localtime(now, TZ)

    # ---- Day range (calendar day in London) ----
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(dt_timezone.utc)

    day_end = day_end_local.astimezone(dt_timezone.utc)

    # ---- Week range (Mon 00:00 -> next Mon 00:00 in London) ----
    weekday = day_start_local.weekday()  # Mon=0
    week_start_local = day_start_local - timedelta(days=weekday)
    week_end_local = week_start_local + timedelta(days=7)
    week_start = week_start_local.astimezone(dt_timezone.utc)
    week_end = week_end_local.astimezone(dt_timezone.utc)

    # ---- Month range (1st 00:00 -> next month 1st 00:00 in London) ----
    month_start_local = day_start_local.replace(day=1)
    if month_start_local.month == 12:
        month_end_local = month_start_local.replace(year=month_start_local.year + 1, month=1)
    else:
        month_end_local = month_start_local.replace(month=month_start_local.month + 1)
    month_start = month_start_local.astimezone(dt_timezone.utc)
    month_end = month_end_local.astimezone(dt_timezone.utc)

    # ---- Goal window (duration_days) ----
    window_start_local, window_end_local, duration_days = _window_bounds_local(goal)
    window_start = window_start_local.astimezone(dt_timezone.utc)
    window_end = window_end_local.astimezone(dt_timezone.utc)

    # ---- Query sets ----
    qs_day = Session.objects.filter(goal=goal, start_at__gte=day_start, start_at__lt=day_end)
    qs_week = Session.objects.filter(goal=goal, start_at__gte=week_start, start_at__lt=week_end)
    qs_month = Session.objects.filter(goal=goal, start_at__gte=month_start, start_at__lt=month_end)
    qs_30 = Session.objects.filter(goal=goal, start_at__gte=window_start, start_at__lt=window_end)

    day_raw = _sum_minutes(qs_day, "duration_minutes")
    day_eff = _sum_minutes(qs_day, "effective_minutes")

    week_raw = _sum_minutes(qs_week, "duration_minutes")
    week_eff = _sum_minutes(qs_week, "effective_minutes")

    month_raw = _sum_minutes(qs_month, "duration_minutes")
    month_eff = _sum_minutes(qs_month, "effective_minutes")

    win_raw = _sum_minutes(qs_30, "duration_minutes")
    win_eff = _sum_minutes(qs_30, "effective_minutes")

    # ---- Targets ----
    daily_target = int(getattr(settings, "daily_target_minutes", 660))
    weekly_target = daily_target * 7
    monthly_target = int(getattr(goal, "monthly_target_minutes", 19800))  # 330h
    win_target = monthly_target  # default

    # ---- Remaining today ----
    day_remaining_raw = max(0, daily_target - day_raw)

    # ---- Remaining + pace ----
    start_date = goal.start_date
    days_elapsed = (now_local.date() - start_date).days + 1
    days_elapsed = _clamp(days_elapsed, 1, duration_days)

    days_left_30 = duration_days - days_elapsed
    days_left_30 = _clamp(days_left_30, 1, duration_days)

    win_remaining_raw = max(0, win_target - win_raw)
    win_required_per_day = int(round(win_remaining_raw / days_left_30))

    days_left_week = (week_end_local.date() - now_local.date()).days
    days_left_week = _clamp(days_left_week, 1, 7)

    days_left_month = (month_end_local.date() - now_local.date()).days
    days_left_month = _clamp(days_left_month, 1, 31)

    week_remaining_raw = max(0, weekly_target - week_raw)
    month_remaining_raw = max(0, monthly_target - month_raw)

    week_required_per_day = int(round(week_remaining_raw / days_left_week))
    month_required_per_day = int(round(month_remaining_raw / days_left_month))

    # ---- Bars + gains ----
    win_raw_pct = _percent(win_raw, win_target)
    win_eff_pct = _percent(win_eff, win_target)
    win_raw_bar = _bar_pct(win_raw_pct)
    win_eff_bar = _bar_pct(win_eff_pct)
    win_gain_h = _fmt_hours(max(0, win_eff - win_raw))

    day_raw_pct = _percent(day_raw, daily_target)
    day_eff_pct = _percent(day_eff, daily_target)
    day_raw_bar = _bar_pct(day_raw_pct)
    day_eff_bar = _bar_pct(day_eff_pct)
    day_gain_h = _fmt_hours(max(0, day_eff - day_raw))

    week_raw_pct = _percent(week_raw, weekly_target)
    week_eff_pct = _percent(week_eff, weekly_target)
    week_raw_bar = _bar_pct(week_raw_pct)
    week_eff_bar = _bar_pct(week_eff_pct)
    week_gain_h = _fmt_hours(max(0, week_eff - week_raw))

    month_raw_pct = _percent(month_raw, monthly_target)
    month_eff_pct = _percent(month_eff, monthly_target)
    month_raw_bar = _bar_pct(month_raw_pct)
    month_eff_bar = _bar_pct(month_eff_pct)
    month_gain_h = _fmt_hours(max(0, month_eff - month_raw))

    # ---- On-track / pace delta ----
    pace_delta_30_h = round(_fmt_hours(win_required_per_day) - _fmt_hours(daily_target), 2)
    on_track_30 = win_required_per_day <= daily_target

    pace_delta_week_h = round(_fmt_hours(week_required_per_day) - _fmt_hours(daily_target), 2)
    on_track_week = week_required_per_day <= daily_target

    # ---- Category breakdown (window) ----
    cat_rows = (
        qs_30.values("category_id", "category__name")
        .annotate(raw_min=Sum("duration_minutes"), eff_min=Sum("effective_minutes"))
        .order_by("-eff_min")
    )
    total_eff_window = sum(int(r["eff_min"] or 0) for r in cat_rows) or 0

    top_cats_30 = []
    for r in cat_rows[:10]:
        eff_min = int(r["eff_min"] or 0)
        raw_min = int(r["raw_min"] or 0)
        share_pct = round((eff_min / total_eff_window) * 100.0, 1) if total_eff_window else 0.0
        top_cats_30.append(
            {
                "name": r["category__name"] or "Uncategorised",
                "eff_min": eff_min,
                "raw_min": raw_min,
                "eff_h": _fmt_hours(eff_min),
                "raw_h": _fmt_hours(raw_min),
                "share_pct": share_pct,
            }
        )

    # ---- Day open / timer status (robust: OneToOne OR ForeignKey) ----
    active_day = active_day_for(goal)
    day_is_open = bool(
        active_day and getattr(active_day, "is_open", False) and getattr(active_day, "sleep_at", None) is None
    )

    timer = active_timer_for(goal)
    timer_is_running = bool(timer and getattr(timer, "is_running", False))

    ctx = {
        "goal": goal,
        "settings": settings,
        "now_local": now_local,

        # Status strip
        "active_day": active_day if day_is_open else None,
        "day_is_open": day_is_open,
        "timer": timer,
        "timer_is_running": timer_is_running,
        "on_track_30": on_track_30,
        "on_track_week": on_track_week,
        "pace_delta_30_h": pace_delta_30_h,
        "pace_delta_week_h": pace_delta_week_h,

        # Goal window
        "window_start_local": window_start_local,
        "window_end_local": window_end_local,
        "days_elapsed": days_elapsed,
        "days_left_30": days_left_30,
        "win_raw": win_raw,
        "win_eff": win_eff,
        "win_raw_h": _fmt_hours(win_raw),
        "win_eff_h": _fmt_hours(win_eff),
        "win_target": win_target,
        "win_target_h": _fmt_hours(win_target),
        "win_raw_pct": win_raw_pct,
        "win_eff_pct": win_eff_pct,
        "win_raw_bar": win_raw_bar,
        "win_eff_bar": win_eff_bar,
        "win_remaining_raw_h": _fmt_hours(win_remaining_raw),
        "win_required_per_day_h": _fmt_hours(win_required_per_day),
        "win_gain_h": win_gain_h,

        # Today
        "daily_target": daily_target,
        "daily_target_h": _fmt_hours(daily_target),
        "day_raw": day_raw,
        "day_eff": day_eff,
        "day_raw_h": _fmt_hours(day_raw),
        "day_eff_h": _fmt_hours(day_eff),
        "day_raw_pct": day_raw_pct,
        "day_eff_pct": day_eff_pct,
        "day_raw_bar": day_raw_bar,
        "day_eff_bar": day_eff_bar,
        "day_remaining_raw_h": _fmt_hours(day_remaining_raw),
        "day_gain_h": day_gain_h,

        # Week
        "week_start_local": week_start_local,
        "week_end_local": week_end_local,
        "weekly_target_h": _fmt_hours(weekly_target),
        "week_raw_h": _fmt_hours(week_raw),
        "week_eff_h": _fmt_hours(week_eff),
        "week_raw_pct": week_raw_pct,
        "week_eff_pct": week_eff_pct,
        "week_raw_bar": week_raw_bar,
        "week_eff_bar": week_eff_bar,
        "week_remaining_raw_h": _fmt_hours(week_remaining_raw),
        "week_required_per_day_h": _fmt_hours(week_required_per_day),
        "week_gain_h": week_gain_h,

        # Month
        "month_start_local": month_start_local,
        "month_end_local": month_end_local,
        "monthly_target_h": _fmt_hours(monthly_target),
        "month_raw_h": _fmt_hours(month_raw),
        "month_eff_h": _fmt_hours(month_eff),
        "month_raw_pct": month_raw_pct,
        "month_eff_pct": month_eff_pct,
        "month_raw_bar": month_raw_bar,
        "month_eff_bar": month_eff_bar,
        "month_remaining_raw_h": _fmt_hours(month_remaining_raw),
        "month_required_per_day_h": _fmt_hours(month_required_per_day),
        "month_gain_h": month_gain_h,

        # Category breakdown
        "top_cats_30": top_cats_30,
    }

    return render(request, "dashboard/index.html", ctx)


@require_login
def history_view(request):
    goal = _get_active_goal()
    if not goal:
        return render(request, "dashboard/history.html", {"error": "No active goal set."})

    settings = _safe_settings()
    now = timezone.now()
    now_local = timezone.localtime(now, TZ)
    today_local_date = now_local.date()

    window_start_local, window_end_local, duration_days = _window_bounds_local(goal)
    window_start_utc = window_start_local.astimezone(dt_timezone.utc)
    window_end_utc = window_end_local.astimezone(dt_timezone.utc)

    sessions = list(
        Session.objects.select_related("category")
        .filter(goal=goal, start_at__gte=window_start_utc, start_at__lt=window_end_utc)
        .order_by("start_at")
    )

    day_totals = defaultdict(lambda: {"raw": 0, "eff": 0})
    week_totals = defaultdict(lambda: {"raw": 0, "eff": 0, "week_start": None})
    cat_totals = defaultdict(lambda: {"name": "", "raw": 0, "eff": 0})
    cat_week = defaultdict(lambda: {"raw": 0, "eff": 0})

    for s in sessions:
        start_local = timezone.localtime(s.start_at, TZ)
        d = start_local.date()

        raw = int(getattr(s, "duration_minutes", 0) or 0)
        eff = int(getattr(s, "effective_minutes", 0) or 0)

        day_totals[d]["raw"] += raw
        day_totals[d]["eff"] += eff

        iso = d.isocalendar()
        week_key = (iso.year, iso.week)
        monday = d - timedelta(days=d.weekday())
        if week_totals[week_key]["week_start"] is None:
            week_totals[week_key]["week_start"] = monday

        week_totals[week_key]["raw"] += raw
        week_totals[week_key]["eff"] += eff

        cat_id = getattr(s, "category_id", None)
        cat_name = s.category.name if getattr(s, "category_id", None) else "Uncategorised"
        cat_totals[cat_id]["name"] = cat_name
        cat_totals[cat_id]["raw"] += raw
        cat_totals[cat_id]["eff"] += eff

        cat_week[(cat_id, week_key)]["raw"] += raw
        cat_week[(cat_id, week_key)]["eff"] += eff

    daily_target = int(getattr(settings, "daily_target_minutes", 660))
    weekly_target = daily_target * 7

    start_date = goal.start_date
    date_rows = []
    labels = []
    raw_series_h = []
    eff_series_h = []

    total_raw = 0
    total_eff = 0
    days_with_work = 0
    best_eff = -1
    best_day = None

    for i in range(duration_days):
        d = start_date + timedelta(days=i)
        is_future = d > today_local_date

        raw = day_totals[d]["raw"] if not is_future else 0
        eff = day_totals[d]["eff"] if not is_future else 0

        total_raw += raw
        total_eff += eff

        if (raw > 0 or eff > 0) and not is_future:
            days_with_work += 1
        if eff > best_eff and not is_future:
            best_eff = eff
            best_day = d

        raw_h = _fmt_hours(raw)
        eff_h = _fmt_hours(eff)

        raw_pct = _percent(raw, daily_target) if not is_future else 0.0
        eff_pct = _percent(eff, daily_target) if not is_future else 0.0

        date_rows.append(
            {
                "date": d,
                "dow": d.strftime("%a"),
                "is_future": is_future,
                "raw_h": raw_h,
                "eff_h": eff_h,
                "gain_h": _fmt_hours(max(0, eff - raw)),
                "raw_pct": raw_pct,
                "eff_pct": eff_pct,
                "raw_bar": _bar_pct(raw_pct),
                "eff_bar": _bar_pct(eff_pct),
            }
        )

        labels.append(d.strftime("%d %b"))
        raw_series_h.append(raw_h)
        eff_series_h.append(eff_h)

    # -----------------------------
    # Daily breakdown pagination
    # -----------------------------
    page_num = request.GET.get("p") or "1"
    paginator = Paginator(date_rows, DAILY_BREAKDOWN_PER_PAGE)
    daily_page_obj = paginator.get_page(page_num)

    # -----------------------------
    # Weekly totals
    # -----------------------------
    week_rows = []
    week_keys_sorted = sorted(
        week_totals.keys(),
        key=lambda wk: week_totals[wk]["week_start"] or datetime.min.date(),
    )

    for wk in week_keys_sorted:
        wk_start = week_totals[wk]["week_start"]
        if not wk_start:
            continue

        wk_end_exclusive = wk_start + timedelta(days=7)
        wk_end_inclusive = wk_end_exclusive - timedelta(days=1)

        raw = week_totals[wk]["raw"]
        eff = week_totals[wk]["eff"]

        raw_pct = _percent(raw, weekly_target)
        eff_pct = _percent(eff, weekly_target)

        week_rows.append(
            {
                "week_key": f"{wk[0]}-W{wk[1]:02d}",
                "week_start": wk_start,
                "week_end": wk_end_exclusive,               # stored as exclusive-style boundary
                "week_end_inclusive": wk_end_inclusive,     # for display (Mon → Sun)
                "raw_h": _fmt_hours(raw),
                "eff_h": _fmt_hours(eff),
                "gain_h": _fmt_hours(max(0, eff - raw)),
                "raw_pct": raw_pct,
                "eff_pct": eff_pct,
                "raw_bar": _bar_pct(raw_pct),
                "eff_bar": _bar_pct(eff_pct),
            }
        )

    total_eff_window = sum(v["eff"] for v in cat_totals.values()) or 0
    top_cats = sorted(cat_totals.items(), key=lambda kv: kv[1]["eff"], reverse=True)[:5]

    week_cols = [
        {
            "key": wr["week_key"],
            "start": wr["week_start"],
            "end": wr["week_end"],
            "end_inclusive": wr["week_end_inclusive"],
        }
        for wr in week_rows
    ]

    cat_trend_rows = []
    for cat_id, info in top_cats:
        row_weeks = []
        for wr in week_rows:
            year = int(wr["week_key"].split("-W")[0])
            weekn = int(wr["week_key"].split("-W")[1])
            wk_key_tuple = (year, weekn)
            eff_min = cat_week[(cat_id, wk_key_tuple)]["eff"]
            row_weeks.append({"eff_h": _fmt_hours(eff_min)})

        share = round((info["eff"] / total_eff_window) * 100.0, 1) if total_eff_window else 0.0

        cat_trend_rows.append(
            {
                "name": info["name"] or "Uncategorised",
                "total_eff_h": _fmt_hours(info["eff"]),
                "share_pct": share,
                "weeks": row_weeks,
            }
        )

    days_elapsed = (today_local_date - start_date).days + 1
    days_elapsed = _clamp(days_elapsed, 1, duration_days)
    avg_eff_h = round((_fmt_hours(total_eff) / days_elapsed), 2) if days_elapsed else 0.0
    best_day_label = best_day.strftime("%d %b %Y") if best_day else "—"
    best_day_eff_h = _fmt_hours(best_eff) if best_eff >= 0 else 0.0

    ctx = {
        "goal": goal,
        "settings": settings,
        "now_local": now_local,

        "window_start_local": window_start_local,
        "window_end_local": window_end_local,
        "duration_days": duration_days,

        "total_raw_h": _fmt_hours(total_raw),
        "total_eff_h": _fmt_hours(total_eff),
        "total_gain_h": _fmt_hours(max(0, total_eff - total_raw)),

        "days_elapsed": days_elapsed,
        "days_with_work": days_with_work,
        "avg_eff_h": avg_eff_h,
        "best_day_label": best_day_label,
        "best_day_eff_h": best_day_eff_h,

        # Paginated daily rows
        "date_rows": daily_page_obj.object_list,
        "daily_page_obj": daily_page_obj,
        "daily_page_size": DAILY_BREAKDOWN_PER_PAGE,

        # Weekly + categories
        "week_rows": week_rows,
        "week_cols": week_cols,
        "cat_trend_rows": cat_trend_rows,

        # Chart series (full window)
        "chart_labels": labels,
        "chart_raw_h": raw_series_h,
        "chart_eff_h": eff_series_h,
    }

    return render(request, "dashboard/history.html", ctx)
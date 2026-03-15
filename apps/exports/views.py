# apps/exports/views.py
from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.goals.models import Category, Goal
from apps.goals.rbac import require_staff
from apps.snapshots.models import DaySnapshot
from apps.tracker.models import Session

from .contracts import (
    # contracts
    EXPORT_CONTRACT_V1,
    EXPORT_CONTRACT_V2,
    EXPORT_CONTRACT_VERSION,  # backwards compat, ok to keep
    # v1 headers
    SESSIONS_V1_HEADERS,
    DAY_SNAPSHOTS_V1_HEADERS,
    # v2 headers
    FACT_SESSIONS_V2_HEADERS,
    DIM_GOAL_V2_HEADERS,
    DIM_CATEGORY_V2_HEADERS,
    DIM_WORK_ITEM_V2_HEADERS,
    DIM_DATE_V2_HEADERS,
    SPRINT_SETTINGS_V2_HEADERS,
    DIM_TAG_GROUP_V2_HEADERS,
    DIM_TAG_V2_HEADERS,
    BRIDGE_SESSION_TAG_V2_HEADERS,
)

TZ = ZoneInfo("Europe/London")


# -----------------------------
# Small utilities
# -----------------------------
def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _iso_local_dt(dt: datetime | None):
    if not dt:
        return ""
    return timezone.localtime(dt, TZ).isoformat(timespec="minutes")


def _iso_utc_dt(dt: datetime | None):
    if not dt:
        return ""
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def _row_from_headers(headers: list[str], values_by_name: dict[str, object]):
    """
    Write rows strictly in contract order.
    Missing keys become "" (safe if headers change).
    """
    row = []
    for h in headers:
        v = values_by_name.get(h, "")
        row.append("" if v is None else v)
    return row


def _csv_response(filename: str, contract: str):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["X-Export-Contract"] = contract
    return resp


# -----------------------------
# Goal + date range helpers
# -----------------------------
def _get_active_goal() -> Goal | None:
    return Goal.objects.filter(is_active=True).first()


def _get_goal_from_request(request) -> Goal | None:
    """
    Allows: ?goal=<id>
    Defaults: active goal.
    """
    goal_id = request.GET.get("goal")
    if goal_id:
        try:
            return Goal.objects.filter(id=int(goal_id)).first()
        except Exception:
            return _get_active_goal()
    return _get_active_goal()


def _local_day_bounds(d: date):
    """London calendar bounds: [00:00, next day 00:00)."""
    start_local = datetime.combine(d, datetime.min.time(), tzinfo=TZ)
    end_local = start_local + timedelta(days=1)
    return start_local, end_local


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _window_bounds(goal: Goal):
    start_date = getattr(goal, "start_date", None)
    if not start_date:
        start_date = timezone.localtime(timezone.now(), TZ).date()
    duration_days = _safe_int(getattr(goal, "duration_days", 30) or 30, 30)

    start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=TZ)
    end_local = start_local + timedelta(days=duration_days)
    return start_local, end_local


def _scope_bounds(goal: Goal, scope: str | None, now_local: datetime):
    scope = (scope or "window").strip().lower()
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if scope == "day":
        return day_start_local, day_start_local + timedelta(days=1)

    if scope == "week":
        weekday = day_start_local.weekday()  # Mon=0
        start_local = day_start_local - timedelta(days=weekday)
        return start_local, start_local + timedelta(days=7)

    if scope == "month":
        start_local = day_start_local.replace(day=1)
        if start_local.month == 12:
            end_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            end_local = start_local.replace(month=start_local.month + 1)
        return start_local, end_local

    return _window_bounds(goal)


def _apply_range_filters(goal: Goal, request, base_start_local: datetime, base_end_local: datetime):
    """
    Query overrides:
      - start=YYYY-MM-DD
      - end=YYYY-MM-DD (inclusive day, converted to end-exclusive)
      - scope=day|week|month|window
    start/end override scope.
    """
    now_local = timezone.localtime(timezone.now(), TZ)
    scope = request.GET.get("scope")
    start_q = request.GET.get("start")
    end_q = request.GET.get("end")

    if start_q or end_q:
        sd = _parse_date(start_q) if start_q else None
        ed = _parse_date(end_q) if end_q else None

        if sd and ed and ed < sd:
            return base_start_local, base_end_local

        if sd:
            start_local, _ = _local_day_bounds(sd)
        else:
            start_local = base_start_local

        if ed:
            _, end_local = _local_day_bounds(ed)
        else:
            end_local = base_end_local

        return start_local, end_local

    return _scope_bounds(goal, scope, now_local)


# -----------------------------
# Exports hub page
# -----------------------------
@require_staff
def exports_index(request):
    goal = _get_goal_from_request(request)
    now_local = timezone.localtime(timezone.now(), TZ)
    return render(
        request,
        "exports/hub.html",
        {
            "goal": goal,
            "now_local": now_local,
            "export_contract": EXPORT_CONTRACT_V2,  # show BI contract on hub
        },
    )


# ==========================================================
# V1 exports (legacy)
# ==========================================================
@require_staff
def export_sessions_csv(request):
    """
    GET /exports/sessions.csv
    Params:
      - goal=<goal_id>
      - scope=day|week|month|window
      - start=YYYY-MM-DD
      - end=YYYY-MM-DD
      - category=<category_id>
    """
    goal = _get_goal_from_request(request)
    resp = _csv_response("sessions.csv", EXPORT_CONTRACT_V1)
    w = csv.writer(resp)
    w.writerow(SESSIONS_V1_HEADERS)

    if not goal:
        return resp

    base_start_local, base_end_local = _window_bounds(goal)
    start_local, end_local = _apply_range_filters(goal, request, base_start_local, base_end_local)

    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    qs = (
        Session.objects.select_related("category", "goal")
        .filter(goal=goal, start_at__gte=start_utc, start_at__lt=end_utc)
        .order_by("start_at")
    )

    cat_id = request.GET.get("category")
    if cat_id:
        try:
            qs = qs.filter(category_id=int(cat_id))
        except Exception:
            pass

    for s in qs:
        mult = getattr(s, "multiplier", None)
        mult_val = f"{mult}" if mult is not None else ""

        values = {
            "session_id": s.id,
            "goal": s.goal.name if s.goal_id else "",
            "category": s.category.name if getattr(s, "category_id", None) else "",
            "start_at_local": _iso_local_dt(getattr(s, "start_at", None)),
            "end_at_local": _iso_local_dt(getattr(s, "end_at", None)),
            "duration_minutes": _safe_int(getattr(s, "duration_minutes", 0)),
            "effective_minutes": _safe_int(getattr(s, "effective_minutes", 0)),
            "quality_level": getattr(s, "quality_level", "") or "",
            "multiplier": mult_val,
            "mae_block": getattr(s, "mae_block", "") or "",
            "deliverable": getattr(s, "deliverable", "") or "",
            "notes": getattr(s, "notes", "") or "",
        }
        w.writerow(_row_from_headers(SESSIONS_V1_HEADERS, values))

    return resp


@require_staff
def export_day_snapshots_csv(request):
    """
    GET /exports/day_snapshots.csv
    Params:
      - goal=<goal_id>
      - scope=day|week|month|window
      - start=YYYY-MM-DD
      - end=YYYY-MM-DD
    """
    goal = _get_goal_from_request(request)
    resp = _csv_response("day_snapshots.csv", EXPORT_CONTRACT_V1)
    w = csv.writer(resp)
    w.writerow(DAY_SNAPSHOTS_V1_HEADERS)

    if not goal:
        return resp

    base_start_local, base_end_local = _window_bounds(goal)
    start_local, end_local = _apply_range_filters(goal, request, base_start_local, base_end_local)

    start_date = start_local.date()
    end_date_exclusive = end_local.date()

    qs = (
        DaySnapshot.objects.select_related("goal")
        .filter(goal=goal, day_key__gte=start_date, day_key__lt=end_date_exclusive)
        .order_by("day_key")
    )

    for d in qs:
        values = {
            "day_key": d.day_key.isoformat(),
            "goal": d.goal.name if d.goal_id else "",
            "wake_at_local": _iso_local_dt(getattr(d, "wake_at", None)),
            "sleep_at_local": _iso_local_dt(getattr(d, "sleep_at", None)),
            "target_minutes": _safe_int(getattr(d, "target_minutes", 0)),
            "raw_minutes": _safe_int(getattr(d, "raw_minutes", 0)),
            "effective_minutes": _safe_int(getattr(d, "effective_minutes", 0)),
            "effective_pct": _safe_float(getattr(d, "effective_pct", 0.0)),
            "rating": getattr(d, "rating", "") or "",
            "reflection": getattr(d, "reflection", "") or "",
        }
        w.writerow(_row_from_headers(DAY_SNAPSHOTS_V1_HEADERS, values))

    return resp


# ==========================================
# V2 exports (BI-grade / Power BI)
# ==========================================
@require_staff
def export_fact_sessions_v2_csv(request):
    """
    GET /exports/v2/fact_sessions.csv
    Params:
      - goal=<goal_id>
      - scope=day|week|month|window
      - start=YYYY-MM-DD
      - end=YYYY-MM-DD
      - category=<category_id>
    """
    goal = _get_goal_from_request(request)
    resp = _csv_response("fact_sessions.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(FACT_SESSIONS_V2_HEADERS)

    if not goal:
        return resp

    base_start_local, base_end_local = _window_bounds(goal)
    start_local, end_local = _apply_range_filters(goal, request, base_start_local, base_end_local)

    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    qs = (
        Session.objects.select_related("category", "goal")
        .filter(goal=goal, start_at__gte=start_utc, start_at__lt=end_utc)
        .order_by("start_at")
    )

    cat_id = request.GET.get("category")
    if cat_id:
        try:
            qs = qs.filter(category_id=int(cat_id))
        except Exception:
            pass

    for s in qs:
        start_at = getattr(s, "start_at", None)
        start_local_s = timezone.localtime(start_at, TZ) if start_at else None
        session_date = start_local_s.date().isoformat() if start_local_s else ""

        mult = getattr(s, "multiplier", None)
        mult_val = f"{mult}" if mult is not None else ""

        # ✅ populate created_at_utc (your missing column)
        created_at = getattr(s, "created_at", None)
        created_utc = _iso_utc_dt(created_at)

        values = {
            "session_id": s.id,
            "goal_id": getattr(s, "goal_id", "") or "",
            "category_id": getattr(s, "category_id", "") or "",
            "work_item_id": getattr(s, "work_item_id", "") or "",
            "date": session_date,
            "start_at_local": _iso_local_dt(getattr(s, "start_at", None)),
            "end_at_local": _iso_local_dt(getattr(s, "end_at", None)),
            "duration_minutes": _safe_int(getattr(s, "duration_minutes", 0)),
            "effective_minutes": _safe_int(getattr(s, "effective_minutes", 0)),
            "quality_level": getattr(s, "quality_level", "") or "",
            "multiplier": mult_val,
            "mae_block": getattr(s, "mae_block", "") or "",
            "deliverable": getattr(s, "deliverable", "") or "",
            "notes": getattr(s, "notes", "") or "",
            "created_at_utc": created_utc,
        }
        w.writerow(_row_from_headers(FACT_SESSIONS_V2_HEADERS, values))

    return resp


@require_staff
def export_dim_goal_v2_csv(request):
    resp = _csv_response("dim_goal.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(DIM_GOAL_V2_HEADERS)

    qs = Goal.objects.all().order_by("-is_active", "id")
    for g in qs:
        values = {
            "goal_id": g.id,
            "goal_name": getattr(g, "name", "") or "",
            "start_date": getattr(g, "start_date", "") or "",
            "duration_days": _safe_int(getattr(g, "duration_days", 0)),
            "is_active": "1" if getattr(g, "is_active", False) else "0",
        }
        w.writerow(_row_from_headers(DIM_GOAL_V2_HEADERS, values))

    return resp


@require_staff
def export_dim_category_v2_csv(request):
    resp = _csv_response("dim_category.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(DIM_CATEGORY_V2_HEADERS)

    qs = Category.objects.all().order_by("id")
    for c in qs:
        values = {
            "category_id": c.id,
            "category_name": getattr(c, "name", "") or "",
            "goal_id": getattr(c, "goal_id", "") or "",
            "sort_order": _safe_int(getattr(c, "sort_order", 0)),
            "archived": "1" if getattr(c, "archived", False) else "0",
        }
        w.writerow(_row_from_headers(DIM_CATEGORY_V2_HEADERS, values))

    return resp


@require_staff
def export_dim_work_item_v2_csv(request):
    resp = _csv_response("dim_work_item.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(DIM_WORK_ITEM_V2_HEADERS)

    try:
        from apps.goals.models import WorkItem
    except Exception:
        return resp

    qs = WorkItem.objects.all().order_by("goal_id", "archived", "id")

    for wi in qs:
        title = getattr(wi, "title", None) or getattr(wi, "name", "") or ""
        values = {
            "work_item_id": wi.id,
            "goal_id": getattr(wi, "goal_id", "") or "",
            "title": title,
            "status": getattr(wi, "status", "") or "",
            "planned_minutes": _safe_int(getattr(wi, "planned_minutes", 0)),
            "due_date": getattr(wi, "due_date", "") or "",
            "archived": "1" if getattr(wi, "archived", False) else "0",
        }
        w.writerow(_row_from_headers(DIM_WORK_ITEM_V2_HEADERS, values))

    return resp


@require_staff
def export_sprint_settings_v2_csv(request):
    """
    Must include at least:
      - sprint_start_date
      - sprint_days
    (Power Query uses those two)
    """
    goal = _get_goal_from_request(request)
    resp = _csv_response("sprint_settings.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(SPRINT_SETTINGS_V2_HEADERS)

    if not goal:
        return resp

    sprint_start = getattr(goal, "sprint_start_date", None) or getattr(goal, "start_date", None)
    sprint_days = _safe_int(getattr(goal, "sprint_days", None) or getattr(goal, "duration_days", 30) or 30, 30)
    if not sprint_start:
        sprint_start = timezone.localtime(timezone.now(), TZ).date()

    sprint_end = sprint_start + timedelta(days=sprint_days - 1)
    baseline_end = sprint_start + timedelta(days=6)

    # best effort daily target
    daily_target = 0
    try:
        from apps.goals.models import TrackerSettings
        ts = TrackerSettings.objects.first()
        daily_target = _safe_int(getattr(ts, "daily_target_minutes", 0))
    except Exception:
        daily_target = 0

    sprint_target = daily_target * sprint_days if daily_target else 0

    values = {
        "sprint_start_date": sprint_start.isoformat(),
        "sprint_days": sprint_days,
        "sprint_end_date": sprint_end.isoformat(),
        "baseline_end_date_day7": baseline_end.isoformat(),
        "daily_target_minutes": daily_target,
        "sprint_target_minutes": sprint_target,
    }
    w.writerow(_row_from_headers(SPRINT_SETTINGS_V2_HEADERS, values))
    return resp


@require_staff
def export_dim_date_v2_csv(request):
    goal = _get_goal_from_request(request)
    resp = _csv_response("dim_date.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(DIM_DATE_V2_HEADERS)

    if not goal:
        return resp

    base_start_local, base_end_local = _window_bounds(goal)
    start_local, end_local = _apply_range_filters(goal, request, base_start_local, base_end_local)

    d = start_local.date()
    end_excl = end_local.date()

    while d < end_excl:
        iso_week = d.isocalendar().week
        week_start = d - timedelta(days=d.weekday())  # Monday
        values = {
            "date": d.isoformat(),
            "year": d.year,
            "month": d.month,
            "month_name": d.strftime("%B"),
            "day": d.day,
            "day_name": d.strftime("%A"),
            "iso_week": iso_week,
            "week_start_date": week_start.isoformat(),
            "is_weekend": "1" if d.isoweekday() in (6, 7) else "0",
            # optional alternate names if your contract uses them
            "isoweekday": d.isoweekday(),
        }
        w.writerow(_row_from_headers(DIM_DATE_V2_HEADERS, values))
        d += timedelta(days=1)

    return resp


# -----------------------
# Optional tags (safe if models exist)
# -----------------------
@require_staff
def export_dim_tag_group_v2_csv(request):
    resp = _csv_response("dim_tag_group.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(DIM_TAG_GROUP_V2_HEADERS)

    try:
        from apps.tracker.models import TagGroup
    except Exception:
        return resp

    for tg in TagGroup.objects.all().order_by("archived", "sort_order", "id"):
        values = {
            "tag_group_id": tg.id,
            "name": getattr(tg, "name", "") or "",
            "sort_order": _safe_int(getattr(tg, "sort_order", 0)),
            "archived": "1" if getattr(tg, "archived", False) else "0",
        }
        w.writerow(_row_from_headers(DIM_TAG_GROUP_V2_HEADERS, values))

    return resp


@require_staff
def export_dim_tag_v2_csv(request):
    resp = _csv_response("dim_tag.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(DIM_TAG_V2_HEADERS)

    try:
        from apps.tracker.models import Tag
    except Exception:
        return resp

    for t in Tag.objects.all().order_by("group_id", "archived", "sort_order", "id"):
        values = {
            "tag_id": t.id,
            "tag_group_id": getattr(t, "group_id", "") or "",
            "name": getattr(t, "name", "") or "",
            "sort_order": _safe_int(getattr(t, "sort_order", 0)),
            "archived": "1" if getattr(t, "archived", False) else "0",
        }
        w.writerow(_row_from_headers(DIM_TAG_V2_HEADERS, values))

    return resp


@require_staff
def export_bridge_session_tag_v2_csv(request):
    resp = _csv_response("bridge_session_tag.csv", EXPORT_CONTRACT_V2)
    w = csv.writer(resp)
    w.writerow(BRIDGE_SESSION_TAG_V2_HEADERS)

    try:
        from apps.tracker.models import SessionTag
    except Exception:
        return resp

    for st in SessionTag.objects.all().order_by("session_id", "tag_id"):
        created_utc = _iso_utc_dt(getattr(st, "created_at", None))
        values = {
            "session_id": getattr(st, "session_id", "") or "",
            "tag_id": getattr(st, "tag_id", "") or "",
            "created_at_utc": created_utc,
        }
        w.writerow(_row_from_headers(BRIDGE_SESSION_TAG_V2_HEADERS, values))

    return resp

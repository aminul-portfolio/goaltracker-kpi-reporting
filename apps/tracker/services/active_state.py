# apps/tracker/services/active_state.py
from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

from apps.tracker.models import ActiveDay, ActiveTimer


def _has_field(model, field_name: str) -> bool:
    try:
        return any(f.name == field_name for f in model._meta.fields)
    except Exception:
        return False


def _get_goal_rel(goal, attr: str):
    try:
        return getattr(goal, attr)
    except ObjectDoesNotExist:
        return None
    except Exception:
        return None


def active_day_for(goal):
    rel = _get_goal_rel(goal, "active_day")

    ordering = []
    if _has_field(ActiveDay, "wake_at"):
        ordering.append("-wake_at")
    ordering.append("-id")

    if rel is None:
        return ActiveDay.objects.filter(goal=goal).order_by(*ordering).first()

    if hasattr(rel, "all"):
        return rel.order_by(*ordering).first()

    return rel


def active_timer_for(goal):
    rel = _get_goal_rel(goal, "active_timer")

    if rel is None:
        return ActiveTimer.objects.filter(goal=goal).order_by("-id").first()

    if hasattr(rel, "all"):
        return rel.order_by("-id").first()

    return rel


def require_open_day(goal) -> ActiveDay | None:
    qs = ActiveDay.objects.filter(goal=goal, is_open=True)

    if _has_field(ActiveDay, "sleep_at"):
        qs = qs.filter(sleep_at__isnull=True)

    ordering = []
    if _has_field(ActiveDay, "wake_at"):
        ordering.append("-wake_at")
    ordering.append("-id")

    return qs.order_by(*ordering).first()
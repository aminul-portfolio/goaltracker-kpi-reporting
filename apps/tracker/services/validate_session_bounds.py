# apps/tracker/services/validate_session_bounds.py
from __future__ import annotations

from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

TZ = ZoneInfo("Europe/London")


def validate_session_bounds(
    start_at,
    end_at,
    *,
    active_day=None,
    settings=None,
    now=None,
):
    """
    Validates that a session lies inside the current active-day window (if enforced).

    Rules:
    - Always: end_at must be after start_at
    - If enforce_active_day_bounds is True:
        - active_day must exist and be open
        - start_at >= active_day.wake_at
        - end_at <= active_day.sleep_at (if closed) else <= now
    """
    if start_at is None or end_at is None:
        return start_at, end_at

    if end_at <= start_at:
        raise ValidationError("End time must be after start time.")

    enforce = True
    if settings is not None:
        enforce = bool(getattr(settings, "enforce_active_day_bounds", True))

    if not enforce:
        return start_at, end_at

    if not active_day:
        raise ValidationError("Start Day first to add sessions.")

    if not getattr(active_day, "is_open", False):
        raise ValidationError("No open day. Click Start Day first.")

    wake_at = getattr(active_day, "wake_at", None)
    if wake_at and start_at < wake_at:
        wake_local = timezone.localtime(wake_at, TZ).strftime("%d/%m/%Y %H:%M")
        raise ValidationError(f"Session start cannot be before the day start (wake time: {wake_local}).")

    now = now or timezone.now()
    sleep_at = getattr(active_day, "sleep_at", None)
    window_end = sleep_at or now

    if end_at > window_end:
        if sleep_at:
            end_local = timezone.localtime(sleep_at, TZ).strftime("%d/%m/%Y %H:%M")
            raise ValidationError(f"Session end cannot be after day end ({end_local}).")
        raise ValidationError(
            "End time cannot be in the future. Set End ≤ current time, or use Timer for an ongoing session."
        )

    return start_at, end_at
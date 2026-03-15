# apps/tracker/forms.py
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.goals.models import Category
from apps.tracker.enums import QualityLevel
from apps.tracker.models import Session
from apps.tracker.services.validate_session_bounds import validate_session_bounds

TZ = ZoneInfo("Europe/London")


class SessionQuickAddForm(forms.ModelForm):
    """
    Quick Add form with:
      - active-day bounds (Wake -> now) when enabled
      - strict no cross-midnight (while day is open)
      - exceptional rules (deliverable + min minutes + max/day)
      - no overlapping sessions

    NOTE:
      We enforce "no future end time" on the server (clean()).
      Avoid HTML5 max=... on datetime-local because some pickers/browsers can submit
      invalid values as blank, producing confusing "required" + "future" errors together.
    """

    def __init__(self, *args, goal=None, settings=None, active_day=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal = goal
        self.settings = settings
        self.active_day = active_day

        # Robust Category queryset (supports optional: goal, archived, sort_order)
        qs = Category.objects.all()

        try:
            Category._meta.get_field("goal")
            if self.goal:
                qs = qs.filter(goal=self.goal)
        except Exception:
            pass

        try:
            Category._meta.get_field("archived")
            qs = qs.filter(archived=False)
        except Exception:
            pass

        order_fields = []
        try:
            Category._meta.get_field("sort_order")
            order_fields.append("sort_order")
        except Exception:
            pass
        order_fields.append("name")

        self.fields["category"].queryset = qs.order_by(*order_fields)

        # Accept both HTML datetime-local and common UK formats (+ optional seconds)
        dt_local = "%Y-%m-%dT%H:%M"
        dt_local_sec = "%Y-%m-%dT%H:%M:%S"
        dt_uk = "%d/%m/%Y %H:%M"
        dt_uk_sec = "%d/%m/%Y %H:%M:%S"
        dt_uk_comma = "%d/%m/%Y, %H:%M"
        dt_uk_comma_sec = "%d/%m/%Y, %H:%M:%S"

        self.fields["start_at"].input_formats = [dt_local, dt_local_sec, dt_uk, dt_uk_sec, dt_uk_comma, dt_uk_comma_sec]
        self.fields["end_at"].input_formats = [dt_local, dt_local_sec, dt_uk, dt_uk_sec, dt_uk_comma, dt_uk_comma_sec]

        # Make required errors explicit + consistent
        self.fields["start_at"].error_messages.setdefault("required", "Start time is required.")
        self.fields["end_at"].error_messages.setdefault("required", "End time is required.")
        self.fields["start_at"].error_messages.setdefault("invalid", "Enter a valid start date/time.")
        self.fields["end_at"].error_messages.setdefault("invalid", "Enter a valid end date/time.")

        # Optional min boundary (wake_at) to reduce obvious mistakes
        min_local_str = None
        if self.active_day and getattr(self.active_day, "wake_at", None):
            min_local = timezone.localtime(self.active_day.wake_at, TZ).replace(second=0, microsecond=0)
            min_local_str = min_local.strftime(dt_local)

        start_attrs = {"type": "datetime-local", "class": "form-control", "step": "60"}
        end_attrs = {"type": "datetime-local", "class": "form-control", "step": "60"}
        if min_local_str:
            start_attrs["min"] = min_local_str
            end_attrs["min"] = min_local_str

        self.fields["start_at"].widget = forms.DateTimeInput(format=dt_local, attrs=start_attrs)
        self.fields["end_at"].widget = forms.DateTimeInput(format=dt_local, attrs=end_attrs)

    class Meta:
        model = Session
        fields = ["category", "start_at", "end_at", "quality_level", "deliverable", "notes"]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "quality_level": forms.Select(attrs={"class": "form-select"}),
            "deliverable": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Required for Exceptional"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def _ensure_aware_london(self, dt):
        if not dt:
            return dt
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, TZ)
        return dt

    def clean(self):
        cleaned = super().clean()

        q = cleaned.get("quality_level")
        deliverable = (cleaned.get("deliverable") or "").strip()

        start_at = self._ensure_aware_london(cleaned.get("start_at"))
        end_at = self._ensure_aware_london(cleaned.get("end_at"))
        cleaned["start_at"] = start_at
        cleaned["end_at"] = end_at

        # If either field failed parsing / missing, let field-level errors stand
        if not start_at or not end_at:
            return cleaned

        # Most common mistake
        if end_at <= start_at:
            self.add_error(
                "end_at",
                "End time must be after start time. If your work crossed midnight, select the next day for End "
                "(or End Day + Start Day and log sessions per day).",
            )
            return cleaned

        # Second most common mistake (your screenshot case)
        now = timezone.now()
        if end_at > now:
            self.add_error(
                "end_at",
                "End time cannot be in the future. Set End ≤ current time, or use Timer for an ongoing session.",
            )
            return cleaned

        enforce_bounds = bool(getattr(self.settings, "enforce_active_day_bounds", True))
        strict_midnight = True

        # 1) Active-day bounds
        try:
            validate_session_bounds(
                start_at,
                end_at,
                active_day=self.active_day,
                settings=self.settings,
                now=now,
            )
        except ValidationError as e:
            msg = "; ".join(getattr(e, "messages", [str(e)]))
            self.add_error("end_at", msg)

        # 2) Strict no-cross-midnight (only while day is open)
        if (
            strict_midnight
            and enforce_bounds
            and self.active_day
            and getattr(self.active_day, "is_open", False)
            and getattr(self.active_day, "sleep_at", None) is None
        ):
            s_date = timezone.localtime(start_at, TZ).date()
            e_date = timezone.localtime(end_at, TZ).date()
            if s_date != e_date:
                self.add_error(
                    "end_at",
                    "Sessions cannot cross midnight. End the day and start a new day instead.",
                )

        # 3) Exceptional rules
        if q == QualityLevel.EXCEPTIONAL:
            if not deliverable:
                self.add_error("deliverable", "Deliverable is required for Exceptional sessions.")

            min_minutes = int(getattr(self.settings, "exceptional_min_minutes", 45) or 45)
            dur_min = int((end_at - start_at).total_seconds() // 60)
            if dur_min < min_minutes:
                self.add_error(
                    "quality_level",
                    f"Exceptional requires at least {min_minutes} minutes (this session is {dur_min} minutes).",
                )

            max_per_day = int(getattr(self.settings, "exceptional_max_per_day", 2) or 2)
            if self.goal and self.active_day and getattr(self.active_day, "wake_at", None):
                day_key = timezone.localtime(self.active_day.wake_at, TZ).date()
                day_start_local = timezone.make_aware(datetime.combine(day_key, time.min), TZ)
                day_end_local = day_start_local + timedelta(days=1)

                exc_qs = Session.objects.filter(
                    goal=self.goal,
                    start_at__gte=day_start_local.astimezone(timezone.utc),
                    start_at__lt=day_end_local.astimezone(timezone.utc),
                    quality_level=QualityLevel.EXCEPTIONAL,
                )
                if self.instance and self.instance.pk:
                    exc_qs = exc_qs.exclude(pk=self.instance.pk)

                if exc_qs.count() >= max_per_day:
                    self.add_error(
                        "quality_level",
                        f"Exceptional limit reached ({max_per_day}/day). Use High or end the day first.",
                    )

        # 4) Overlap prevention
        overlaps = Session.objects.filter(
            goal=self.goal,
            start_at__lt=end_at,
            end_at__gt=start_at,
        )
        if self.instance and self.instance.pk:
            overlaps = overlaps.exclude(pk=self.instance.pk)

        if enforce_bounds and self.active_day and getattr(self.active_day, "wake_at", None):
            overlaps = overlaps.filter(start_at__gte=self.active_day.wake_at)

        if overlaps.exists():
            self.add_error("end_at", "This session overlaps an existing session. Adjust start/end to avoid overlap.")

        return cleaned
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.goals.models import Goal, Category
from .enums import QualityLevel, MaeBlock, QUALITY_MULTIPLIERS


class ActiveDay(models.Model):
    """
    Current day window for a Goal.

    Option B:
      - Start Day: wake_at = now, is_open = True,  sleep_at = None
      - End Day:   sleep_at = now, is_open = False
    """
    goal = models.OneToOneField(Goal, on_delete=models.CASCADE, related_name="active_day")

    wake_at = models.DateTimeField()
    sleep_at = models.DateTimeField(null=True, blank=True)

    is_open = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_closed(self) -> bool:
        return (not self.is_open) or (self.sleep_at is not None)

    def __str__(self) -> str:
        return (
            f"ActiveDay(goal={self.goal_id}, wake_at={self.wake_at}, "
            f"sleep_at={self.sleep_at}, open={self.is_open})"
        )


class ActiveTimer(models.Model):
    """One timer per active goal. Stop & Save creates a Session."""
    goal = models.OneToOneField(Goal, on_delete=models.CASCADE, related_name="active_timer")

    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True)
    quality_level = models.CharField(
        max_length=20,
        choices=QualityLevel.choices,
        default=QualityLevel.STANDARD,
    )
    deliverable = models.CharField(max_length=200, blank=True, default="")

    is_running = models.BooleanField(default=False)
    current_start_at = models.DateTimeField(null=True, blank=True)
    accumulated_minutes = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def elapsed_minutes(self, now=None) -> int:
        now = now or timezone.now()
        total = int(self.accumulated_minutes)
        if self.is_running and self.current_start_at:
            seg = int((now - self.current_start_at).total_seconds() // 60)
            total += max(0, seg)
        return total

    def __str__(self) -> str:
        return f"ActiveTimer(goal={self.goal_id}, running={self.is_running})"


class Session(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.PROTECT, related_name="sessions")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="sessions")

    # Keep as string to avoid import cycles
    work_item = models.ForeignKey(
        "goals.WorkItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sessions",
    )

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    duration_minutes = models.PositiveIntegerField(default=0)
    quality_level = models.CharField(
        max_length=20,
        choices=QualityLevel.choices,
        default=QualityLevel.STANDARD,
    )

    multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    effective_minutes = models.PositiveIntegerField(default=0)

    mae_block = models.CharField(
        max_length=20,
        choices=MaeBlock.choices,
        default=MaeBlock.MORNING,
    )

    deliverable = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["start_at"]),
            models.Index(fields=["end_at"]),
            models.Index(fields=["category", "start_at"]),
            models.Index(fields=["goal", "start_at"]),
            models.Index(fields=["quality_level"]),
            models.Index(fields=["work_item", "start_at"]),
        ]

    def clean(self):
        errors = {}

        if not self.start_at:
            errors["start_at"] = "Start time is required."
        if not self.end_at:
            errors["end_at"] = "End time is required."
        if errors:
            raise ValidationError(errors)

        if self.end_at <= self.start_at:
            raise ValidationError({"end_at": "End time must be after start time."})

        if self.quality_level == QualityLevel.EXCEPTIONAL and not (self.deliverable or "").strip():
            raise ValidationError({"deliverable": "Deliverable is required for Exceptional sessions."})

    def save(self, *args, **kwargs):
        self.full_clean()

        delta = self.end_at - self.start_at
        minutes = int(delta.total_seconds() // 60)
        self.duration_minutes = max(0, minutes)

        mult = QUALITY_MULTIPLIERS.get(self.quality_level, 1.0)
        self.multiplier = Decimal(str(mult)).quantize(Decimal("0.01"))
        self.effective_minutes = int(round(self.duration_minutes * float(mult)))

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.category} {self.start_at:%Y-%m-%d %H:%M} ({self.duration_minutes}m)"


class TagGroup(models.Model):
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["archived", "sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    group = models.ForeignKey(TagGroup, on_delete=models.PROTECT, related_name="tags")
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("group", "name"),)
        indexes = [
            models.Index(fields=["group", "archived", "sort_order", "name"]),
        ]
        ordering = ["group_id", "archived", "sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class SessionTag(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="session_tags")
    tag = models.ForeignKey(Tag, on_delete=models.PROTECT, related_name="session_tags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("session", "tag"),)
        indexes = [
            models.Index(fields=["session"]),
            models.Index(fields=["tag"]),
        ]

    def __str__(self) -> str:
        return f"{self.session_id}:{self.tag_id}"

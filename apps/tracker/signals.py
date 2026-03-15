from __future__ import annotations

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from apps.tracker.models import Session
from apps.snapshots.services import TZ, upsert_day_snapshot_from_sessions


@receiver(pre_save, sender=Session)
def _session_capture_old(sender, instance: Session, **kwargs):
    if not instance.pk:
        instance._old_goal_id = None
        instance._old_day_key = None
        return

    old = Session.objects.filter(pk=instance.pk).only("goal_id", "start_at").first()
    if not old or not old.start_at:
        instance._old_goal_id = None
        instance._old_day_key = None
        return

    instance._old_goal_id = old.goal_id
    instance._old_day_key = timezone.localtime(old.start_at, TZ).date()


@receiver(post_save, sender=Session)
def _session_sync_snapshot_on_save(sender, instance: Session, **kwargs):
    if instance.start_at:
        day_key = timezone.localtime(instance.start_at, TZ).date()
        upsert_day_snapshot_from_sessions(goal=instance.goal, day_key=day_key)

    old_goal_id = getattr(instance, "_old_goal_id", None)
    old_day_key = getattr(instance, "_old_day_key", None)

    # If a session moved goal/day, reconcile the old snapshot too
    if old_goal_id and old_day_key:
        if old_goal_id != instance.goal_id or (
            instance.start_at and old_day_key != timezone.localtime(instance.start_at, TZ).date()
        ):
            from apps.goals.models import Goal
            old_goal = Goal.objects.filter(id=old_goal_id).first()
            if old_goal:
                upsert_day_snapshot_from_sessions(goal=old_goal, day_key=old_day_key)


@receiver(post_delete, sender=Session)
def _session_sync_snapshot_on_delete(sender, instance: Session, **kwargs):
    if instance.start_at:
        day_key = timezone.localtime(instance.start_at, TZ).date()
        upsert_day_snapshot_from_sessions(goal=instance.goal, day_key=day_key)
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.goals.models import Goal, Category
from apps.tracker.models import Session
from apps.snapshots.models import DaySnapshot

from .contracts import (
    EXPORT_CONTRACT_V1,
    SESSIONS_V1_HEADERS,
    DAY_SNAPSHOTS_V1_HEADERS,
)


class ExportContractsTests(TestCase):
    def setUp(self):
        self.goal = Goal.objects.create(name="Test Goal", is_active=True)
        self.cat = Category.objects.create(name="Deep Work")

        now = timezone.now()

        Session.objects.create(
            goal=self.goal,
            category=self.cat,
            start_at=now - timezone.timedelta(minutes=60),
            end_at=now,
            quality_level="standard",
            deliverable="",
            notes="",
        )

        wake = now - timezone.timedelta(hours=8)
        sleep = now - timezone.timedelta(hours=1)

        DaySnapshot.objects.update_or_create(
            goal=self.goal,
            day_key=timezone.localdate(),
            defaults={
                "wake_at": wake,
                "sleep_at": sleep,
                "raw_minutes": 60,
                "effective_minutes": 60,
                "target_minutes": 660,
                "effective_pct": 9.1,
                "rating": "OK",
                "reflection": "",
            },
        )

    def test_sessions_export_headers_contract(self):
        url = reverse("exports:sessions_csv")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Export-Contract"], EXPORT_CONTRACT_V1)

        first_line = resp.content.decode("utf-8").splitlines()[0]
        self.assertEqual(first_line, ",".join(SESSIONS_V1_HEADERS))

    def test_day_snapshots_export_headers_contract(self):
        url = reverse("exports:day_snapshots_csv")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Export-Contract"], EXPORT_CONTRACT_V1)

        first_line = resp.content.decode("utf-8").splitlines()[0]
        self.assertEqual(first_line, ",".join(DAY_SNAPSHOTS_V1_HEADERS))
# config/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("tracker/", include("apps.tracker.urls")),
    path("snapshots/", include("apps.snapshots.urls")),
    path("exports/", include(("apps.exports.urls", "exports"), namespace="exports")),  # ✅ namespaced
]

# apps/snapshots/urls.py
from django.urls import path
from . import views

app_name = "snapshots"

urlpatterns = [
    path("history/", views.history, name="history"),
    path("day/<str:day_key>/", views.day_detail, name="day_detail"),
    path("week/<str:week_start>/", views.week_detail, name="week_detail"),
]
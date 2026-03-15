from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_v1, name="home"),
    path("history/", views.history_view, name="history"),
]

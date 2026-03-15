# apps/tracker/urls.py
from django.urls import path

from . import views
from . import views_sessions, views_timer

app_name = "tracker"

urlpatterns = [
    # Today page
    path("today/", views.today_view, name="today"),

    # Day window
    path("today/start/", views_timer.day_start, name="start_day"),
    path("today/end/", views_timer.day_end, name="end_day"),

    # Timer
    path("today/timer/start/", views_timer.timer_start, name="timer_start"),
    path("today/timer/pause/", views_timer.timer_pause, name="timer_pause"),
    path("today/timer/resume/", views_timer.timer_resume, name="timer_resume"),
    path("today/timer/stop/", views_timer.timer_stop_and_save, name="timer_stop"),

    # Sessions
    path("sessions/new/", views_sessions.session_new, name="session_new"),
]
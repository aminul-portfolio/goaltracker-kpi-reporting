from django.apps import AppConfig

class TrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tracker"

    def ready(self):
        import apps.tracker.signals  # noqa
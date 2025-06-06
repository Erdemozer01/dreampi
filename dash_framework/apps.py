from django.apps import AppConfig


class DashFrameworkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dash_framework'

    def ready(self):
        try:
            import dash_framework.dash_apps  # Dash uygulamalarını yükle
        except ImportError:
            print("dash_framework.dash_apps yüklenirken bir sorun oluştu (belki ilk migrate sırasında).")
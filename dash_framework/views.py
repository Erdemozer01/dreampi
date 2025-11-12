from django.shortcuts import render
from .camera_apps import app as camera_app
from .dash_apps import app as dashboard_app


def dashboard_display_view(request):
    # Dash uygulamasının adı dash_apps.py'de tanımladığımız isim olacak
    # Örnek: app = DjangoDash('RealtimeSensorDashboard', ...)
    context = {'dash_app_name': "RealtimeSensorDashboard"}
    return render(request, 'dashboard_app/dashboard_display.html', context)


def camera_display_view(request):
    return render(request, "dashboard_app/camera.html")
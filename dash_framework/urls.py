from django.urls import path
from . import views

app_name = 'dash_framework'

urlpatterns = [
    path('', views.dashboard_display_view, name='realtime_dashboard'),
    path('camera/', views.camera_display_view, name='camera_display'),

]
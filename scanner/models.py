# scanner/models.py

from django.db import models
from django.utils import timezone


class Scan(models.Model): # <-- THIS CLASS MUST EXIST!
    # Your fields for the Scan model
    start_angle_setting = models.FloatField(default=0.0)
    end_angle_setting = models.FloatField(default=0.0)
    step_angle_setting = models.FloatField(default=10.0)
    buzzer_distance_setting = models.IntegerField(default=10)
    invert_motor_direction_setting = models.BooleanField(default=False)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    calculated_area_cm2 = models.FloatField(null=True, blank=True)
    perimeter_cm = models.FloatField(null=True, blank=True)
    max_width_cm = models.FloatField(null=True, blank=True)
    max_depth_cm = models.FloatField(null=True, blank=True)
    ai_commentary = models.TextField(blank=True, null=True)

    class Status(models.TextChoices):
        RUNNING = 'RUN', 'Running'
        COMPLETED = 'CMP', 'Completed'
        INTERRUPTED = 'INT', 'Interrupted'
        ERROR = 'ERR', 'Error'
        INSUFFICIENT_POINTS = 'ISP', 'Insufficient Points'

    status = models.CharField(max_length=3, choices=Status.choices, default=Status.RUNNING)


    def __str__(self):
        return f"Scan {self.id} ({self.status}) - {self.start_time.strftime('%Y-%m-%d %H:%M')}"


# dreampi/scanner/models.py dosyasında

class ScanPoint(models.Model):
    scan = models.ForeignKey(Scan, related_name='points', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    derece = models.FloatField(verbose_name="Derece")
    mesafe_cm = models.FloatField(verbose_name="Mesafe (cm)")
    hiz_cm_s = models.FloatField(null=True, blank=True, verbose_name="Hız (cm/s)")
    x_cm = models.FloatField(null=True, blank=True)
    y_cm = models.FloatField(null=True, blank=True)
    z_cm = models.FloatField(null=True, blank=True)
    mesafe_cm_2 = models.FloatField(null=True, blank=True, verbose_name="2. Sensör Mesafe (cm)")

    # YENİ SATIRI BURAYA EKLEYİN
    dikey_aci = models.FloatField(null=True, blank=True, verbose_name="Dikey Açı (°)")

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Point at {self.derece}° - {self.mesafe_cm:.2f} cm"
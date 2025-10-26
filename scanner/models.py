# scanner/models.py

import logging
from scipy.spatial import QhullError
import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull
from django.db import models
from django.utils import timezone

# --- Logger Tanımlaması ---
logger = logging.getLogger(__name__)


# --- Django Modelleri ---

class Scan(models.Model):
    """
    Tek bir tarama işlemini ve onunla ilgili ayarları, durumu ve
    analiz sonuçlarını saklar.
    """

    class Status(models.TextChoices):
        RUNNING = 'RUN', 'Çalışıyor'
        COMPLETED = 'CMP', 'Tamamlandı'
        INTERRUPTED = 'INT', 'Kesildi'
        ERROR = 'ERR', 'Hata'
        INSUFFICIENT_POINTS = 'ISP', 'Yetersiz Nokta'

    # --- YENİ EKLENEN ALAN ---
    class ScanType(models.TextChoices):
        MANUAL = 'MAN', 'Manuel Haritalama'
        AUTONOMOUS = 'AUT', 'Otonom Sürüş'

    scan_type = models.CharField(
        max_length=3,
        choices=ScanType.choices,
        default=ScanType.MANUAL,
        verbose_name="Tarama Tipi"
    )
    # --- YENİ EKLENEN ALAN SONU ---

    # Ayarlar
    h_scan_angle_setting = models.FloatField(default=360.0, verbose_name="Yatay Tarama Açısı")
    h_step_angle_setting = models.FloatField(default=10.0, verbose_name="Yatay Adım Açısı")
    v_scan_angle_setting = models.FloatField(default=180.0, verbose_name="Dikey Tarama Açısı")
    v_step_angle_setting = models.FloatField(default=10.0, verbose_name="Dikey Adım Açısı")
    steps_per_revolution_setting = models.IntegerField(default=4096, verbose_name="Motor Adım/Tur")

    # Zaman ve Durum
    start_time = models.DateTimeField(auto_now_add=True, verbose_name="Başlangıç Zamanı")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="Bitiş Zamanı")
    status = models.CharField(max_length=3, choices=Status.choices, default=Status.RUNNING, verbose_name="Durum")

    # Analiz Sonuçları
    point_count = models.IntegerField(default=0, verbose_name="Geçerli Nokta Sayısı")
    calculated_area_cm2 = models.FloatField(null=True, blank=True, verbose_name="2D Alan (cm²)")
    perimeter_cm = models.FloatField(null=True, blank=True, verbose_name="2D Çevre (cm)")
    max_width_cm = models.FloatField(null=True, blank=True, verbose_name="Maks. Genişlik (cm)")
    max_depth_cm = models.FloatField(null=True, blank=True, verbose_name="Maks. Derinlik (cm)")
    max_height_cm = models.FloatField(null=True, blank=True, verbose_name="Maks. Yükseklik (cm)")
    calculated_volume_cm3 = models.FloatField(null=True, blank=True, verbose_name="3D Hacim (cm³)")
    ai_commentary = models.TextField(blank=True, null=True, verbose_name="AI Yorumu")


    class Meta:
        verbose_name = "Tarama Kaydı"
        verbose_name_plural = "Tarama Kayıtları"
        ordering = ['-start_time']

    def __str__(self):
        return f"Tarama #{self.id} ({self.get_status_display()}) - {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    def run_analysis_and_update(self):
        """
        Bu taramaya ait noktaları analiz eder ve sonuçları veritabanına kaydeder.
        Bu fonksiyon, tarama tamamlandığında harici bir script tarafından çağrılmalıdır.
        """
        logger.info(f"Scan ID {self.id} için analiz başlatılıyor...")
        points_qs = self.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0).values('x_cm', 'y_cm', 'z_cm')
        point_count = points_qs.count()
        self.point_count = point_count

        if point_count < 15:
            logger.warning(f"Analiz için yetersiz nokta sayısı: {point_count}")
            self.status = self.Status.INSUFFICIENT_POINTS
            self.save(update_fields=['status', 'point_count'])
            return

        df = pd.DataFrame(list(points_qs))
        df.dropna(inplace=True)

        try:
            # 2D Analiz (Üstten Görünüm x-y düzleminde)
            points_2d = df[['y_cm', 'x_cm']].to_numpy()
            hull_2d = ConvexHull(points_2d)
            self.calculated_area_cm2 = hull_2d.volume  # 2D'de volume alanı verir
            self.perimeter_cm = hull_2d.area  # 2D'de area çevreyi verir
            self.max_width_cm = df['y_cm'].max() - df['y_cm'].min()
            self.max_depth_cm = df['x_cm'].max() - df['x_cm'].min()

            # 3D Analiz (Hacim ve Yükseklik)
            points_3d = df[['x_cm', 'y_cm', 'z_cm']].to_numpy()
            hull_3d = ConvexHull(points_3d)
            self.calculated_volume_cm3 = hull_3d.volume
            self.max_height_cm = df['z_cm'].max() - df['z_cm'].min()

            logger.info(
                f"Analiz tamamlandı. 2D Alan: {self.calculated_area_cm2:.2f}, 3D Hacim: {self.calculated_volume_cm3:.2f}")

        except (QhullError, ValueError) as e:
            logger.error(f"Analiz sırasında Convex Hull hatası (muhtemelen noktalar tek bir düzlemde): {e}")
            self.status = self.Status.ERROR
        except Exception as e:
            logger.error(f"Analiz sırasında genel hata: {e}", exc_info=True)
            self.status = self.Status.ERROR

        # Analizden sonra tüm hesaplanmış alanları tek seferde kaydet
        self.save()

class ScanPoint(models.Model):
    """
    Bir tarama sırasında toplanan her bir ölçüm noktasını temsil eder.
    """
    scan = models.ForeignKey(Scan, related_name='points', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    derece = models.FloatField(verbose_name="Yatay Açı (°)")
    dikey_aci = models.FloatField(null=True, blank=True, verbose_name="Dikey Açı (°)")
    mesafe_cm = models.FloatField(verbose_name="Mesafe (cm)")
    hiz_cm_s = models.FloatField(null=True, blank=True, verbose_name="Hız (cm/s)")
    x_cm = models.FloatField(null=True, blank=True)
    y_cm = models.FloatField(null=True, blank=True)
    z_cm = models.FloatField(null=True, blank=True)


    class Meta:
        ordering = ['timestamp']
        verbose_name = "Tarama Noktası"
        verbose_name_plural = "Tarama Noktaları"

    def __str__(self):
        return f"Point at {self.derece}° - {self.mesafe_cm:.2f} cm"


class AIModelConfiguration(models.Model):

    PROVIDER_CHOICES = [
        ('Google', 'Google'),
        ('OpenAI', 'OpenAI'),
        ('Other', 'Diğer'),
    ]
    model_provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default='Google', verbose_name="Sağlayıcı")


    name = models.CharField(max_length=100, unique=True, verbose_name="Yapılandırma Adı")
    model_name = models.CharField(max_length=100, verbose_name="Model Adı (örn: gemini-1.5-flash-latest)")
    api_key = models.CharField(max_length=255, help_text="Bu modele ait API anahtarı.")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "AI Model Yapılandırması"
        verbose_name_plural = "AI Model Yapılandırmaları"
        ordering = ['-is_active', 'name']
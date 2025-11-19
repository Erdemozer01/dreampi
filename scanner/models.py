import logging
import numpy as np
import pandas as pd
from django.db import models
from django.utils import timezone
from django.utils.html import format_html

# 3D Analiz için Scipy kontrolü
try:
    from scipy.spatial import ConvexHull, QhullError

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logging.warning("scipy kütüphanesi bulunamadı. 3D analiz devre dışı.")

logger = logging.getLogger(__name__)


# ============================================================================
# KAMERA MODELLERI (Gelişmiş Kontroller + Temel Özellikler)
# ============================================================================

class CameraCapture(models.Model):
    """
    Kameradan çekilen fotoğrafları ve o anki donanım/yazılım ayarlarını saklar.
    Base64 formatında görüntü ve metadata içerir.
    """
    # Temel Bilgiler
    timestamp = models.DateTimeField(default=timezone.now, verbose_name="Çekim Zamanı", db_index=True)
    base64_image = models.TextField(verbose_name="Görüntü Verisi (Base64)", help_text="Base64 encoded JPEG/PNG görüntü")

    # Donanım Durumu
    pan_angle = models.FloatField(default=0.0, verbose_name="Pan Açısı (Yatay)")
    distance_info = models.CharField(max_length=100, default="N/A", verbose_name="Mesafe Bilgisi")

    # Kamera Ayarları (v3.20+ ile uyumlu - Admin Paneli için Gerekli)
    resolution = models.CharField(max_length=20, default="1280x720", verbose_name="Çözünürlük")
    framerate = models.FloatField(null=True, blank=True, verbose_name="FPS")

    # Otomatik Kontrol Durumları
    ae_enable = models.BooleanField(default=True, verbose_name="Oto Pozlama (AE)")
    awb_enable = models.BooleanField(default=True, verbose_name="Oto Beyaz Dengesi (AWB)")
    lens_correction = models.BooleanField(default=False, verbose_name="Lens Düzeltme")

    # Manuel Ayar Değerleri
    exposure_time = models.IntegerField(null=True, blank=True, verbose_name="Pozlama Süresi (µs)")
    analogue_gain = models.FloatField(null=True, blank=True, verbose_name="ISO (Gain)")

    # Modlar ve Efektler
    awb_mode = models.CharField(max_length=50, default="Auto", verbose_name="AWB Modu")
    colour_effect = models.CharField(max_length=50, blank=True, null=True, verbose_name="Renk Efekti")
    flicker_mode = models.CharField(max_length=50, blank=True, null=True, verbose_name="Titreme Modu")
    exposure_mode = models.CharField(max_length=50, blank=True, null=True, verbose_name="Pozlama Modu")
    metering_mode = models.CharField(max_length=50, blank=True, null=True, verbose_name="Ölçüm Modu")

    # Görüntü İyileştirme
    brightness = models.FloatField(default=0.0, verbose_name="Parlaklık")
    contrast = models.FloatField(default=1.0, verbose_name="Kontrast")
    saturation = models.FloatField(default=1.0, verbose_name="Doygunluk")
    sharpness = models.FloatField(default=1.0, verbose_name="Keskinlik")

    class Meta:
        verbose_name = "Kamera Kaydı"
        verbose_name_plural = "Kamera Kayıtları"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self):
        return f"Capture #{self.id} - {self.timestamp.strftime('%H:%M:%S')}"

    @property
    def image_size_mb(self):
        """Base64 string boyutundan yaklaşık dosya boyutunu (MB) hesaplar."""
        if self.base64_image:
            size_bytes = (len(self.base64_image) * 3) / 4
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        return "0 MB"

    @property
    def settings_summary(self):
        """Admin panelinde özet göstermek için."""
        ae_status = "Otomatik" if self.ae_enable else f"Manuel (Exp:{self.exposure_time}, Gain:{self.analogue_gain})"
        awb_status = f"Otomatik ({self.awb_mode})" if self.awb_enable else "Manuel"
        return f"AE: {ae_status} | AWB: {awb_status} | Res: {self.resolution}"

    def get_image_preview(self):
        """Admin panelinde küçük önizleme göster (HTML)"""
        if self.base64_image:
            img_src = self.base64_image if self.base64_image.startswith(
                'data:') else f"data:image/jpeg;base64,{self.base64_image}"
            return format_html(
                '<img src="{}" width="100" height="75" style="object-fit: cover; border-radius: 4px;" />', img_src)
        return format_html('<span style="color: gray;">No image</span>')


# ============================================================================
# TARAMA MODELLERI
# ============================================================================

class Scan(models.Model):
    """
    Tek bir tarama işlemini ve analiz sonuçlarını saklar.
    """

    class Status(models.TextChoices):
        RUNNING = 'RUN', 'Çalışıyor'
        COMPLETED = 'CMP', 'Tamamlandı'
        INTERRUPTED = 'INT', 'Kesildi'
        ERROR = 'ERR', 'Hata'
        INSUFFICIENT_POINTS = 'ISP', 'Yetersiz Nokta'

    class ScanType(models.TextChoices):
        MANUAL = 'MAN', 'Manuel Haritalama'
        AUTONOMOUS = 'AUT', 'Otonom Sürüş'

    # Tarama Tipi
    scan_type = models.CharField(
        max_length=3,
        choices=ScanType.choices,
        default=ScanType.MANUAL,
        verbose_name="Tarama Tipi"
    )

    # Tarama Ayarları
    h_scan_angle_setting = models.FloatField(default=360.0, verbose_name="Yatay Tarama Açısı (°)")
    h_step_angle_setting = models.FloatField(default=10.0, verbose_name="Yatay Adım Açısı (°)")
    v_scan_angle_setting = models.FloatField(default=180.0, verbose_name="Dikey Tarama Açısı (°)")
    v_step_angle_setting = models.FloatField(default=10.0, verbose_name="Dikey Adım Açısı (°)")
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

    @property
    def duration(self):
        """Tarama süresi"""
        if self.end_time:
            return self.end_time - self.start_time
        return timezone.now() - self.start_time

    def run_analysis_and_update(self):
        """Bu taramaya ait noktaları analiz eder ve sonuçları günceller."""
        if not SCIPY_AVAILABLE:
            logger.error("scipy yüklü değil, analiz yapılamıyor")
            self.status = self.Status.ERROR
            self.save(update_fields=['status'])
            return

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
            # 2D Analiz
            points_2d = df[['y_cm', 'x_cm']].to_numpy()
            hull_2d = ConvexHull(points_2d)
            self.calculated_area_cm2 = hull_2d.volume
            self.perimeter_cm = hull_2d.area
            self.max_width_cm = df['y_cm'].max() - df['y_cm'].min()
            self.max_depth_cm = df['x_cm'].max() - df['x_cm'].min()

            # 3D Analiz
            points_3d = df[['x_cm', 'y_cm', 'z_cm']].to_numpy()
            hull_3d = ConvexHull(points_3d)
            self.calculated_volume_cm3 = hull_3d.volume
            self.max_height_cm = df['z_cm'].max() - df['z_cm'].min()

            logger.info(
                f"Analiz tamamlandı. 2D Alan: {self.calculated_area_cm2:.2f}, 3D Hacim: {self.calculated_volume_cm3:.2f}")
            self.status = self.Status.COMPLETED

        except QhullError as e:
            logger.error(f"Convex Hull hatası: {e}")
            self.status = self.Status.ERROR
        except Exception as e:
            logger.error(f"Analiz sırasında genel hata: {e}", exc_info=True)
            self.status = self.Status.ERROR

        self.save()


class ScanPoint(models.Model):
    """
    Bir tarama sırasında toplanan her bir ölçüm noktası.
    """
    scan = models.ForeignKey(Scan, related_name='points', on_delete=models.CASCADE, verbose_name="Tarama")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Zaman")

    # Motor Açıları
    derece = models.FloatField(verbose_name="Yatay Açı (°)", help_text="Pan açısı")
    dikey_aci = models.FloatField(null=True, blank=True, verbose_name="Dikey Açı (°)", help_text="Tilt açısı")

    # Ana Mesafe
    mesafe_cm = models.FloatField(verbose_name="Ana Mesafe (cm)", help_text="Birincil sensör okuması")

    # İki Bağımsız Sensör Verisi
    h_sensor_distance = models.FloatField(null=True, blank=True, verbose_name="H-Sensör Mesafesi (cm)")
    v_sensor_distance = models.FloatField(null=True, blank=True, verbose_name="V-Sensör Mesafesi (cm)")

    # Hız ve Koordinatlar
    hiz_cm_s = models.FloatField(null=True, blank=True, verbose_name="Hız (cm/s)")
    x_cm = models.FloatField(null=True, blank=True, verbose_name="X Koordinatı (cm)")
    y_cm = models.FloatField(null=True, blank=True, verbose_name="Y Koordinatı (cm)")
    z_cm = models.FloatField(null=True, blank=True, verbose_name="Z Koordinatı (cm)")

    class Meta:
        ordering = ['timestamp']
        verbose_name = "Tarama Noktası"
        verbose_name_plural = "Tarama Noktaları"

    def __str__(self):
        h_dist = f"{self.h_sensor_distance:.1f}" if self.h_sensor_distance else "N/A"
        v_dist = f"{self.v_sensor_distance:.1f}" if self.v_sensor_distance else "N/A"
        return f"Point H:{self.derece:.1f}° - Ana:{self.mesafe_cm:.1f}cm (H:{h_dist}, V:{v_dist})"


# ============================================================================
# SİSTEM LOGLARI
# ============================================================================

class SystemLog(models.Model):
    """Sistem olaylarını veritabanında saklar."""
    LOG_LEVELS = [('INFO', 'Bilgi'), ('WARNING', 'Uyarı'), ('ERROR', 'Hata'), ('CRITICAL', 'Kritik')]

    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Zaman")
    level = models.CharField(max_length=20, choices=LOG_LEVELS, default='INFO', verbose_name="Seviye")
    message = models.TextField(verbose_name="Mesaj")
    component = models.CharField(max_length=50, verbose_name="Bileşen")

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Sistem Logu'
        verbose_name_plural = 'Sistem Logları'
        indexes = [models.Index(fields=['-timestamp', 'level'])]

    def __str__(self):
        return f"[{self.level}] {self.component} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


# ============================================================================
# AI MODEL YAPILANDIRMASI
# ============================================================================

class AIModelConfiguration(models.Model):
    """AI Model API anahtarları ve yapılandırması"""
    PROVIDER_CHOICES = [('Google', 'Google (Gemini)'), ('OpenAI', 'OpenAI (GPT)'), ('Anthropic', 'Anthropic (Claude)'),
                        ('Other', 'Diğer')]

    model_provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default='Google',
                                      verbose_name="Sağlayıcı")
    name = models.CharField(max_length=100, unique=True, verbose_name="Yapılandırma Adı")
    model_name = models.CharField(max_length=100, verbose_name="Model Adı", help_text="Örn: gemini-1.5-flash")
    api_key = models.CharField(max_length=255, verbose_name="API Anahtarı")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI Model Yapılandırması"
        verbose_name_plural = "AI Model Yapılandırmaları"
        ordering = ['-is_active', 'name']

    def __str__(self):
        active_icon = "✓" if self.is_active else "✗"
        return f"{active_icon} {self.name} ({self.get_model_provider_display()})"

    def save(self, *args, **kwargs):
        if self.is_active:
            AIModelConfiguration.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

# scanner/models.py - Django Modelleri

import logging
import numpy as np
import pandas as pd
from django.db import models
from django.utils import timezone
from django.utils.html import format_html

try:
    from scipy.spatial import ConvexHull, QhullError
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logging.warning("scipy kütüphanesi bulunamadı. 3D analiz devre dışı.")

# Logger
logger = logging.getLogger(__name__)


# ============================================================================
# KAMERA MODELLERI
# ============================================================================

class CameraCapture(models.Model):
    """
    Kameradan çekilen fotoğrafları saklar.
    Base64 formatında görüntü ve metadata içerir.
    """
    EFFECT_CHOICES = [
        ('none', 'Normal'),
        ('grayscale', 'Gri Tonlama'),
        ('edges', 'Kenar Algılama'),
        ('invert', 'Ters Çevir'),
    ]

    # Görüntü verisi (Base64) - TextField kullanılmalı
    base64_image = models.TextField(
        verbose_name="Base64 Görüntü",
        help_text="Base64 encoded JPEG/PNG görüntü"
    )

    # Zaman damgası
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Zaman Damgası",
        help_text="Fotoğrafın çekildiği zaman"
    )

    # Uygulanan efekt
    effect = models.CharField(
        max_length=50,
        choices=EFFECT_CHOICES,
        default='none',
        verbose_name="Efekt",
        help_text="Uygulanan görüntü efekti"
    )

    # Motor açısı (Pan)
    pan_angle = models.FloatField(
        default=0.0,
        verbose_name="Pan Açısı (Yatay)",
        help_text="Yatay motor açısı (derece)"
    )

    # Mesafe bilgisi
    distance_info = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Mesafe Bilgisi",
        help_text="Ultrasonik sensör mesafe okuması (örn: '45.1 cm')"
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Kamera Fotoğrafı'
        verbose_name_plural = 'Kamera Fotoğrafları'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['effect']),
        ]

    def __str__(self):
        return f"Fotoğraf #{self.pk} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

    def get_image_preview(self):
        """Admin panelinde küçük önizleme göster (Django 3.0+ uyumlu)"""
        if self.base64_image:
            # İlk 100 karakter base64 prefix
            img_src = self.base64_image if self.base64_image.startswith('data:') else f"data:image/jpeg;base64,{self.base64_image[:100]}..."
            return format_html('<img src="{}" width="100" height="75" style="object-fit: cover;" />', img_src)
        return format_html('<span style="color: gray;">No image</span>')

    get_image_preview.short_description = 'Önizleme'

    @property
    def image_size_kb(self):
        """Görüntü boyutunu KB cinsinden hesapla"""
        if self.base64_image:
            return len(self.base64_image) / 1024
        return 0

    def save(self, *args, **kwargs):
        """Kaydetmeden önce validasyon"""
        # Açıyı sınırla (-180 ile 180 arası)
        if self.pan_angle < -180:
            self.pan_angle = -180
        elif self.pan_angle > 180:
            self.pan_angle = 180

        super().save(*args, **kwargs)


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
    h_scan_angle_setting = models.FloatField(
        default=360.0,
        verbose_name="Yatay Tarama Açısı (°)"
    )
    h_step_angle_setting = models.FloatField(
        default=10.0,
        verbose_name="Yatay Adım Açısı (°)"
    )
    v_scan_angle_setting = models.FloatField(
        default=180.0,
        verbose_name="Dikey Tarama Açısı (°)"
    )
    v_step_angle_setting = models.FloatField(
        default=10.0,
        verbose_name="Dikey Adım Açısı (°)"
    )
    steps_per_revolution_setting = models.IntegerField(
        default=4096,
        verbose_name="Motor Adım/Tur"
    )

    # Zaman ve Durum
    start_time = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Başlangıç Zamanı"
    )
    end_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Bitiş Zamanı"
    )
    status = models.CharField(
        max_length=3,
        choices=Status.choices,
        default=Status.RUNNING,
        verbose_name="Durum"
    )

    # Analiz Sonuçları
    point_count = models.IntegerField(
        default=0,
        verbose_name="Geçerli Nokta Sayısı"
    )
    calculated_area_cm2 = models.FloatField(
        null=True,
        blank=True,
        verbose_name="2D Alan (cm²)"
    )
    perimeter_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="2D Çevre (cm)"
    )
    max_width_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Maks. Genişlik (cm)"
    )
    max_depth_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Maks. Derinlik (cm)"
    )
    max_height_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Maks. Yükseklik (cm)"
    )
    calculated_volume_cm3 = models.FloatField(
        null=True,
        blank=True,
        verbose_name="3D Hacim (cm³)"
    )
    ai_commentary = models.TextField(
        blank=True,
        null=True,
        verbose_name="AI Yorumu"
    )

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
        """
        Bu taramaya ait noktaları analiz eder ve sonuçları günceller.
        """
        if not SCIPY_AVAILABLE:
            logger.error("scipy yüklü değil, analiz yapılamıyor")
            self.status = self.Status.ERROR
            self.save(update_fields=['status'])
            return

        logger.info(f"Scan ID {self.id} için analiz başlatılıyor...")

        # Geçerli noktaları filtrele
        points_qs = self.points.filter(
            mesafe_cm__gt=0.1,
            mesafe_cm__lt=400.0
        ).values('x_cm', 'y_cm', 'z_cm')

        point_count = points_qs.count()
        self.point_count = point_count

        if point_count < 15:
            logger.warning(f"Analiz için yetersiz nokta sayısı: {point_count}")
            self.status = self.Status.INSUFFICIENT_POINTS
            self.save(update_fields=['status', 'point_count'])
            return

        # DataFrame'e çevir
        df = pd.DataFrame(list(points_qs))
        df.dropna(inplace=True)

        try:
            # 2D Analiz (Üstten Görünüm x-y düzleminde)
            points_2d = df[['y_cm', 'x_cm']].to_numpy()
            hull_2d = ConvexHull(points_2d)
            self.calculated_area_cm2 = hull_2d.volume  # 2D'de volume = alan
            self.perimeter_cm = hull_2d.area  # 2D'de area = çevre
            self.max_width_cm = df['y_cm'].max() - df['y_cm'].min()
            self.max_depth_cm = df['x_cm'].max() - df['x_cm'].min()

            # 3D Analiz (Hacim ve Yükseklik)
            points_3d = df[['x_cm', 'y_cm', 'z_cm']].to_numpy()
            hull_3d = ConvexHull(points_3d)
            self.calculated_volume_cm3 = hull_3d.volume
            self.max_height_cm = df['z_cm'].max() - df['z_cm'].min()

            logger.info(
                f"Analiz tamamlandı. 2D Alan: {self.calculated_area_cm2:.2f} cm², "
                f"3D Hacim: {self.calculated_volume_cm3:.2f} cm³"
            )

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
    İKİ BAĞIMSIZ SENSÖR DESTEĞİ ile.
    """
    scan = models.ForeignKey(
        Scan,
        related_name='points',
        on_delete=models.CASCADE,
        verbose_name="Tarama"
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Zaman"
    )

    # Motor Açıları
    derece = models.FloatField(
        verbose_name="Yatay Açı (°)",
        help_text="Pan açısı"
    )
    dikey_aci = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Dikey Açı (°)",
        help_text="Tilt açısı"
    )

    # Ana Mesafe (öncelikli sensör)
    mesafe_cm = models.FloatField(
        verbose_name="Ana Mesafe (cm)",
        help_text="Birincil sensör okuması"
    )

    # === İKİ BAĞIMSIZ SENSÖR VERİSİ ===
    h_sensor_distance = models.FloatField(
        null=True,
        blank=True,
        verbose_name="H-Sensör Mesafesi (cm)",
        help_text="Yatay motor üzerindeki sensör okuması"
    )
    v_sensor_distance = models.FloatField(
        null=True,
        blank=True,
        verbose_name="V-Sensör Mesafesi (cm)",
        help_text="Dikey motor üzerindeki sensör okuması"
    )

    # Hız ve Koordinatlar
    hiz_cm_s = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Hız (cm/s)"
    )
    x_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="X Koordinatı (cm)"
    )
    y_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Y Koordinatı (cm)"
    )
    z_cm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Z Koordinatı (cm)"
    )

    class Meta:
        ordering = ['timestamp']
        verbose_name = "Tarama Noktası"
        verbose_name_plural = "Tarama Noktaları"

    def __str__(self):
        h_dist = f"{self.h_sensor_distance:.1f}" if self.h_sensor_distance else "N/A"
        v_dist = f"{self.v_sensor_distance:.1f}" if self.v_sensor_distance else "N/A"
        dikey = f"{self.dikey_aci:.1f}" if self.dikey_aci else "0.0"

        return (
            f"Point H:{self.derece:.1f}° V:{dikey}° - "
            f"Ana:{self.mesafe_cm:.1f}cm (H:{h_dist}, V:{v_dist})"
        )


# ============================================================================
# SİSTEM LOGLARı
# ============================================================================

class SystemLog(models.Model):
    """
    Sistem olaylarını loglar (opsiyonel).
    """
    LOG_LEVELS = [
        ('INFO', 'Bilgi'),
        ('WARNING', 'Uyarı'),
        ('ERROR', 'Hata'),
        ('CRITICAL', 'Kritik'),
    ]

    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Zaman"
    )
    level = models.CharField(
        max_length=20,
        choices=LOG_LEVELS,
        default='INFO',
        verbose_name="Seviye"
    )
    message = models.TextField(
        verbose_name="Mesaj"
    )
    component = models.CharField(
        max_length=50,
        verbose_name="Bileşen",
        help_text="camera, motor, sensor, etc."
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Sistem Logu'
        verbose_name_plural = 'Sistem Logları'
        indexes = [
            models.Index(fields=['-timestamp', 'level']),
        ]

    def __str__(self):
        return f"[{self.level}] {self.component} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


# ============================================================================
# AI MODEL YAPILANDIRMASI
# ============================================================================

class AIModelConfiguration(models.Model):
    """
    AI Model yapılandırması (Gemini, OpenAI, vb.)
    """
    PROVIDER_CHOICES = [
        ('Google', 'Google (Gemini)'),
        ('OpenAI', 'OpenAI (GPT)'),
        ('Anthropic', 'Anthropic (Claude)'),
        ('Other', 'Diğer'),
    ]

    model_provider = models.CharField(
        max_length=50,
        choices=PROVIDER_CHOICES,
        default='Google',
        verbose_name="Sağlayıcı"
    )
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Yapılandırma Adı",
        help_text="Örn: 'Production Gemini' veya 'Test GPT-4'"
    )
    model_name = models.CharField(
        max_length=100,
        verbose_name="Model Adı",
        help_text="Örn: gemini-1.5-flash-latest veya gpt-4-turbo"
    )
    api_key = models.CharField(
        max_length=255,
        verbose_name="API Anahtarı",
        help_text="Bu modele ait API key (güvenli saklanmalı)"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktif mi?"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Oluşturulma"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Güncellenme"
    )

    class Meta:
        verbose_name = "AI Model Yapılandırması"
        verbose_name_plural = "AI Model Yapılandırmaları"
        ordering = ['-is_active', 'name']

    def __str__(self):
        active_icon = "✓" if self.is_active else "✗"
        return f"{active_icon} {self.name} ({self.get_model_provider_display()})"

    def save(self, *args, **kwargs):
        """Sadece bir aktif model olmasını sağla"""
        if self.is_active:
            # Diğer aktif modelleri pasif yap
            AIModelConfiguration.objects.filter(
                is_active=True
            ).exclude(pk=self.pk).update(is_active=False)

        super().save(*args, **kwargs)
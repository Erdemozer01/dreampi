# scanner/models.py

# --- Gerekli Kütüphaneler ---
# Analiz fonksiyonu için bu importların dosyanın en üstünde olması gerekir.
import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull
from django.db import models
from django.utils import timezone


# --- Analiz Fonksiyonu ---
def perform_scan_analysis(scan_instance):
    """
    Bir Scan nesnesine bağlı noktaları analiz eder ve geometrik metrikleri hesaplar.
    Bu fonksiyon, save metodu tarafından otomatik olarak çağrılır.
    """
    print(f"Scan ID {scan_instance.id} için analiz başlatılıyor...")
    points_qs = scan_instance.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

    if points_qs.count() < 10:
        print("Analiz için yetersiz nokta sayısı.")
        scan_instance.status = Scan.Status.INSUFFICIENT_POINTS
        return None

    df = pd.DataFrame(list(points_qs.values('x_cm', 'y_cm')))

    try:
        points_2d = df[['x_cm', 'y_cm']].to_numpy()
        hull = ConvexHull(points_2d)

        results = {
            'area': hull.area,
            'perimeter': hull.volume,  # 2D'de 'volume' çevreyi verir
            'width': df['y_cm'].max() - df['y_cm'].min(),
            'depth': df['x_cm'].max() - df['x_cm'].min(),
        }
        print(f"Analiz tamamlandı: {results}")
        return results
    except Exception as e:
        print(f"Analiz sırasında kritik hata: {e}")
        scan_instance.status = Scan.Status.ERROR
        return None


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

    # Ayarlar
    start_angle_setting = models.FloatField(default=0.0)
    end_angle_setting = models.FloatField(default=0.0)
    step_angle_setting = models.FloatField(default=10.0)
    buzzer_distance_setting = models.IntegerField(default=10)


    # Zaman ve Durum
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=3, choices=Status.choices, default=Status.RUNNING)

    # Analiz Sonuçları
    calculated_area_cm2 = models.FloatField(null=True, blank=True)
    perimeter_cm = models.FloatField(null=True, blank=True)
    max_width_cm = models.FloatField(null=True, blank=True)
    max_depth_cm = models.FloatField(null=True, blank=True)
    ai_commentary = models.TextField(blank=True, null=True)

    steps_per_revolution_setting = models.IntegerField(
        default=4096,
        null=True,
        blank=True,
        verbose_name="Motor Adım/Tur Ayarı"
    )
    invert_motor_direction_setting = models.BooleanField(
        default=False,
        blank=True,
        verbose_name="Motor Yönü Ters Çevirme Ayarı"
    )

    def __str__(self):
        return f"Tarama #{self.id} ({self.get_status_display()}) - {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    def save(self, *args, **kwargs):
        """
        Model kaydedilirken durumu kontrol et ve gerekirse analizi tetikle.
        """
        is_new = self.pk is None
        original_status = None
        if not is_new:
            original_status = Scan.objects.get(pk=self.pk).status

        super().save(*args, **kwargs)  # Önce normal kaydetme işlemini yap

        # Eğer durum 'Çalışıyor'dan 'Tamamlandı'ya değiştiyse analizi tetikle
        if not is_new and original_status != self.Status.COMPLETED and self.status == self.Status.COMPLETED:
            analysis_results = perform_scan_analysis(self)

            if analysis_results:
                self.calculated_area_cm2 = analysis_results['area']
                self.perimeter_cm = analysis_results['perimeter']
                self.max_width_cm = analysis_results['width']
                self.max_depth_cm = analysis_results['depth']

                # Sadece analiz alanlarını güncellemek için tekrar kaydet
                super().save(
                    update_fields=['calculated_area_cm2', 'perimeter_cm', 'max_width_cm', 'max_depth_cm', 'status'])


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
    mesafe_cm_2 = models.FloatField(null=True, blank=True, verbose_name="2. Sensör Mesafe (cm)")

    class Meta:
        ordering = ['timestamp']
        verbose_name = "Tarama Noktası"
        verbose_name_plural = "Tarama Noktaları"

    def __str__(self):
        return f"Point at {self.derece}° - {self.mesafe_cm:.2f} cm"


class AIModelConfiguration(models.Model):
    """
    Farklı yapay zeka modellerinin yapılandırmalarını ve API anahtarlarını
    veritabanında saklamak için kullanılan model.
    """
    PROVIDER_CHOICES = [
        ('Google', 'Google'),
        ('OpenAI', 'OpenAI'),
        ('Other', 'Diğer'),
    ]

    name = models.CharField(max_length=100, unique=True,
                            help_text="Bu yapılandırma için akılda kalıcı bir isim (örn: Gemini Flash - Hızlı Analiz).")
    model_provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default='Google')
    model_name = models.CharField(max_length=100,
                                  help_text="API tarafından beklenen tam model adı (örn: gemini-1.5-flash-latest).")
    api_key = models.CharField(max_length=255, help_text="Bu modele ait API anahtarı.")
    is_active = models.BooleanField(default=True, help_text="Bu yapılandırma aktif olarak kullanılsın mı?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "AI Model Yapılandırması"
        verbose_name_plural = "AI Model Yapılandırmaları"
        ordering = ['-is_active', 'name']
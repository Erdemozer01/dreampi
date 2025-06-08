# scanner/management/commands/run_ai_analysis.py

from django.core.management.base import BaseCommand
from scanner.models import Scan, ScanPoint, AIModelConfiguration  # AIModelConfiguration import edildi
from scanner.ai_analyzer import AIAnalyzerService


class Command(BaseCommand):
    help = 'Veritabanında kayıtlı aktif AI yapılandırmasını kullanarak en son taramayı analiz eder.'

    def handle(self, *args, **options):
        self.stdout.write("AI Analiz komutu başlatıldı...")

        # 1. Aktif AI yapılandırmasını veritabanından çek
        active_config = AIModelConfiguration.objects.filter(is_active=True).first()
        if not active_config:
            self.stdout.write(self.style.ERROR(
                "❌ Veritabanında aktif bir AI yapılandırması bulunamadı. Lütfen Admin panelinden ekleyin."))
            return

        self.stdout.write(f"Kullanılacak AI Yapılandırması: '{active_config.name}'")

        # 2. Analiz edilecek taramayı seç
        latest_scan = Scan.objects.order_by('-start_time').first()
        if not latest_scan:
            self.stdout.write(self.style.ERROR("❌ Analiz edilecek tarama bulunamadı."))
            return

        self.stdout.write(f"En son tarama (ID: {latest_scan.id}) analiz için seçildi.")

        try:
            # 3. AI Servisini veritabanından gelen yapılandırma nesnesi ile başlat
            analyzer = AIAnalyzerService(config=active_config)

            # 4. Yapay zekaya sorulacak soruyu tanımla
            prompt = (
                "Bu 3D tarama verilerini analiz et. Ortamın genel şekli nedir (oda, koridor vb.)? "
                "Belirgin nesneler var mı? Varsa, bu nesnelerin konumu ve olası şekli hakkında bilgi ver. "
                "Özellikle z_cm (yükseklik) verisini dikkate alarak yorum yap."
            )

            # 5. Analizi gerçekleştir
            analysis_result = analyzer.analyze_model_data(
                django_model=ScanPoint,
                custom_prompt=prompt,
                fields=['derece', 'dikey_aci', 'mesafe_cm', 'x_cm', 'y_cm', 'z_cm'],
                scan=latest_scan
            )

            # 6. Sonucu ekrana yazdır
            self.stdout.write(self.style.SUCCESS("\n--- YAPAY ZEKA ANALİZ SONUCU ---"))
            self.stdout.write(analysis_result)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Analiz sırasında beklenmedik bir hata oluştu: {e}"))
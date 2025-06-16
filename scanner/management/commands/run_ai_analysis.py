# scanner/management/commands/run_ai_analysis.py

from django.core.management.base import BaseCommand
from django.db.models import Q
from scanner.models import Scan, AIModelConfiguration
from scanner.ai_analyzer import AIAnalyzerService
import traceback


class Command(BaseCommand):
    help = 'Aktif AI yapılandırmasını kullanarak, yorumu olmayan en son tamamlanmış taramayı analiz eder.'

    def add_arguments(self, parser):
        parser.add_argument('--scan-id', type=int, help='Belirli bir tarama ID\'sini analiz et.')
        parser.add_argument('--force', action='store_true',
                            help='Mevcut bir yorum olsa bile analizi zorla yeniden çalıştır.')

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("AI Analiz ve Görselleştirme Komutu Başlatıldı..."))

        # 1. Aktif AI yapılandırmasını bul
        active_config = AIModelConfiguration.objects.filter(is_active=True).first()
        if not active_config:
            self.stdout.write(self.style.ERROR("❌ Veritabanında aktif bir AI yapılandırması bulunamadı."))
            return
        self.stdout.write(f"Kullanılacak AI Yapılandırması: '{active_config.name}'")

        # 2. Analiz edilecek taramayı seç
        scan_to_analyze = self.get_scan_to_analyze(options)
        if not scan_to_analyze:
            return  # get_scan_to_analyze fonksiyonu zaten mesajı yazdırır

        self.stdout.write(f"Tarama (ID: {scan_to_analyze.id}) analiz için seçildi.")

        try:
            # ADIM 1: Metinsel Yorumu Al (Encoder)
            self.stdout.write("Metinsel yorum için AI ile iletişim kuruluyor...")
            analyzer = AIAnalyzerService(config=active_config)
            text_interpretation = analyzer.get_text_interpretation(scan=scan_to_analyze)

            if not text_interpretation or "hata" in text_interpretation.lower():
                self.stdout.write(
                    self.style.ERROR(f"❌ Yapay zeka geçerli bir metin yorumu döndürmedi: {text_interpretation}"))
                return

            # Metinsel sonucu veritabanına kaydet
            scan_to_analyze.ai_commentary = text_interpretation
            scan_to_analyze.save(update_fields=['ai_commentary'])

            self.stdout.write(self.style.SUCCESS("\n--- ÜRETİLEN METİN YORUMU ---"))
            self.stdout.write(text_interpretation)
            self.stdout.write(self.style.SUCCESS(f"\n✅ Yorum, Tarama ID {scan_to_analyze.id} kaydına eklendi."))

            # ADIM 2: Resim Oluştur (Decoder)
            # Bu adımda, gerçek bir resim oluşturma API'si yerine,
            # üretilen metinden bir URL oluşturan basit bir simülasyon kullanacağız.
            # Gelecekte burası Imagen API çağrısıyla değiştirilebilir.
            self.stdout.write("\nMetinden resim oluşturuluyor...")
            # (Bu fonksiyonun ai_services.py içinde olduğu varsayılıyor)
            # image_url = generate_image_from_text(text_interpretation)
            # self.stdout.write(self.style.SUCCESS(f"✅ Resim başarıyla oluşturuldu: {image_url}"))
            # scan_to_analyze.ai_image_url = image_url
            # scan_to_analyze.save(update_fields=['ai_image_url'])

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ İşlem sırasında beklenmedik bir hata oluştu: {e}"))
            traceback.print_exc()

    def get_scan_to_analyze(self, options):
        scan_id = options['scan_id']
        force_run = options['force']
        if scan_id:
            try:
                scan = Scan.objects.get(id=scan_id)
                if scan.ai_commentary and not force_run:
                    self.stdout.write(self.style.WARNING(f"⚠️ ID {scan_id} zaten bir yoruma sahip. --force kullanın."))
                    return None
                return scan
            except Scan.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"❌ ID'si {scan_id} olan bir tarama bulunamadı."))
                return None
        else:
            scan = Scan.objects.filter(
                Q(status=Scan.Status.COMPLETED) | Q(status=Scan.Status.INSUFFICIENT_POINTS),
                ai_commentary__isnull=True
            ).order_by('-start_time').first()
            if not scan:
                self.stdout.write(self.style.WARNING("✅ Analiz edilecek yeni bir tarama bulunamadı."))
            return scan

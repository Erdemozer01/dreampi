import pandas as pd
import google.generativeai as genai
from django.db.models import Model
from .models import AIModelConfiguration
import json
import traceback


class AIAnalyzerService:
    """
    Veritabanından alınan bir AIModelConfiguration nesnesine göre
    metinsel analiz ve yorumlama gerçekleştiren servis.
    Bu servis bir "Encoder" görevi görür.
    """

    def __init__(self, config: AIModelConfiguration):
        """
        AI servisini, veritabanından gelen bir yapılandırma nesnesi ile başlatır.
        """
        if not config or not isinstance(config, AIModelConfiguration):
            raise ValueError("Geçerli bir AIModelConfiguration nesnesi gereklidir.")

        self.config = config
        try:
            genai.configure(api_key=self.config.api_key)
            self.model = genai.GenerativeModel(self.config.model_name)
            # DÜZELTME: Unicode emoji (✅) kaldırıldı.
            print(f"[SUCCESS] AI Servisi: '{self.config.model_name}' modeli başarıyla yüklendi.")
        except Exception as e:
            # DÜZELTME: Unicode emoji (❌) kaldırıldı.
            print(
                f"[ERROR] HATA: '{self.config.model_name}' modeli yüklenemedi. Model adını veya API anahtarını kontrol edin.")
            raise e

    def get_text_interpretation(self, scan: 'Scan') -> str:
        """
        Bir Scan nesnesine bağlı noktaları alır, özetler ve Gemini'ye göndererek
        ortam hakkında sanatsal ve betimleyici bir metin üretmesini sağlar.

        Args:
            scan (Scan): Analiz edilecek tarama nesnesi.

        Returns:
            str: Yapay zeka tarafından üretilen metinsel yorum.
        """
        # DÜZELTME: Unicode emoji (🔍) kaldırıldı.
        print(f"[INFO] Scan ID {scan.id} için veritabanı sorgulanıyor...")
        queryset = scan.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

        if not queryset.exists():
            return "Analiz için uygun veri bulunamadı."

        # Daha verimli bir prompt için veriyi özetleyelim
        df = pd.DataFrame(list(queryset.values('derece', 'dikey_aci', 'mesafe_cm')))
        data_summary = df.describe().to_string()  # İstatistiksel özet
        sample_data = df.sample(min(len(df), 15)).to_string()  # Rastgele 15 örnek

        # DÜZELTME: Unicode emoji (📊) kaldırıldı.
        print(f"[INFO] {len(df)} adet kayıt özetlendi. Yorumlama için Gemini'ye gönderiliyor...")

        # Sanatsal bir prompt oluşturmak için Gemini'ye gönderilecek talimat
        full_prompt = (
            f"Sen, bir mekanın ruhunu sensör verilerinden okuyabilen bir şair/sanatçısın. "
            f"Görevin, aşağıda verilen düşük çözünürlüklü 3D tarama verilerinin istatistiksel özetini ve birkaç örneğini inceleyerek, "
            f"bu mekanın atmosferini, olası içeriğini ve hissettirdiklerini betimleyen canlı bir paragraf yazmaktır. "
            f"Bu metin, bir resim yapay zekasına ilham vermek için kullanılacak. Somut olmaktan çekinme, boşlukları hayal gücünle doldur.\n\n"
            f"--- Veri Özeti ---\n{data_summary}\n\n"
            f"--- Veri Örnekleri ---\n{sample_data}\n\n"
            f"--- Betimleme ---\n"
        )

        try:
            response = self.model.generate_content(full_prompt)
            # DÜZELTME: Unicode emoji (✅) kaldırıldı.
            print("[SUCCESS] Metinsel yorum başarıyla alındı!")
            return response.text.strip()
        except Exception as e:
            # DÜZELTME: Unicode emoji (❌) kaldırıldı.
            print(f"[ERROR] Gemini modelinden yanıt alınırken bir hata oluştu: {e}")
            return f"Analiz sırasında bir hata meydana geldi: {e}"

# scanner/ai_analyzer.py

import pandas as pd
import google.generativeai as genai
from django.db.models import Model
from .models import AIModelConfiguration, Scan
import json
import traceback
import urllib.parse  # Resim URL'i için gerekli


class AIAnalyzerService:
    """
    Veritabanından alınan bir AIModelConfiguration nesnesine göre
    metinsel analiz ve görselleştirme gerçekleştiren servis.
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
            self.text_model = genai.GenerativeModel(self.config.model_name)
            print(f"[SUCCESS] AI Servisi: '{self.config.model_name}' metin modeli başarıyla yüklendi.")
        except Exception as e:
            print(
                f"[ERROR] HATA: '{self.config.model_name}' modeli yüklenemedi. Model adını veya API anahtarını kontrol edin.")
            raise e

    def get_text_interpretation(self, scan: Scan) -> str:
        """
        Bir Scan nesnesine bağlı noktaları alır, özetler ve Gemini'ye göndererek
        ortam hakkında sanatsal ve betimleyici bir metin üretmesini sağlar. (ENCODER)
        """
        print(f"[INFO] Scan ID {scan.id} için veritabanı sorgulanıyor...")
        queryset = scan.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

        if not queryset.exists():
            return "Analiz için uygun veri bulunamadı."

        df = pd.DataFrame(list(queryset.values('derece', 'dikey_aci', 'mesafe_cm')))
        data_summary = df.describe().to_string()
        sample_data = df.sample(min(len(df), 15)).to_string()

        print(f"[INFO] {len(df)} adet kayıt özetlendi. Yorumlama için Gemini'ye gönderiliyor...")

        full_prompt = (
            f"Sen, bir mekanın ruhunu sensör verilerinden okuyabilen bir şair/sanatçısın. "
            f"Görevin, aşağıda verilen düşük çözünürlüklü 3D tarama verilerini inceleyerek, "
            f"bu mekanın atmosferini, olası içeriğini ve hissettirdiklerini betimleyen canlı bir paragraf yazmaktır. "
            f"Bu metin, bir resim yapay zekasına ilham vermek için kullanılacak. Somut olmaktan çekinme, boşlukları hayal gücünle doldur.\n\n"
            f"--- Veri Özeti ---\n{data_summary}\n\n"
            f"--- Veri Örnekleri ---\n{sample_data}\n\n"
            f"--- Betimleme ---\n"
        )

        try:
            response = self.text_model.generate_content(full_prompt)
            print("[SUCCESS] Metinsel yorum başarıyla alındı!")
            return response.text.strip()
        except Exception as e:
            print(f"[ERROR] Gemini modelinden yanıt alınırken bir hata oluştu: {e}")
            return f"Analiz sırasında bir hata meydana geldi: {e}"

    # --- YENİ FONKSİYON ---
    def generate_image_from_text(self, text_prompt: str) -> str:
        """
        Verilen metin prompt'unu kullanarak bir resim oluşturur ve resmin URL'ini döndürür. (DECODER)
        Not: Bu fonksiyon şimdilik basit bir URL servisi kullanır.
             Gelecekte Google Imagen API ile değiştirilebilir.
        """
        print(f"[INFO] Alınan metin ile resim oluşturuluyor: '{text_prompt[:50]}...'")

        # Metni URL formatına uygun hale getir (boşlukları %20 vb. ile değiştirir)
        encoded_prompt = urllib.parse.quote(text_prompt)

        # Pollinations.ai servisini kullanarak anında bir resim URL'i oluşturuyoruz.
        # Bu URL, tarayıcı tarafından çağrıldığında bir resim üretecektir.
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

        print(f"[SUCCESS] Resim URL'i başarıyla oluşturuldu.")
        return image_url


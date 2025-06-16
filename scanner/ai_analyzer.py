# scanner/ai_analyzer.py

import pandas as pd
import google.generativeai as genai
from django.db.models import Model
from .models import AIModelConfiguration, Scan
import json
import traceback
import requests
import base64


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
        Bir Scan nesnesine bağlı noktaları alır ve __init__ içinde başlatılan Gemini modeli ile yorumlar. (ENCODER)
        """
        print(f"[INFO] Scan ID {scan.id} için veritabanı sorgulanıyor...")
        queryset = scan.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

        if not queryset.exists():
            return "Analiz için uygun veri bulunamadı."

        df = pd.DataFrame(list(queryset.values('derece', 'dikey_aci', 'mesafe_cm')))
        data_summary = df.describe().to_string()
        sample_data = df.sample(min(len(df), 15)).to_string()

        print(f"[INFO] {len(df)} adet kayıt özetlendi. Yorumlama için {self.config.model_name}'e gönderiliyor...")

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

    def generate_image_with_imagen(self, text_prompt: str) -> str:
        """
        Verilen metin prompt'unu kullanarak Google'ın resim oluşturma modeli ile
        bir resim oluşturur ve resmin data URI'ını döndürür. (DECODER)
        """
        print(f"[INFO] Resim oluşturma modeli ile resim oluşturuluyor: '{text_prompt[:70]}...'")

        # DÜZELTME: Google'ın resim oluşturma için sunduğu doğru ve stabil model adı kullanılıyor.
        IMAGE_MODEL_NAME = "imagen-3.0-generate-002"
        API_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_MODEL_NAME}:predict?key={self.config.api_key}"

        style_keywords = "photorealistic, 4k, digital art, futuristic, point cloud scan, cinematic lighting"
        full_image_prompt = f"{text_prompt}, {style_keywords}"

        payload = {
            "instances": [{"prompt": full_image_prompt}],
            "parameters": {"sampleCount": 1}
        }

        try:
            response = requests.post(API_ENDPOINT, json=payload, timeout=90)

            if response.status_code != 200:
                error_details = "Bilinmeyen API Hatası"
                try:
                    error_json = response.json()
                    error_details = error_json.get('error', {}).get('message', response.text)
                except json.JSONDecodeError:
                    error_details = response.text
                print(f"[ERROR] Resim API Hatası (Kod: {response.status_code}): {error_details}")
                return f"API Hatası (Kod: {response.status_code}): {error_details}"

            result = response.json()

            if 'predictions' in result and result['predictions']:
                base64_image = result['predictions'][0].get('bytesBase64Encoded')
                if base64_image:
                    print("[SUCCESS] Resim başarıyla oluşturuldu.")
                    return f"data:image/png;base64,{base64_image}"

            print("[ERROR] API'den resim verisi alınamadı. Dönen cevap:", result)
            return "Resim oluşturulamadı (API'den boş veya hatalı yanıt)."

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] API'ye bağlanırken hata oluştu: {e}")
            return f"Resim oluşturma servisine bağlanılamadı: {e}"
        except Exception as e:
            print(f"[ERROR] Resim oluşturma sırasında genel bir hata oluştu: {e}")
            return f"Resim oluşturulurken beklenmedik bir hata oluştu: {e}"

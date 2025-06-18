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

    def get_text_interpretation(self, scan: Scan) -> tuple[str, str]:
        """
        Sensör verilerinin tamamını analiz eder. Önce Türkçe bir teknik rapor,
        sonra bu raporun özetinden İngilizce bir resim prompt'u üretir.
        """
        print(f"[INFO] Scan ID {scan.id} için veritabanı sorgulanıyor...")
        queryset = scan.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

        if not queryset.exists():
            return "Analiz için uygun veri bulunamadı.", "No data to generate an image from."

        df = pd.DataFrame(list(queryset.values('derece', 'dikey_aci', 'mesafe_cm')))
        data_string = df.head(1000).to_string(index=False)

        print(f"[INFO] {len(df)} adet noktanın tamamı analiz için {self.config.model_name}'e gönderiliyor...")

        h_angle = scan.h_scan_angle_setting
        v_angle = scan.v_scan_angle_setting

        # DÜZELTME: Prompt, yapay zekayı önce analiz yapıp sonra bu analizi özetlemeye yönlendiriyor.
        full_prompt = (
            f"You are a visionary artist who can see entire worlds in sparse data. Your task is to interpret the following 3D sensor data. "
            f"From these abstract points, dream up a complete, immersive, 360-degree panoramic scene. "
            f"Your output MUST be a valid JSON object with two keys: 'turkish_analysis' and 'english_image_prompt'.\n"
            f"1. For 'turkish_analysis' (in TURKISH): Describe your vision with poetic and artistic language. What does this space feel like? What story does it tell?\n"
            f"2. For 'english_image_prompt' (in ENGLISH): Provide a rich, detailed description of the full 360-degree scene. This will be used to generate an equirectangular panorama for a VR experience.\n\n"
            f"--- Sensor Data ---\n{data_string}\n\n"
            f"--- Generate Visionary JSON Report ---\n"
        )

        try:
            response = self.text_model.generate_content(full_prompt)
            print("[SUCCESS] İkili dilde yorum ve özet başarıyla alındı!")

            json_response_text = response.text.strip()
            if json_response_text.startswith("```json"):
                json_response_text = json_response_text[7:-3].strip()

            data = json.loads(json_response_text)

            turkish_analysis = data.get("turkish_analysis", "Türkçe analiz üretilemedi.")
            english_image_prompt = data.get("english_image_prompt", "English image prompt could not be generated.")

            return turkish_analysis, english_image_prompt

        except (json.JSONDecodeError, KeyError) as e:
            print(f"[ERROR] Gemini modelinden gelen JSON yanıtı ayrıştırılamadı: {e}")
            return "Analiz sırasında bir JSON hatası meydana geldi.", "JSON parsing error."
        except Exception as e:
            print(f"[ERROR] Gemini modelinden yanıt alınırken bir hata oluştu: {e}")
            return "Analiz sırasında bir hata meydana geldi.", "API error during analysis."

    def generate_image_with_imagen(self, text_prompt: str) -> str:
        """
        Verilen İngilizce özet betimlemeyi kullanarak Google Imagen ile bir resim oluşturur. (DECODER)
        """
        print(f"[INFO] Resim oluşturma modeli ile resim oluşturuluyor: '{text_prompt[:70]}...'")

        IMAGE_MODEL_NAME = "imagen-3.0-generate-002"
        API_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_MODEL_NAME}:predict?key={self.config.api_key}"

        full_image_prompt = (
            f"A photorealistic, 4k, cinematic image of the following scene, which is a reconstruction from sensor data: {text_prompt}. "
            f"The image should have a clean, modern, slightly technical aesthetic."
        )

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

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
            # API anahtarını yapılandır ve metin modelini başlat
            genai.configure(api_key=self.config.api_key)
            self.text_model = genai.GenerativeModel(self.config.model_name)
            print(f"[SUCCESS] AI Servisi: '{self.config.model_name}' metin modeli başarıyla yüklendi.")
        except Exception as e:
            print(
                f"[ERROR] HATA: '{self.config.model_name}' modeli yüklenemedi. Model adını veya API anahtarını kontrol edin.")
            raise e

    def get_text_interpretation(self, scan: Scan) -> tuple[str, str]:
        """
        Sensör verilerini analiz eder ve biri kullanıcı için Türkçe analiz, diğeri
        resim modeli için İngilizce prompt olmak üzere iki metin döndürür. (ENCODER)
        """
        print(f"[INFO] Scan ID {scan.id} için veritabanı sorgulanıyor...")
        queryset = scan.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

        if not queryset.exists():
            return "Analiz için uygun veri bulunamadı.", "No data to generate an image from."

        df = pd.DataFrame(list(queryset.values('derece', 'dikey_aci', 'mesafe_cm')))
        data_summary = df.describe().to_string()

        print(f"[INFO] {len(df)} adet kayıt özetlendi. Yorumlama için {self.config.model_name}'e gönderiliyor...")

        h_angle = scan.h_scan_angle_setting
        v_angle = scan.v_scan_angle_setting

        full_prompt = (
            f"You are a 3D Scene Reconstruction Analyst. Your task is to interpret the following statistical summary of sparse 3D sensor data, considering the scan settings used. "
            f"The scan was performed with a horizontal angle of {h_angle} degrees and a vertical angle of {v_angle} degrees. "
            f"Your output MUST be a valid JSON object containing two keys: 'turkish_analysis' and 'english_image_prompt'.\n"
            f"1. For 'turkish_analysis', provide a detailed technical analysis of the scene in TURKISH. Use the provided scan settings ({h_angle}° horizontal, {v_angle}° vertical) and the data summary to deduce the most likely objects and their layout.\n"
            f"2. For 'english_image_prompt', provide a concise, descriptive scene description in ENGLISH, based on your analysis.\n"
            f"Example JSON output for a different scan: {{"
            f"  \"turkish_analysis\": \"Sensör verileri yaklaşık 270 derecelik geniş bir yatay taramayı ve 90 dereceye varan bir dikey hareketi göstermektedir. Mesafeler 350cm'ye kadar uzanmakta, bu da orta büyüklükte bir odaya işaret etmektedir. 150cm uzaklıktaki geniş ve düz bir küme muhtemelen bir duvardır. Önünde, 80cm yükseklikteki dikdörtgen küme, bir çalışma masası olarak yorumlanmıştır.\", "
            f"  \"english_image_prompt\": \"A work desk with a computer monitor and an office chair in a medium-sized room, based on a 3D sensor scan.\""
            f"}}\n\n"
            f"--- Data Summary for This Scan ---\n{data_summary}\n\n"
            f"--- Generate JSON Output for the {h_angle}°x{v_angle}° Scan ---\n"
        )

        try:
            response = self.text_model.generate_content(full_prompt)
            print("[SUCCESS] İkili dilde yorum başarıyla alındı!")

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
        Verilen İngilizce betimlemeyi kullanarak Google Imagen ile bir resim oluşturur. (DECODER)
        """
        print(f"[INFO] Resim oluşturma modeli ile resim oluşturuluyor: '{text_prompt[:70]}...'")

        IMAGE_MODEL_NAME = "imagen-3.0-generate-002"

        # DÜZELTME: URL'deki hatalı Markdown formatı kaldırıldı.
        API_ENDPOINT = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){IMAGE_MOD
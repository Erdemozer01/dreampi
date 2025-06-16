# scanner/ai_analyzer.py

import pandas as pd
import google.generativeai as genai
from django.db.models import Model
from .models import AIModelConfiguration, Scan
import json
import traceback
import requests
import base64
import numpy as np


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

        # DÜZELTME: Veriyi daha anlamlı hale getirmek için ön işleme yapıyoruz.
        df = pd.DataFrame(list(queryset.values('x_cm', 'y_cm', 'z_cm')))
        df.dropna(inplace=True)

        print(f"[INFO] {len(df)} adet kayıt özetlendi. Yorumlama için {self.config.model_name}'e gönderiliyor...")

        # --- YENİ: Veriyi Izgara Yapısına Dönüştürme ---
        # Tarama alanını 5x5'lik bir ızgaraya böl ve her hücre için özet bilgi çıkar.
        x_min, x_max = df['x_cm'].min(), df['x_cm'].max()
        y_min, y_max = df['y_cm'].min(), df['y_cm'].max()

        grid_x = np.linspace(x_min, x_max, 6)
        grid_y = np.linspace(y_min, y_max, 6)

        grid_summary = []
        for i in range(5):
            row_summary = []
            for j in range(5):
                cell_df = df[
                    (df['x_cm'] >= grid_x[i]) & (df['x_cm'] < grid_x[i + 1]) &
                    (df['y_cm'] >= grid_y[j]) & (df['y_cm'] < grid_y[j + 1])
                    ]
                if not cell_df.empty:
                    row_summary.append({
                        "nokta_sayisi": len(cell_df),
                        "ortalama_yukseklik_cm": round(cell_df['z_cm'].mean(), 1)
                    })
                else:
                    row_summary.append({"nokta_sayisi": 0})
            grid_summary.append(row_summary)

        grid_summary_text = json.dumps(grid_summary, indent=2, ensure_ascii=False)
        # ----------------------------------------------

        h_angle = scan.h_scan_angle_setting
        v_angle = scan.v_scan_angle_setting

        # DÜZELTME: Prompt, artık yapılandırılmış ızgara verisini alıyor.
        full_prompt = (
            f"You are a digital forensics expert. Your task is to analyze the following structured grid data derived from a 3D sensor scan. "
            f"The grid represents a top-down view of the scanned area, divided into 5x5 cells. Each cell shows the number of points detected and their average height in cm. "
            f"The scan was performed with a horizontal angle of {h_angle} degrees and a vertical angle of {v_angle} degrees. "
            f"Your output MUST be a valid JSON object with two keys: 'turkish_analysis' and 'english_image_prompt'.\n"
            f"1. For 'turkish_analysis' (in TURKISH): Analyze the grid summary. Identify high-density cells as potential objects. Use the average height to deduce what these objects might be (e.g., cells with 75cm height could be a desk). Describe the overall layout and object placement.\n"
            f"2. For 'english_image_prompt' (in ENGLISH): Synthesize your analysis into a single, rich, descriptive paragraph for an image generation AI. Describe the objects, their placement, the lighting, and the overall atmosphere of the scene.\n\n"
            f"--- Structured Grid Data (5x5, top-down view) ---\n{grid_summary_text}\n\n"
            f"--- Generate Forensic JSON Report ---\n"
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

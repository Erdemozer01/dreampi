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
    VeritabanÄ±ndan alÄ±nan bir AIModelConfiguration nesnesine gÃ¶re
    metinsel analiz ve gÃ¶rselleÅŸtirme gerÃ§ekleÅŸtiren servis.
    """

    def __init__(self, config: AIModelConfiguration):
        """
        AI servisini, veritabanÄ±ndan gelen bir yapÄ±landÄ±rma nesnesi ile baÅŸlatÄ±r.
        """
        if not config or not isinstance(config, AIModelConfiguration):
            raise ValueError("GeÃ§erli bir AIModelConfiguration nesnesi gereklidir.")

        self.config = config
        try:
            # API anahtarÄ±nÄ± yapÄ±landÄ±r ve metin modelini baÅŸlat
            genai.configure(api_key=self.config.api_key)
            self.text_model = genai.GenerativeModel(self.config.model_name)
            print(f"[SUCCESS] AI Servisi: '{self.config.model_name}' metin modeli baÅŸarÄ±yla yÃ¼klendi.")
        except Exception as e:
            print(
                f"[ERROR] HATA: '{self.config.model_name}' modeli yÃ¼klenemedi. Model adÄ±nÄ± veya API anahtarÄ±nÄ± kontrol edin.")
            raise e

    def get_text_interpretation(self, scan: Scan) -> tuple[str, str]:
        """
        SensÃ¶r verilerini analiz eder ve biri kullanÄ±cÄ± iÃ§in TÃ¼rkÃ§e analiz, diÄŸeri
        resim modeli iÃ§in Ä°ngilizce prompt olmak Ã¼zere iki metin dÃ¶ndÃ¼rÃ¼r. (ENCODER)
        """
        print(f"[INFO] Scan ID {scan.id} iÃ§in veritabanÄ± sorgulanÄ±yor...")
        queryset = scan.points.filter(mesafe_cm__gt=0.1, mesafe_cm__lt=400.0)

        if not queryset.exists():
            return "Analiz iÃ§in uygun veri bulunamadÄ±.", "No data to generate an image from."

        df = pd.DataFrame(list(queryset.values('derece', 'dikey_aci', 'mesafe_cm')))
        data_summary = df.describe().to_string()

        print(f"[INFO] {len(df)} adet kayÄ±t Ã¶zetlendi. Yorumlama iÃ§in {self.config.model_name}'e gÃ¶nderiliyor...")

        h_angle = scan.h_scan_angle_setting
        v_angle = scan.v_scan_angle_setting

        # DÃœZELTME: Prompt, yapay zekayÄ± bir "dedektif" gibi davranmaya, kanÄ±tlarÄ± yorumlamaya ve detaylÄ± bir rapor sunmaya yÃ¶nlendiriyor.
        full_prompt = (
            f"You are a digital forensics expert, specializing in reconstructing scenes from sparse sensor data. Your task is to analyze the following data. "
            f"The scan was performed with a horizontal angle of {h_angle} degrees and a vertical angle of {v_angle} degrees. "
            f"Your output MUST be a valid JSON object with two keys: 'turkish_analysis' and 'english_image_prompt'.\n"
            f"1. For 'turkish_analysis' (in TURKISH): Write a detailed forensic report. Start with an analysis of the scan parameters ({h_angle}Â°x{v_angle}Â°) and the data summary to estimate the overall room size. Then, identify clusters of points and deduce what they most likely are (e.g., 'a large vertical plane is likely a wall', 'a flat horizontal cluster at 75cm height is likely a desk'). Conclude with an estimated area and perimeter based on the data. Be descriptive and explain your reasoning.\n"
            f"2. For 'english_image_prompt' (in ENGLISH): Synthesize your analysis into a single, rich, descriptive paragraph for an image generation AI. Describe the objects, their placement, the lighting, and the overall atmosphere of the scene.\n\n"
            f"--- Data Summary for This Scan ---\n{data_summary}\n\n"
            f"--- Generate Forensic JSON Report ---\n"
        )

        try:
            response = self.text_model.generate_content(full_prompt)
            print("[SUCCESS] Ä°kili dilde yorum baÅŸarÄ±yla alÄ±ndÄ±!")

            json_response_text = response.text.strip()
            if json_response_text.startswith("```json"):
                json_response_text = json_response_text[7:-3].strip()

            data = json.loads(json_response_text)

            turkish_analysis = data.get("turkish_analysis", "TÃ¼rkÃ§e analiz Ã¼retilemedi.")
            english_image_prompt = data.get("english_image_prompt", "English image prompt could not be generated.")

            return turkish_analysis, english_image_prompt

        except (json.JSONDecodeError, KeyError) as e:
            print(f"[ERROR] Gemini modelinden gelen JSON yanÄ±tÄ± ayrÄ±ÅŸtÄ±rÄ±lamadÄ±: {e}")
            return "Analiz sÄ±rasÄ±nda bir JSON hatasÄ± meydana geldi.", "JSON parsing error."
        except Exception as e:
            print(f"[ERROR] Gemini modelinden yanÄ±t alÄ±nÄ±rken bir hata oluÅŸtu: {e}")
            return "Analiz sÄ±rasÄ±nda bir hata meydana geldi.", "API error during analysis."

    def generate_image_with_imagen(self, text_prompt: str) -> str:
        """
        Verilen Ä°ngilizce betimlemeyi kullanarak Google Imagen ile bir resim oluÅŸturur. (DECODER)
        """
        print(f"[INFO] Resim oluÅŸturma modeli ile resim oluÅŸturuluyor: '{text_prompt[:70]}...'")

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
                error_details = "Bilinmeyen API HatasÄ±"
                try:
                    error_json = response.json()
                    error_details = error_json.get('error', {}).get('message', response.text)
                except json.JSONDecodeError:
                    error_details = response.text
                print(f"[ERROR] Resim API HatasÄ± (Kod: {response.status_code}): {error_details}")
                return f"API HatasÄ± (Kod: {response.status_code}): {error_details}"

            result = response.json()

            if 'predictions' in result and result['predictions']:
                base64_image = result['predictions'][0].get('bytesBase64Encoded')
                if base64_image:
                    print("[SUCCESS] Resim baÅŸarÄ±yla oluÅŸturuldu.")
                    return f"data:image/png;base64,{base64_image}"

            print("[ERROR] API'den resim verisi alÄ±namadÄ±. DÃ¶nen cevap:", result)
            return "Resim oluÅŸturulamadÄ± (API'den boÅŸ veya hatalÄ± yanÄ±t)."

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] API'ye baÄŸlanÄ±rken hata oluÅŸtu: {e}")
            return f"Resim oluÅŸturma servisine baÄŸlanÄ±lamadÄ±: {e}"
        except Exception as e:
            print(f"[ERROR] Resim oluÅŸturma sÄ±rasÄ±nda genel bir hata oluÅŸtu: {e}")
            return f"Resim oluÅŸturulurken beklenmedik bir hata oluÅŸtu: {e}"

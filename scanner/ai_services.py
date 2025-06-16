# scanner/ai_services.py

import google.generativeai as genai
from django.conf import settings
import pandas as pd
import json


# API anahtarının veritabanından alınacağını varsayarak,
# bu fonksiyonun çağrıldığı yerde configure edilmesi en doğrusudur.

def interpret_scan_data_with_gemini(scan_points_df: pd.DataFrame, api_key: str) -> str:
    """
    Ultrasonik tarama verisini (DataFrame) alıp, Gemini modeli ile yorumlar
    ve bir resim oluşturma yapay zekası için detaylı bir metin (prompt) üretir.
    """
    # API anahtarını fonksiyona gelen parametre ile yapılandır
    genai.configure(api_key=api_key)

    if scan_points_df.empty:
        return "Yorumlanacak tarama verisi bulunamadı."

    # Analiz için veriyi özetle (tüm veriyi göndermek yerine)
    data_summary = json.dumps(scan_points_df.head(25).to_dict(orient='records'), indent=2)

    # Gemini modelini başlat
    model = genai.GenerativeModel('gemini-1.5-flash-latest')

    # Yapay zekaya verilecek talimat (Prompt)
    prompt = f"""
    Sen, 3D sensör verilerini yorumlayan bir sanat eleştirmenisin. Görevin, aşağıda verilen düşük çözünürlüklü ultrasonik sensör verisinden yola çıkarak, ortamın atmosferini ve olası içeriğini betimleyen, sanatsal ve ilham verici bir metin yazmaktır. Bu metin, bir resim oluşturma motoru için kullanılacak. Açıklaman canlı, detaylı ve duygusal bir tona sahip olsun.

    İşte sensör verisi özeti (açı ve mesafe(cm)):
    {data_summary}

    Bu verilere dayanarak, odanın nasıl göründüğünü anlatan zengin bir metin oluştur. Örneğin: "Düşük çözünürlüklü tarama, bir çalışma masasının etrafındaki belirsiz şekilleri gösteriyor. Ortada büyük, düz bir yüzey, muhtemelen bir bilgisayar monitörünün önündeki bir klavyeyi temsil ediyor. Yüzeyin sağında ve solunda, kalemlik ve kitap yığını olabilecek daha dikey yapılar mevcut. Sahne, loş bir akşam ışığıyla aydınlatılıyor ve teknolojik bir yalnızlık hissi veriyor. Nokta bulutu stili, fütüristik ve dijital bir estetik katıyor."
    """

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API hatası: {e}")
        return f"Yapay zeka veriyi yorumlarken bir hata oluştu: {e}"
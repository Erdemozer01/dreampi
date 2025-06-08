# scanner/ai_analyzer.py

import pandas as pd
import google.generativeai as genai
from django.db.models import Model
from .models import AIModelConfiguration  # Kendi modelimizi import ediyoruz


class AIAnalyzerService:
    """
    Veritabanından alınan bir AIModelConfiguration nesnesine göre
    analiz gerçekleştiren yeniden kullanılabilir servis.
    """

    def __init__(self, config: AIModelConfiguration):
        """
        AI servisini, veritabanından gelen bir yapılandırma nesnesi ile başlatır.

        Args:
            config (AIModelConfiguration): Kullanılacak yapılandırmayı içeren model nesnesi.
        """
        if not config or not isinstance(config, AIModelConfiguration):
            raise ValueError("Geçerli bir AIModelConfiguration nesnesi gereklidir.")

        self.config = config
        self._configure_api()
        self.model = self._load_model()
        print(f"✅ AI Servisi: '{self.config.model_name}' modeli başarıyla yüklendi.")

    def _configure_api(self):
        """API anahtarını yapılandırma nesnesinden alarak genai kütüphanesini yapılandırır."""
        genai.configure(api_key=self.config.api_key)

    def _load_model(self) -> genai.GenerativeModel:
        """Model adını yapılandırma nesnesinden alarak modeli oluşturur."""
        try:
            return genai.GenerativeModel(self.config.model_name)
        except Exception as e:
            print(
                f"❌ HATA: '{self.config.model_name}' modeli yüklenemedi. Model adını veya API anahtarını kontrol edin.")
            raise e

    def analyze_model_data(self, django_model: Model, custom_prompt: str, fields: list = None, **filters) -> str:
        # Bu metodun içeriğinde herhangi bir değişiklik yapmaya gerek yok.
        # Aynen önceki gibi kalabilir.
        print(f"🔍 Veritabanı sorgulanıyor: Model={django_model.__name__}, Filtreler={filters}")
        queryset = django_model.objects.filter(**filters)
        if not queryset.exists():
            return f"Analiz için uygun veri bulunamadı. (Model: {django_model.__name__}, Filtre: {filters})"
        df = pd.DataFrame(list(queryset.values(*fields) if fields else queryset.values()))
        print(f"📊 {len(df)} adet kayıt DataFrame'e yüklendi. Analiz için gönderiliyor...")
        data_string = df.to_string()
        full_prompt = (
            f"Ultrasonic sensör mesafe ölçümlerinden elde edilen veriler analiz et:\n\n"
            f"--- VERİ TABLOSU ({django_model.__name__}) ---\n"
            f"{data_string}\n\n"
            f"--- ANALİZ İSTEĞİ ---\n"
            f"{custom_prompt}\n\n"
            f"Lütfen cevabını net başlıklar ve maddeler halinde Markdown formatında sun. "
            f"Multimodal özelliğinle resim oluştur. Resim tahmini yapma. Alan ve çevre tahmini yap."
            f"Bulunduğun ortamın geometrik şeklini tahmin et"
        )
        try:
            response = self.model.generate_content(full_prompt)
            print("✅ Analiz başarıyla tamamlandı!")
            return response.text
        except Exception as e:
            print(f"❌ Yapay zeka modelinden yanıt alınırken bir hata oluştu: {e}")
            return "Analiz sırasında bir hata meydana geldi."
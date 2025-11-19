# ai_vision.py - v1.5 (Distance Measurement + Resolution Crash Fix + Single Load)
# ÖZELLİK 1: Nesne türüne göre tahmini mesafe ölçümü (Monocular Distance Estimation).
# ÖZELLİK 2: Kamera çözünürlüğü değiştiğinde Hareket Algılama çökmesi düzeltildi.
# ÖZELLİK 3: Modeller sadece bir kez yüklenir (RAM tasarrufu).

import logging
import cv2
import numpy as np
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import threading

# Config dosyasından model yollarını almak için
try:
    from .config import AIConfig
except ImportError:
    from config import AIConfig

logger = logging.getLogger(__name__)

@dataclass
class Detection:
    """Tespit edilen nesne veri yapısı"""
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    color: Tuple[int, int, int] = (0, 255, 0)
    metadata: Dict[str, Any] = None
    distance_cm: float = None # Mesafe bilgisi

# --- MESAFE ÖLÇÜMÜ İÇİN SABİTLER ---
# Bilinen nesne genişlikleri (cm cinsinden - Ortalama değerler)
KNOWN_WIDTHS = {
    'person': 45.0,   # Ortalama omuz genişliği
    'car': 180.0,     # Ortalama araba genişliği
    'cell phone': 7.5,
    'bottle': 7.0,
    'cup': 8.0,
    'monitor': 50.0,
    'laptop': 35.0,
    'mouse': 6.0,
    'keyboard': 45.0,
    'book': 15.0,
    'chair': 50.0,
    'cat': 15.0,      # Ortalama kedi göğüs genişliği
    'dog': 20.0,      # Ortalama köpek göğüs genişliği
}

# Kameranın odak uzaklığı (Piksel cinsinden, kalibre edilebilir)
# Formül: F = (Piksel Genişliği x Bilinen Mesafe) / Bilinen Genişlik
# Varsayılan olarak 650px (VGA/HD için yaklaşık değer)
FOCAL_LENGTH = 650.0

class AIVisionManager:
    """
    Tüm AI ve Görüntü İşleme operasyonlarını yöneten merkezi sınıf.
    """
    def __init__(self):
        self.yolo_model = None
        self.face_cascade = None
        self.qr_decoder = None
        # Aktif modüllerin durumunu tutar
        self.enabled_modules = {
            'yolo': False,
            'face': False,
            'motion': False,
            'qr': False,
            'edges': False
        }
        self.lock = threading.Lock()
        self.prev_frame = None # Hareket algılama için referans kare

    def initialize_module(self, module_name: str, **kwargs) -> bool:
        """İstenen AI modülünü güvenli bir şekilde başlatır (Tekrar yüklemeyi önler)."""
        with self.lock:
            try:
                if module_name == 'yolo':
                    if not AIConfig.ENABLE_YOLO: return False
                    # Eğer model zaten yüklüyse tekrar yükleme (RAM koruması)
                    if self.yolo_model is None:
                        from ultralytics import YOLO
                        # Config'den gelen yolu string'e çevir
                        model_path = str(AIConfig.YOLO_MODEL_PATH)
                        self.yolo_model = YOLO(model_path)
                        logger.info(f"YOLO model loaded: {model_path}")

                    # Güven skoru kwargs ile gelirse güncellemeye gerek yok, predict sırasında kullanılır
                    self.enabled_modules['yolo'] = True
                    return True

                elif module_name == 'face':
                    if not AIConfig.ENABLE_FACE_DETECTION: return False
                    if self.face_cascade is None:
                        self.face_cascade = cv2.CascadeClassifier(AIConfig.FACE_CASCADE_PATH)
                    self.enabled_modules['face'] = True
                    return True

                elif module_name == 'motion':
                    self.enabled_modules['motion'] = True
                    # Hareket modülü her başladığında referans kareyi sıfırla
                    self.prev_frame = None
                    return True

                elif module_name == 'qr':
                    if self.qr_decoder is None:
                        from pyzbar.pyzbar import decode
                        self.qr_decoder = decode
                    self.enabled_modules['qr'] = True
                    return True

                elif module_name == 'edges':
                    self.enabled_modules['edges'] = True
                    return True

                return False
            except Exception as e:
                logger.error(f"Modül başlatma hatası ({module_name}): {e}")
                return False

    def calculate_distance(self, pixel_width, label):
        """Nesne etiketine ve piksel genişliğine göre cm cinsinden mesafe hesaplar."""
        real_width = KNOWN_WIDTHS.get(label)
        if real_width and pixel_width > 0:
            # Mesafe Formülü: D = (W x F) / P
            distance = (real_width * FOCAL_LENGTH) / pixel_width
            return round(distance, 1)
        return None

    def process_frame(self, frame: np.ndarray, modules: List[str] = None, draw_results: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Verilen bir kareyi (frame) aktif modüllerle işler.

        Args:
            frame: İşlenecek görüntü (numpy array)
            modules: Hangi modüllerin çalışacağı (None ise hepsi)
            draw_results: Sonuçların kare üzerine çizilip çizilmeyeceği

        Returns:
            (processed_frame, results_dict)
        """
        if frame is None: return None, {}

        # Modül listesi verilmezse, initialize edilmiş tüm modülleri kullan
        if modules is None:
            modules = [k for k, v in self.enabled_modules.items() if v]

        results = {
            'detections': [],
            'motion_percentage': 0.0,
            'edge_frame': None,
            'stats': {}
        }

        output_frame = frame.copy() if draw_results else frame

        # 1. YOLO (Nesne Tespiti + Mesafe)
        if 'yolo' in modules and self.yolo_model:
            try:
                # verbose=False: Konsol kirliliğini önler
                yolo_res = self.yolo_model.predict(frame, conf=AIConfig.YOLO_CONFIDENCE, verbose=False)

                for r in yolo_res:
                    boxes = r.boxes
                    for box in boxes:
                        # Koordinatları al
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        w = x2 - x1
                        h = y2 - y1

                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        # Model isimlerini güvenli al
                        if hasattr(self.yolo_model, 'names'):
                            label = self.yolo_model.names[cls_id]
                        else:
                            label = str(cls_id)

                        # Mesafe Hesapla
                        dist = self.calculate_distance(w, label)

                        # Sonucu kaydet
                        results['detections'].append(Detection(
                            label, conf, (x1, y1, w, h), (0, 255, 0), distance_cm=dist
                        ))

                        # Çizim
                        if draw_results:
                            cv2.rectangle(output_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            label_text = f"{label} {conf:.2f}"
                            if dist:
                                label_text += f" | {dist}cm"

                            # Metin arka planı (Okunabilirlik için)
                            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                            cv2.rectangle(output_frame, (x1, y1 - 20), (x1 + tw, y1), (0, 255, 0), -1)
                            cv2.putText(output_frame, label_text, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

                results['stats']['yolo_objects'] = len(results['detections'])
            except Exception as e:
                logger.error(f"YOLO error: {e}")

        # 2. Face Detection (Yüz Tanıma + Mesafe)
        if 'face' in modules and self.face_cascade:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.1, 5)

                for (x, y, w, h) in faces:
                    # Ortalama insan yüzü genişliği ~15cm varsayılır
                    dist = (15.0 * FOCAL_LENGTH) / w

                    results['detections'].append(Detection(
                        "Face", 1.0, (x, y, w, h), (255, 0, 255), distance_cm=dist
                    ))

                    if draw_results:
                        cv2.rectangle(output_frame, (x, y), (x+w, y+h), (255, 0, 255), 2)
                        cv2.putText(output_frame, f"Face {dist:.0f}cm", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)

                results['stats']['faces'] = len(faces)
            except Exception as e:
                logger.error(f"Face detection error: {e}")

        # 3. Motion Detection (Hareket Algılama + Çözünürlük Koruması)
        if 'motion' in modules:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                # DÜZELTME: Eğer prev_frame yoksa VEYA boyutları uyuşmuyorsa (çözünürlük değiştiyse) sıfırla
                if self.prev_frame is None or self.prev_frame.shape != gray.shape:
                    self.prev_frame = gray
                    # İlk karede hareket hesaplanmaz
                else:
                    delta = cv2.absdiff(self.prev_frame, gray)
                    thresh = cv2.threshold(delta, AIConfig.MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
                    thresh = cv2.dilate(thresh, None, iterations=2)
                    cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    motion_count = 0
                    for c in cnts:
                        if cv2.contourArea(c) < AIConfig.MOTION_MIN_AREA: continue
                        motion_count += 1
                        (x, y, w, h) = cv2.boundingRect(c)

                        if draw_results:
                            cv2.rectangle(output_frame, (x, y), (x+w, y+h), (0, 255, 255), 2)

                    results['stats']['motion_regions'] = motion_count
                    self.prev_frame = gray

            except Exception as e:
                logger.error(f"Motion calculation error: {e}")
                self.prev_frame = None # Hata durumunda sıfırla

        # 4. QR Code
        if 'qr' in modules and self.qr_decoder:
            try:
                objs = self.qr_decoder(frame)
                for obj in objs:
                    data = obj.data.decode("utf-8")
                    (x, y, w, h) = obj.rect

                    results['detections'].append(Detection(
                        "QR", 1.0, (x, y, w, h), (255, 165, 0), {'data': data}
                    ))

                    if draw_results:
                        cv2.rectangle(output_frame, (x, y), (x+w, y+h), (255, 165, 0), 2)
                        cv2.putText(output_frame, data, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 165, 0), 2)

                results['stats']['qr_codes'] = len(objs)
            except Exception as e:
                logger.error(f"QR error: {e}")

        # 5. Edge Detection
        if 'edges' in modules:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                edges = cv2.Canny(blurred, 50, 150)
                results['edge_frame'] = edges
                # İstenirse output_frame üzerine de işlenebilir
            except Exception as e:
                logger.error(f"Edge detection error: {e}")

        return output_frame, results

    def get_status(self):
        """Modül durumlarını döndürür."""
        return {'enabled_modules': self.enabled_modules.copy()}

# Global Singleton Instance
ai_vision_manager = AIVisionManager()
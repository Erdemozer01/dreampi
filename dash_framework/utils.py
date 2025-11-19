# utils.py - v3.32 (Django Import Fix + TFLite Removed)
import base64
import io
import logging
import math
import numpy as np
import hashlib
import threading
import time
import cv2
from typing import Optional, Dict, List, Tuple, Any, Callable
from copy import deepcopy
from collections import deque
from datetime import datetime, timedelta
from functools import wraps, lru_cache
from dataclasses import dataclass
import json

# DJANGO / STANDALONE IMPORT UYUMLULUĞU
try:
    # Django içinden çalışırken (noktalı import)
    from .config import CameraConfig, AppConfig, SensorConfig, AIConfig
except ImportError:
    # Standalone çalışırken
    from config import CameraConfig, AppConfig, SensorConfig, AIConfig

# Yeni importlar
from ultralytics import YOLO
from pyzbar.pyzbar import decode as pyzbar_decode

from pathlib import Path

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL kütüphanesi bulunamadı.")

logger = logging.getLogger(__name__)


# ============================================================================
# PERFORMANS İZLEME VE PROFİLİNG
# ============================================================================

class PerformanceMonitor:
    """Performans metriklerini izle"""

    def __init__(self):
        self.metrics = deque(maxlen=AppConfig.MAX_METRICS_HISTORY)
        self.lock = threading.Lock()

    def record(self, metric_name: str, value: float):
        with self.lock:
            self.metrics.append({
                'name': metric_name,
                'value': value,
                'timestamp': datetime.now()
            })


def profile_performance(func: Callable) -> Callable:
    """Fonksiyon performansını ölç"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not getattr(kwargs.get('self', None), 'performance_monitor', None):
            return func(*args, **kwargs)  # Monitor yoksa ölçme

        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = (end_time - start_time) * 1000
        return result

    return wrapper


class MultiTaskAIProcessor:
    """
    AIConfig'e dayalı çoklu AI/CV görevlerini yürüten işlemci.
    NOT: Bu sınıf artık otomatik olarak başlatılmaz. Manuel çağrılmalıdır.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.yolo_model = None
        self.face_cascade = None
        self.eye_cascade = None
        self.qr_decoder = pyzbar_decode
        self.prev_frame_gray = None

        if not AIConfig.ENABLE_AI:
            self.logger.warning("AI global olarak devre dışı.")
            return

        self.load_models()

    def load_models(self):
        # 1. YOLO Modelini Yükle
        if AIConfig.ENABLE_YOLO:
            try:
                self.yolo_model = YOLO(str(AIConfig.YOLO_MODEL_PATH))
                self.yolo_model.to('cpu')
                self.logger.info(f"✓ YOLO modeli yüklendi (Utils): {AIConfig.YOLO_MODEL}")
            except Exception as e:
                self.logger.error(f"YOLO modeli yüklenemedi: {e}")

        # 2. Yüz Tanıma (Haar Cascade) Yükle
        if AIConfig.ENABLE_FACE_DETECTION:
            try:
                self.face_cascade = cv2.CascadeClassifier(AIConfig.FACE_CASCADE_PATH)
                if AIConfig.DETECT_EYES:
                    self.eye_cascade = cv2.CascadeClassifier(AIConfig.EYE_CASCADE_PATH)
                self.logger.info("✓ Yüz tanıma modelleri yüklendi.")
            except Exception as e:
                self.logger.error(f"Haar cascade modelleri yüklenemedi: {e}")

    def process_frame(self, frame: np.ndarray, active_tasks: Dict[str, bool]) -> np.ndarray:
        if not AIConfig.ENABLE_AI:
            return frame

        processed_frame = frame.copy()

        if active_tasks.get('motion') and AIConfig.ENABLE_MOTION_DETECTION:
            processed_frame = self.run_motion_detection(frame, processed_frame)

        if active_tasks.get('yolo') and AIConfig.ENABLE_YOLO and self.yolo_model:
            processed_frame = self.run_yolo(frame, processed_frame)

        if active_tasks.get('face') and AIConfig.ENABLE_FACE_DETECTION and self.face_cascade:
            processed_frame = self.run_face_detection(frame, processed_frame)

        if active_tasks.get('qr') and AIConfig.ENABLE_QR_BARCODE:
            processed_frame = self.run_qr_barcode(frame, processed_frame)

        if active_tasks.get('edge') and AIConfig.ENABLE_EDGE_DETECTION:
            processed_frame = self.run_edge_detection(frame, processed_frame)

        return processed_frame

    def run_yolo(self, frame_orig: np.ndarray, frame_draw: np.ndarray) -> np.ndarray:
        try:
            results = self.yolo_model.predict(
                source=frame_orig,
                conf=AIConfig.YOLO_CONFIDENCE,
                iou=AIConfig.YOLO_IOU,
                verbose=False
            )
            if results and len(results) > 0:
                frame_draw = results[0].plot()
        except Exception as e:
            self.logger.warning(f"YOLO işleme hatası: {e}")
        return frame_draw

    def run_face_detection(self, frame_orig: np.ndarray, frame_draw: np.ndarray) -> np.ndarray:
        try:
            gray = cv2.cvtColor(frame_orig, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=AIConfig.FACE_SCALE_FACTOR,
                minNeighbors=AIConfig.FACE_MIN_NEIGHBORS,
                minSize=AIConfig.FACE_MIN_SIZE
            )
            color = AIConfig.get_color_for_label('face')
            for (x, y, w, h) in faces:
                cv2.rectangle(frame_draw, (x, y), (x + w, y + h), color, AIConfig.BBOX_THICKNESS)
        except Exception as e:
            self.logger.warning(f"Yüz tanıma hatası: {e}")
        return frame_draw

    def run_motion_detection(self, frame_orig: np.ndarray, frame_draw: np.ndarray) -> np.ndarray:
        try:
            gray = cv2.cvtColor(frame_orig, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, AIConfig.MOTION_GAUSSIAN_BLUR, 0)

            if self.prev_frame_gray is None:
                self.prev_frame_gray = gray
                return frame_draw

            # Çözünürlük değişimi kontrolü
            if self.prev_frame_gray.shape != gray.shape:
                self.prev_frame_gray = gray
                return frame_draw

            settings = AIConfig.get_motion_settings()
            frame_delta = cv2.absdiff(self.prev_frame_gray, gray)
            thresh = cv2.threshold(frame_delta, settings['threshold'], 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=AIConfig.MOTION_DILATE_ITERATIONS)

            contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            color = AIConfig.get_color_for_label('motion')

            for c in contours:
                if cv2.contourArea(c) < settings['min_area']: continue
                (x, y, w, h) = cv2.boundingRect(c)
                cv2.rectangle(frame_draw, (x, y), (x + w, y + h), color, AIConfig.BBOX_THICKNESS)

            self.prev_frame_gray = gray
        except Exception as e:
            self.logger.warning(f"Hareket tespiti hatası: {e}")
            self.prev_frame_gray = None
        return frame_draw

    def run_qr_barcode(self, frame_orig: np.ndarray, frame_draw: np.ndarray) -> np.ndarray:
        try:
            decoded_objects = self.qr_decoder(frame_orig)
            color = AIConfig.get_color_for_label('qr')
            for obj in decoded_objects:
                if obj.type not in AIConfig.QR_SUPPORTED_TYPES: continue
                points = obj.polygon
                if len(points) > 3:
                    pts = np.array(points, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(frame_draw, [pts], True, color, AIConfig.BBOX_THICKNESS)
                data_str = obj.data.decode('utf-8')
                cv2.putText(frame_draw, f"{obj.type}: {data_str}", (obj.rect.left, obj.rect.top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        except Exception as e:
            self.logger.warning(f"QR okuma hatası: {e}")
        return frame_draw

    def run_edge_detection(self, frame_orig: np.ndarray, frame_draw: np.ndarray) -> np.ndarray:
        try:
            gray = cv2.cvtColor(frame_orig, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, AIConfig.EDGE_GAUSSIAN_BLUR, 0)
            edges = cv2.Canny(blur, AIConfig.EDGE_LOW_THRESHOLD, AIConfig.EDGE_HIGH_THRESHOLD)
            color = AIConfig.get_color_for_label('edge')
            frame_draw[edges != 0] = color
        except Exception as e:
            self.logger.warning(f"Kenar tespiti hatası: {e}")
        return frame_draw


class CircuitBreaker:
    def __init__(self, failure_threshold, recovery_timeout):
        self.state = "closed"

    def call(self, func, *args, **kwargs): return func(*args, **kwargs)


class FrameBuffer:
    def __init__(self, size=3, max_age_seconds=300):
        self.buffer = deque(maxlen=size)
        self.lock = threading.Lock()

    def add_frame(self, frame):
        with self.lock: self.buffer.append(frame)

    def get_latest(self):
        with self.lock: return self.buffer[-1] if self.buffer else None

    def clear(self):
        with self.lock: self.buffer.clear()


class FisheyeCorrector:
    def load_calibration(self): pass

    def correct_distortion(self, frame, method='fast'): return frame


# --- Helper Fonksiyonlar ---

def image_to_base64(image: Optional[np.ndarray], quality: int = 85, format: str = 'JPEG') -> str:
    if image is None or not PIL_AVAILABLE: return ""
    try:
        pil_img = Image.fromarray(image)
        buffer = io.BytesIO()
        pil_img.save(buffer, format=format, quality=quality)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/{format.lower()};base64,{img_str}"
    except Exception as e:
        logger.error(f"Base64 hata: {e}")
        return ""


def split_data_uri(uri: str) -> Tuple[str, str]:
    if ',' in uri: return uri.split(',', 1)
    return "", ""


def base64_data_to_images(data: str):
    if not PIL_AVAILABLE: return None, None
    try:
        img_bytes = base64.b64decode(data)
        img_pil = Image.open(io.BytesIO(img_bytes))
        img_np = np.array(img_pil.convert('RGB'))
        img_gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        return img_pil, img_gray
    except Exception:
        return None, None


def cleanup_old_store_data(store, max_age): return store


def format_distance(d):
    if d is None: return "N/A"
    return f"{d:.1f} cm"


def safe_update_store(store, updates):
    if store is None: store = {}
    new_store = store.copy()
    new_store.update(updates)
    return new_store


# DÜZELTME: Bu satırı kaldırıyoruz veya None yapıyoruz ki otomatik yüklenmesin.
ai_processor = None
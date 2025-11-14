# ai_vision.py - v1.0 (AI-Powered Computer Vision)
# Nesne tespiti, Yüz tanıma, Hareket tespiti, QR/Barkod okuma

import logging
import time
import cv2
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from dataclasses import dataclass
from collections import deque
import threading

logger = logging.getLogger(__name__)


# ============================================================================
# DETECTION RESULT DATA CLASS
# ============================================================================

@dataclass
class Detection:
    """Tespit edilen nesne/yüz/hareket bilgisi"""
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    color: Tuple[int, int, int] = (0, 255, 0)
    metadata: Dict[str, Any] = None


# ============================================================================
# YOLO OBJECT DETECTOR (YOLOv8)
# ============================================================================

class YOLODetector:
    """YOLOv8 ile nesne tespiti"""

    def __init__(self, model_path: str = None, confidence: float = 0.5, iou: float = 0.4):
        self.model = None
        self.confidence = confidence
        self.iou = iou
        self.model_loaded = False

        try:
            from ultralytics import YOLO

            if model_path is None or not Path(model_path).exists():
                logger.info("YOLOv8 varsayılan model indiriliyor (yolov8n.pt - nano)...")
                model_path = 'yolov8n.pt'  # Otomatik indirir

            self.model = YOLO(model_path)
            self.model_loaded = True
            logger.info(f"✓ YOLOv8 yüklendi: {model_path}")

        except ImportError:
            logger.warning("⚠️ ultralytics kütüphanesi bulunamadı. 'pip install ultralytics' çalıştırın.")
        except Exception as e:
            logger.error(f"YOLOv8 yükleme hatası: {e}")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Frame'de nesne tespiti yap"""
        if not self.model_loaded or frame is None:
            return []

        try:
            results = self.model.predict(
                frame,
                conf=self.confidence,
                iou=self.iou,
                verbose=False,
                device='cpu'  # RPi için CPU
            )

            detections = []

            for result in results:
                boxes = result.boxes

                for box in boxes:
                    # Koordinatlar
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    w = int(x2 - x1)
                    h = int(y2 - y1)

                    # Sınıf ve güven
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    label = result.names[cls_id]

                    detections.append(Detection(
                        label=label,
                        confidence=conf,
                        bbox=(int(x1), int(y1), w, h),
                        color=self._get_color_for_class(cls_id)
                    ))

            return detections

        except Exception as e:
            logger.error(f"YOLO detection hatası: {e}")
            return []

    def _get_color_for_class(self, cls_id: int) -> Tuple[int, int, int]:
        """Sınıfa göre renk döndür"""
        colors = [
            (0, 255, 0),    # person - yeşil
            (255, 0, 0),    # bicycle - mavi
            (0, 0, 255),    # car - kırmızı
            (255, 255, 0),  # motorcycle - cyan
            (255, 0, 255),  # airplane - magenta
        ]
        return colors[cls_id % len(colors)]


# ============================================================================
# FACE DETECTOR (OpenCV Haar Cascades)
# ============================================================================

class FaceDetector:
    """OpenCV Haar Cascades ile yüz tespiti"""

    def __init__(self):
        self.face_cascade = None
        self.eye_cascade = None
        self.model_loaded = False

        try:
            # Haar Cascade XML dosyaları
            cascade_path = cv2.data.haarcascades

            face_xml = Path(cascade_path) / 'haarcascade_frontalface_default.xml'
            eye_xml = Path(cascade_path) / 'haarcascade_eye.xml'

            if face_xml.exists():
                self.face_cascade = cv2.CascadeClassifier(str(face_xml))
                logger.info("✓ Yüz tespit modeli yüklendi")
                self.model_loaded = True

            if eye_xml.exists():
                self.eye_cascade = cv2.CascadeClassifier(str(eye_xml))
                logger.info("✓ Göz tespit modeli yüklendi")

        except Exception as e:
            logger.error(f"Face detector yükleme hatası: {e}")

    def detect(self, frame: np.ndarray, detect_eyes: bool = False) -> List[Detection]:
        """Yüz tespiti yap"""
        if not self.model_loaded or frame is None:
            return []

        try:
            # Griye çevir
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Yüzleri tespit et
            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )

            detections = []

            for (x, y, w, h) in faces:
                detection = Detection(
                    label='face',
                    confidence=1.0,  # Haar cascades confidence vermez
                    bbox=(x, y, w, h),
                    color=(255, 0, 255),  # Magenta
                    metadata={'eyes': []}
                )

                # Gözleri tespit et (opsiyonel)
                if detect_eyes and self.eye_cascade:
                    roi_gray = gray[y:y+h, x:x+w]
                    eyes = self.eye_cascade.detectMultiScale(roi_gray)

                    for (ex, ey, ew, eh) in eyes:
                        detection.metadata['eyes'].append({
                            'bbox': (x + ex, y + ey, ew, eh)
                        })

                detections.append(detection)

            return detections

        except Exception as e:
            logger.error(f"Face detection hatası: {e}")
            return []


# ============================================================================
# MOTION DETECTOR (Frame Differencing)
# ============================================================================

class MotionDetector:
    """Hareket tespiti (frame diff + contour detection)"""

    def __init__(self, min_area: int = 500, threshold: int = 25):
        self.min_area = min_area
        self.threshold = threshold
        self.prev_frame = None
        self.motion_history = deque(maxlen=30)  # Son 30 frame

    def detect(self, frame: np.ndarray) -> Tuple[List[Detection], float]:
        """
        Hareket tespiti yap

        Returns:
            (detections, motion_percentage)
        """
        if frame is None:
            return [], 0.0

        try:
            # Griye çevir + blur
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            # İlk frame ise kaydet
            if self.prev_frame is None:
                self.prev_frame = gray
                return [], 0.0

            # Frame farkı hesapla
            frame_delta = cv2.absdiff(self.prev_frame, gray)
            thresh = cv2.threshold(frame_delta, self.threshold, 255, cv2.THRESH_BINARY)[1]

            # Morfolojik işlemler (gürültü temizleme)
            thresh = cv2.dilate(thresh, None, iterations=2)

            # Konturları bul
            contours, _ = cv2.findContours(
                thresh.copy(),
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            detections = []
            total_motion_area = 0

            for contour in contours:
                area = cv2.contourArea(contour)

                if area < self.min_area:
                    continue

                total_motion_area += area

                # Bounding box
                x, y, w, h = cv2.boundingRect(contour)

                detections.append(Detection(
                    label='motion',
                    confidence=min(area / 10000, 1.0),  # Alan bazlı confidence
                    bbox=(x, y, w, h),
                    color=(0, 255, 255),  # Sarı
                    metadata={'area': area}
                ))

            # Hareket yüzdesi
            frame_area = frame.shape[0] * frame.shape[1]
            motion_percentage = (total_motion_area / frame_area) * 100

            self.motion_history.append(motion_percentage)

            # Frame'i güncelle
            self.prev_frame = gray

            return detections, motion_percentage

        except Exception as e:
            logger.error(f"Motion detection hatası: {e}")
            return [], 0.0

    def reset(self):
        """Hareket geçmişini sıfırla"""
        self.prev_frame = None
        self.motion_history.clear()

    def get_average_motion(self) -> float:
        """Ortalama hareket yüzdesi"""
        if not self.motion_history:
            return 0.0
        return sum(self.motion_history) / len(self.motion_history)


# ============================================================================
# QR/BARCODE READER
# ============================================================================

class QRBarcodeReader:
    """QR ve Barkod okuma (pyzbar)"""

    def __init__(self):
        self.reader_loaded = False

        try:
            import pyzbar.pyzbar as pyzbar
            self.pyzbar = pyzbar
            self.reader_loaded = True
            logger.info("✓ QR/Barkod okuyucu yüklendi")
        except ImportError:
            logger.warning("⚠️ pyzbar kütüphanesi bulunamadı. 'pip install pyzbar' çalıştırın.")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """QR/Barkod tespiti yap"""
        if not self.reader_loaded or frame is None:
            return []

        try:
            # Griye çevir
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # QR/Barkodları tespit et
            decoded_objects = self.pyzbar.decode(gray)

            detections = []

            for obj in decoded_objects:
                # Koordinatlar
                x, y, w, h = obj.rect

                # Data
                data = obj.data.decode('utf-8')
                obj_type = obj.type

                detections.append(Detection(
                    label=f'{obj_type}',
                    confidence=1.0,
                    bbox=(x, y, w, h),
                    color=(0, 165, 255),  # Turuncu
                    metadata={'data': data, 'type': obj_type}
                ))

            return detections

        except Exception as e:
            logger.error(f"QR/Barcode detection hatası: {e}")
            return []


# ============================================================================
# EDGE DETECTOR (Canny)
# ============================================================================

class EdgeDetector:
    """Kenar tespiti ve kontur analizi"""

    def __init__(self, low_threshold: int = 50, high_threshold: int = 150):
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    def detect(self, frame: np.ndarray, min_area: int = 1000) -> Tuple[np.ndarray, List[Detection]]:
        """
        Kenar tespiti yap

        Returns:
            (edge_frame, contour_detections)
        """
        if frame is None:
            return None, []

        try:
            # Griye çevir
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Blur
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Canny edge detection
            edges = cv2.Canny(blurred, self.low_threshold, self.high_threshold)

            # Konturları bul
            contours, _ = cv2.findContours(
                edges.copy(),
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            detections = []

            for contour in contours:
                area = cv2.contourArea(contour)

                if area < min_area:
                    continue

                # Bounding box
                x, y, w, h = cv2.boundingRect(contour)

                # Perimeter ve circularity
                perimeter = cv2.arcLength(contour, True)
                circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0

                detections.append(Detection(
                    label='contour',
                    confidence=min(area / 50000, 1.0),
                    bbox=(x, y, w, h),
                    color=(255, 165, 0),  # Turuncu
                    metadata={
                        'area': area,
                        'perimeter': perimeter,
                        'circularity': circularity
                    }
                ))

            # Edge frame'i renkli yap (görselleştirme için)
            edge_colored = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

            return edge_colored, detections

        except Exception as e:
            logger.error(f"Edge detection hatası: {e}")
            return frame, []


# ============================================================================
# UNIFIED AI VISION MANAGER
# ============================================================================

class AIVisionManager:
    """Tüm AI/CV modüllerini birleştiren yönetici"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Detectorler
        self.yolo = None
        self.face_detector = None
        self.motion_detector = None
        self.qr_reader = None
        self.edge_detector = None

        # Durum
        self.enabled_modules = {
            'yolo': False,
            'face': False,
            'motion': False,
            'qr': False,
            'edges': False
        }

        # Thread safety
        self.lock = threading.Lock()

        logger.info("AI Vision Manager başlatıldı")

    def initialize_module(self, module_name: str, **kwargs) -> bool:
        """Modül başlat"""
        with self.lock:
            try:
                if module_name == 'yolo':
                    self.yolo = YOLODetector(**kwargs)
                    self.enabled_modules['yolo'] = self.yolo.model_loaded
                    return self.enabled_modules['yolo']

                elif module_name == 'face':
                    self.face_detector = FaceDetector()
                    self.enabled_modules['face'] = self.face_detector.model_loaded
                    return self.enabled_modules['face']

                elif module_name == 'motion':
                    self.motion_detector = MotionDetector(**kwargs)
                    self.enabled_modules['motion'] = True
                    return True

                elif module_name == 'qr':
                    self.qr_reader = QRBarcodeReader()
                    self.enabled_modules['qr'] = self.qr_reader.reader_loaded
                    return self.enabled_modules['qr']

                elif module_name == 'edges':
                    self.edge_detector = EdgeDetector(**kwargs)
                    self.enabled_modules['edges'] = True
                    return True

                else:
                    logger.warning(f"Bilinmeyen modül: {module_name}")
                    return False

            except Exception as e:
                logger.error(f"Modül başlatma hatası ({module_name}): {e}")
                return False

    def process_frame(self,
                      frame: np.ndarray,
                      modules: List[str] = None,
                      draw_results: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Frame'i işle (tüm aktif modüller)

        Args:
            frame: İşlenecek frame
            modules: Kullanılacak modüller (None ise tümü)
            draw_results: Sonuçları frame üzerine çiz

        Returns:
            (processed_frame, results_dict)
        """
        if frame is None:
            return None, {}

        if modules is None:
            modules = [k for k, v in self.enabled_modules.items() if v]

        results = {
            'detections': [],
            'motion_percentage': 0.0,
            'edge_frame': None,
            'stats': {}
        }

        output_frame = frame.copy() if draw_results else frame

        # YOLO
        if 'yolo' in modules and self.yolo:
            yolo_detections = self.yolo.detect(frame)
            results['detections'].extend(yolo_detections)
            results['stats']['yolo_objects'] = len(yolo_detections)

        # Face Detection
        if 'face' in modules and self.face_detector:
            face_detections = self.face_detector.detect(frame, detect_eyes=True)
            results['detections'].extend(face_detections)
            results['stats']['faces'] = len(face_detections)

        # Motion Detection
        if 'motion' in modules and self.motion_detector:
            motion_detections, motion_pct = self.motion_detector.detect(frame)
            results['detections'].extend(motion_detections)
            results['motion_percentage'] = motion_pct
            results['stats']['motion_regions'] = len(motion_detections)

        # QR/Barcode
        if 'qr' in modules and self.qr_reader:
            qr_detections = self.qr_reader.detect(frame)
            results['detections'].extend(qr_detections)
            results['stats']['qr_codes'] = len(qr_detections)

        # Edge Detection
        if 'edges' in modules and self.edge_detector:
            edge_frame, edge_detections = self.edge_detector.detect(frame)
            results['edge_frame'] = edge_frame
            results['detections'].extend(edge_detections)
            results['stats']['contours'] = len(edge_detections)

        # Sonuçları çiz
        if draw_results:
            output_frame = self._draw_detections(output_frame, results['detections'])

        return output_frame, results

    def _draw_detections(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Tespitleri frame üzerine çiz"""
        for det in detections:
            x, y, w, h = det.bbox

            # Bounding box
            cv2.rectangle(frame, (x, y), (x + w, y + h), det.color, 2)

            # Label
            label_text = f"{det.label}: {det.confidence:.2f}"

            # Arka plan (okunabilirlik için)
            (text_w, text_h), _ = cv2.getTextSize(
                label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            cv2.rectangle(
                frame,
                (x, y - text_h - 8),
                (x + text_w + 8, y),
                det.color,
                -1
            )

            # Text
            cv2.putText(
                frame,
                label_text,
                (x + 4, y - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1
            )

            # Metadata (QR data, vb.)
            if det.metadata and 'data' in det.metadata:
                data_text = det.metadata['data'][:30]  # İlk 30 karakter
                cv2.putText(
                    frame,
                    data_text,
                    (x, y + h + 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (0, 255, 255),
                    1
                )

        return frame

    def get_status(self) -> Dict[str, Any]:
        """Modül durumlarını al"""
        return {
            'enabled_modules': self.enabled_modules.copy(),
            'motion_avg': self.motion_detector.get_average_motion() if self.motion_detector else 0.0
        }


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

ai_vision_manager = AIVisionManager()


# Export
__all__ = [
    'AIVisionManager',
    'ai_vision_manager',
    'Detection',
    'YOLODetector',
    'FaceDetector',
    'MotionDetector',
    'QRBarcodeReader',
    'EdgeDetector'
]


if __name__ == "__main__":
    # Test modu
    logging.basicConfig(level=logging.INFO)

    print("🧪 AI Vision Manager Test")
    print("=" * 60)

    manager = AIVisionManager()

    # Modülleri başlat
    print("\n📦 Modüller başlatılıyor...")
    manager.initialize_module('yolo')
    manager.initialize_module('face')
    manager.initialize_module('motion')
    manager.initialize_module('qr')
    manager.initialize_module('edges')

    status = manager.get_status()
    print(f"\n✓ Durum: {status}")

    # Test frame
    test_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    print("\n🔍 Test frame işleniyor...")
    processed, results = manager.process_frame(test_frame, draw_results=True)

    print(f"\n📊 Sonuçlar:")
    print(f"  Tespit sayısı: {len(results['detections'])}")
    print(f"  İstatistikler: {results['stats']}")
    print(f"  Hareket: {results['motion_percentage']:.2f}%")

    print("\n✓ Test tamamlandı!")
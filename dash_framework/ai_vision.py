# ai_vision.py - v1.6 (Django Import Fix)

import logging
import cv2
import numpy as np
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import threading

# DJANGO / STANDALONE IMPORT UYUMLULUĞU
try:
    from .config import AIConfig
except ImportError:
    from config import AIConfig

logger = logging.getLogger(__name__)

@dataclass
class Detection:
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]
    color: Tuple[int, int, int] = (0, 255, 0)
    metadata: Dict[str, Any] = None
    distance_cm: float = None

KNOWN_WIDTHS = {
    'person': 45.0, 'car': 180.0, 'cell phone': 7.5, 'bottle': 7.0,
    'cup': 8.0, 'monitor': 50.0, 'laptop': 35.0, 'mouse': 6.0,
    'keyboard': 45.0, 'book': 15.0, 'chair': 50.0, 'cat': 15.0, 'dog': 20.0
}
FOCAL_LENGTH = 650.0

class AIVisionManager:
    def __init__(self):
        self.yolo_model = None
        self.face_cascade = None
        self.qr_decoder = None
        self.enabled_modules = {'yolo': False, 'face': False, 'motion': False, 'qr': False, 'edges': False}
        self.lock = threading.Lock()
        self.prev_frame = None

    def initialize_module(self, module_name: str, **kwargs) -> bool:
        with self.lock:
            try:
                if module_name == 'yolo':
                    if not AIConfig.ENABLE_YOLO: return False
                    if self.yolo_model is None:
                        from ultralytics import YOLO
                        self.yolo_model = YOLO(str(AIConfig.YOLO_MODEL_PATH))
                        logger.info(f"YOLO model loaded: {AIConfig.YOLO_MODEL}")
                    self.enabled_modules['yolo'] = True
                    return True
                # ... (Diğer modüller aynı mantıkla devam eder)
                elif module_name == 'face':
                    if not AIConfig.ENABLE_FACE_DETECTION: return False
                    if self.face_cascade is None:
                        self.face_cascade = cv2.CascadeClassifier(AIConfig.FACE_CASCADE_PATH)
                    self.enabled_modules['face'] = True
                    return True
                elif module_name == 'motion':
                    self.enabled_modules['motion'] = True
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
        real_width = KNOWN_WIDTHS.get(label)
        if real_width and pixel_width > 0:
            distance = (real_width * FOCAL_LENGTH) / pixel_width
            return round(distance, 1)
        return None

    def process_frame(self, frame: np.ndarray, modules: List[str] = None, draw_results: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
        if frame is None: return None, {}
        if modules is None: modules = [k for k, v in self.enabled_modules.items() if v]

        results = {'detections': [], 'motion_percentage': 0.0, 'edge_frame': None, 'stats': {}}
        output_frame = frame.copy() if draw_results else frame

        # 1. YOLO
        if 'yolo' in modules and self.yolo_model:
            try:
                yolo_res = self.yolo_model.predict(frame, conf=AIConfig.YOLO_CONFIDENCE, verbose=False)
                for r in yolo_res:
                    boxes = r.boxes
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        w = x2 - x1
                        h = y2 - y1
                        conf = float(box.conf[0])
                        cls = int(box.cls[0])
                        label = self.yolo_model.names[cls]
                        dist = self.calculate_distance(w, label)
                        results['detections'].append(Detection(label, conf, (x1, y1, w, h), (0, 255, 0), distance_cm=dist))
                        if draw_results:
                            cv2.rectangle(output_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            label_text = f"{label} {conf:.2f}"
                            if dist: label_text += f" | {dist}cm"
                            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                            cv2.rectangle(output_frame, (x1, y1 - 20), (x1 + tw, y1), (0, 255, 0), -1)
                            cv2.putText(output_frame, label_text, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                results['stats']['yolo_objects'] = len(results['detections'])
            except Exception as e: logger.error(f"YOLO error: {e}")

        # 2. Face
        if 'face' in modules and self.face_cascade:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.1, 5)
                for (x, y, w, h) in faces:
                    dist = (15.0 * FOCAL_LENGTH) / w
                    results['detections'].append(Detection("Face", 1.0, (x, y, w, h), (255, 0, 255), distance_cm=dist))
                    if draw_results:
                        cv2.rectangle(output_frame, (x, y), (x+w, y+h), (255, 0, 255), 2)
                        cv2.putText(output_frame, f"Face {dist:.0f}cm", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
                results['stats']['faces'] = len(faces)
            except Exception as e: logger.error(f"Face error: {e}")

        # 3. Motion
        if 'motion' in modules:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                if self.prev_frame is None or self.prev_frame.shape != gray.shape:
                    self.prev_frame = gray
                else:
                    delta = cv2.absdiff(self.prev_frame, gray)
                    thresh = cv2.threshold(delta, AIConfig.MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
                    thresh = cv2.dilate(thresh, None, iterations=2)
                    cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for c in cnts:
                        if cv2.contourArea(c) < AIConfig.MOTION_MIN_AREA: continue
                        (x, y, w, h) = cv2.boundingRect(c)
                        if draw_results: cv2.rectangle(output_frame, (x, y), (x+w, y+h), (0, 255, 255), 2)
                    self.prev_frame = gray
            except Exception as e:
                logger.error(f"Motion error: {e}")
                self.prev_frame = None

        # 4. QR
        if 'qr' in modules and self.qr_decoder:
            try:
                objs = self.qr_decoder(frame)
                for obj in objs:
                    data = obj.data.decode("utf-8")
                    (x, y, w, h) = obj.rect
                    results['detections'].append(Detection("QR", 1.0, (x, y, w, h), (255, 165, 0), {'data': data}))
                    if draw_results:
                        cv2.rectangle(output_frame, (x, y), (x+w, y+h), (255, 165, 0), 2)
                        cv2.putText(output_frame, data, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 165, 0), 2)
                results['stats']['qr_codes'] = len(objs)
            except Exception as e: logger.error(f"QR error: {e}")

        return output_frame, results

    def get_status(self):
        return {'enabled_modules': self.enabled_modules.copy()}

ai_vision_manager = AIVisionManager()
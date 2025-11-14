# config.py - DÜZELTME v3.16 (Genişletilmiş Kamera Kontrolleri)
# Raspberry Pi 5 + OV5647 130° Kamera
# YENİ: Manuel Pozlama, ISO, Brightness, Contrast, Saturation, Sharpness,
#       AWB Modları, Colour Effects, Flicker Modes

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import json

# libcamera kontrolleri
try:
    from libcamera import controls
    LIBCAMERA_CONTROLS_AVAILABLE = True
except ImportError:
    LIBCAMERA_CONTROLS_AVAILABLE = False
    logging.warning("libcamera.controls bulunamadı. Kamera ayarları sınırlı olabilir.")



class AIConfig:
    """AI entegrasyonu ayarları - Nesne Tespiti, Yüz Tanıma, vb."""

    # ===== GENEL AI AYARLARI =====
    ENABLE_AI = True  # AI/CV özelliklerini etkinleştir

    # ===== YOLO (NESNE TESPİTİ) =====
    ENABLE_YOLO = True
    YOLO_MODEL = 'yolov8n.pt'  # Modeller: yolov8n (hızlı), yolov8s (dengeli), yolov8m (kaliteli)
    YOLO_CONFIDENCE = 0.5      # Minimum güven skoru (0.0-1.0)
    YOLO_IOU = 0.4             # Intersection over Union eşiği
    YOLO_MODEL_DIR = Path("../yolov8n.pt")

    # YOLO Sınıfları (COCO dataset - 80 sınıf)
    YOLO_CLASSES = [
        'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat',
        'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat',
        'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'backpack',
        'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball',
        'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket',
        'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
        'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair',
        'couch', 'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse',
        'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator',
        'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush'
    ]

    # ===== YÜZ TANIMA =====
    ENABLE_FACE_DETECTION = True
    DETECT_EYES = True             # Gözleri de tespit et
    FACE_MIN_SIZE = (30, 30)       # Minimum yüz boyutu (piksel)
    FACE_SCALE_FACTOR = 1.1        # Haar Cascade scale factor
    FACE_MIN_NEIGHBORS = 5         # Minimum komşu sayısı

    # ===== HAREKET TESPİTİ =====
    ENABLE_MOTION_DETECTION = True
    MOTION_MIN_AREA = 500          # Minimum hareket alanı (piksel²)
    MOTION_THRESHOLD = 25          # Frame difference eşiği (0-255)
    MOTION_SENSITIVITY = 'medium'  # Seçenekler: 'low', 'medium', 'high'
    MOTION_GAUSSIAN_BLUR = (21, 21)# Blur kernel boyutu
    MOTION_DILATE_ITERATIONS = 2   # Morfolojik işlem

    # Hareket Hassasiyet Profilleri
    MOTION_PROFILES = {
        'low': {'threshold': 40, 'min_area': 1000},
        'medium': {'threshold': 25, 'min_area': 500},
        'high': {'threshold': 15, 'min_area': 200}
    }

    # ===== QR/BARKOD OKUMA =====
    ENABLE_QR_BARCODE = True
    QR_AUTO_DECODE = True          # Otomatik decode et
    QR_SUPPORTED_TYPES = [         # Desteklenen tipler
        'QRCODE', 'EAN13', 'EAN8', 'CODE128', 'CODE39', 'CODE93',
        'CODABAR', 'UPC_A', 'UPC_E', 'PDF417', 'DATAMATRIX', 'AZTEC'
    ]

    # ===== KENAR TESPİTİ =====
    ENABLE_EDGE_DETECTION = True
    EDGE_LOW_THRESHOLD = 50        # Canny düşük eşik
    EDGE_HIGH_THRESHOLD = 150      # Canny yüksek eşik
    EDGE_MIN_CONTOUR_AREA = 1000   # Minimum kontur alanı
    EDGE_GAUSSIAN_BLUR = (5, 5)    # Blur kernel

    # ===== PERFORMANS AYARLARI =====
    AI_PROCESS_INTERVAL_MS = 100   # AI işleme aralığı (milisaniye)
    AI_SKIP_FRAMES = 2             # Her N frame'de bir işle (1=her frame)
    AI_USE_THREADING = True        # Thread kullan
    AI_MAX_QUEUE_SIZE = 3          # Maksimum frame kuyruğu
    AI_TIMEOUT = 5.0               # İşleme timeout (saniye)

    # ===== GÖRSELLEŞTİRME =====
    DRAW_BBOXES = True             # Bounding box çiz
    DRAW_LABELS = True             # Label yazdır
    BBOX_THICKNESS = 2             # Çizgi kalınlığı
    LABEL_FONT_SCALE = 0.5         # Font boyutu
    LABEL_FONT_THICKNESS = 1       # Font kalınlığı

    # Renk Paleti (BGR formatında)
    COLOR_PALETTE = {
        'yolo': (0, 255, 0),       # Yeşil
        'face': (255, 0, 255),     # Magenta
        'motion': (0, 255, 255),   # Sarı
        'qr': (255, 165, 0),       # Turuncu
        'edge': (255, 165, 0),     # Turuncu
        'person': (0, 255, 0),     # Kişi için özel yeşil
        'car': (0, 0, 255),        # Araba için kırmızı
    }

    # ===== UYARI SİSTEMİ (OPSİYONEL) =====
    ENABLE_ALERTS = False
    ALERT_ON_PERSON_DETECTED = False  # İnsan tespit edilince uyar
    ALERT_ON_MOTION_THRESHOLD = 30.0  # Hareket % eşiği
    ALERT_SOUND = True                # Ses uyarısı
    ALERT_EMAIL = False               # Email uyarısı
    ALERT_WEBHOOK = False             # Webhook (Discord, Slack, vb.)

    # ===== KAYIT VE LOG =====
    SAVE_DETECTIONS = False           # Tespitleri kaydet
    DETECTION_SAVE_DIR = Path("media/detections")
    SAVE_DETECTION_IMAGES = False     # Tespit edilen frame'leri kaydet
    SAVE_DETECTION_METADATA = True    # JSON metadata kaydet
    MAX_SAVED_DETECTIONS = 1000       # Maksimum kayıt sayısı

    # Log detayları
    LOG_DETECTION_STATS = True        # Tespit istatistiklerini logla
    LOG_PERFORMANCE_METRICS = True    # Performans metriklerini logla

    # ===== GELİŞMİŞ AYARLAR =====
    # TensorFlow Lite (YOLO alternatifi)
    USE_TFLITE = False                # YOLOv8 yerine TFLite kullan
    TFLITE_MODEL_PATH = Path("models/detect.tflite")
    TFLITE_LABELS_PATH = Path("models/labelmap.txt")

    # Edge TPU (Google Coral)
    USE_EDGE_TPU = False              # Edge TPU akseleratörü
    EDGE_TPU_DEVICE = '/dev/bus/usb/001/002'

    # GPU/NPU
    USE_GPU = False                   # CUDA/OpenCL (RPi'de yok)
    USE_NPU = False                   # Neural Processing Unit

    # ===== ESKİ AYARLAR (Geriye Dönük Uyumluluk) =====
    AI_MODEL = 'yolo'                 # Varsayılan model tipi
    MODEL_PATH = YOLO_MODEL_DIR / YOLO_MODEL
    CONFIDENCE_THRESHOLD = YOLO_CONFIDENCE
    NMS_THRESHOLD = YOLO_IOU
    MAX_DETECTIONS = 50               # Maksimum tespit sayısı

    @classmethod
    def create_directories(cls):
        """AI için gerekli klasörleri oluştur"""
        try:
            cls.YOLO_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            cls.DETECTION_SAVE_DIR.mkdir(parents=True, exist_ok=True)
            logging.info("✓ AI dizinleri oluşturuldu")
        except Exception as e:
            logging.error(f"AI dizin oluşturma hatası: {e}")

    @classmethod
    def get_motion_settings(cls, profile: str = None) -> Dict[str, int]:
        """Hareket hassasiyet profilini al"""
        if profile is None:
            profile = cls.MOTION_SENSITIVITY
        return cls.MOTION_PROFILES.get(profile, cls.MOTION_PROFILES['medium'])

    @classmethod
    def validate_confidence(cls, confidence: float) -> float:
        """Güven skorunu validasyon yap"""
        return max(0.1, min(0.95, confidence))

    @classmethod
    def get_color_for_label(cls, label: str) -> Tuple[int, int, int]:
        """Label'a göre renk döndür"""
        return cls.COLOR_PALETTE.get(label.lower(), cls.COLOR_PALETTE['yolo'])



# --- KAMERA AYARLARI (GENİŞLETİLMİŞ v3.16) ---
class CameraConfig:
    """OV5647 130° kamera için tam kontrol ayarları"""

    # Kamera Model Bilgileri
    CAMERA_MODEL = "OV5647"
    FOV_HORIZONTAL = 130  # derece
    FOV_VERTICAL = 100    # derece
    SENSOR_WIDTH = 3.68   # mm
    SENSOR_HEIGHT = 2.76  # mm

    # === GENİŞLETİLMİŞ ÇÖZÜNÜRLÜK SEÇENEKLERİ (v3.17) ===

    # Standart Çözünürlükler
    QVGA_RESOLUTION = (320, 240)          # QVGA - 0.08 MP
    VGA_RESOLUTION = (640, 480)           # VGA - 0.3 MP
    SVGA_RESOLUTION = (800, 600)          # SVGA - 0.5 MP
    XGA_RESOLUTION = (1024, 768)          # XGA - 0.8 MP
    HD_READY_RESOLUTION = (1280, 720)     # HD Ready - 0.9 MP
    SXGA_RESOLUTION = (1280, 960)         # SXGA - 1.2 MP

    # OV5647 Native
    NATIVE_RESOLUTION = (1296, 972)       # Native - 1.3 MP (ÖNERİLEN)

    # HD Çözünürlükler
    HD_PLUS_RESOLUTION = (1600, 900)      # HD+ - 1.4 MP
    UXGA_RESOLUTION = (1600, 1200)        # UXGA - 1.9 MP
    FULL_HD_RESOLUTION = (1920, 1080)     # Full HD - 2.1 MP
    FULL_HD_PLUS_RESOLUTION = (1920, 1200) # Full HD+ - 2.3 MP

    # 2K ve Üzeri
    TWO_K_RESOLUTION = (2048, 1536)       # 2K - 3.1 MP
    QHD_RESOLUTION = (2560, 1440)         # QHD/2K - 3.7 MP
    WQHD_RESOLUTION = (2560, 1600)        # WQHD - 4.1 MP
    MAX_RESOLUTION = (2592, 1944)         # Max - 5.0 MP

    # Ultra-wide Aspect Ratios
    ULTRAWIDE_1_RESOLUTION = (2560, 1080) # 21:9 Ultrawide
    ULTRAWIDE_2_RESOLUTION = (3440, 1440) # 21:9 Ultrawide QHD (sınırlı)

    # Kare Formatlar (1:1)
    SQUARE_SMALL_RESOLUTION = (640, 640)   # Instagram square
    SQUARE_MEDIUM_RESOLUTION = (1080, 1080) # Full square
    SQUARE_LARGE_RESOLUTION = (1944, 1944)  # Max square

    # Dikey Video Formatları (9:16)
    PORTRAIT_HD_RESOLUTION = (720, 1280)   # Portrait HD
    PORTRAIT_FHD_RESOLUTION = (1080, 1920) # Portrait Full HD

    # Özel Aspect Ratios
    CINEMATIC_2K_RESOLUTION = (2048, 858)  # 2.39:1 Cinematic
    CINEMATIC_4K_RESOLUTION = (3840, 1607) # 2.39:1 Cinematic (sınırlı)

    # Varsayılan
    DEFAULT_RESOLUTION = HD_READY_RESOLUTION  # 1280x720 (hız/kalite dengesi)
    PERFORMANCE_RESOLUTION = VGA_RESOLUTION   # 640x480 (max FPS)
    BALANCED_RESOLUTION = NATIVE_RESOLUTION   # 1296x972 (optimal)
    QUALITY_RESOLUTION = FULL_HD_RESOLUTION   # 1920x1080 (kalite)

    # === UI İÇİN ÇÖZÜNÜRLÜK LİSTESİ (Gruplandırılmış) ===
    RESOLUTIONS = [
        # === PERFORMANS (90+ FPS) ===
        {'label': '📱 320x240 (QVGA) - Max FPS', 'value': '320x240', 'group': 'Performans'},
        {'label': '📱 640x480 (VGA) - 90 FPS', 'value': '640x480', 'group': 'Performans'},
        {'label': '📱 640x640 (Square) - 90 FPS', 'value': '640x640', 'group': 'Performans'},

        # === STANDART (60-90 FPS) ===
        {'label': '📺 800x600 (SVGA) - 75 FPS', 'value': '800x600', 'group': 'Standart'},
        {'label': '📺 1024x768 (XGA) - 60 FPS', 'value': '1024x768', 'group': 'Standart'},

        # === HD (30-60 FPS) ===
        {'label': '🎬 1280x720 (HD Ready) - 60 FPS ⭐', 'value': '1280x720', 'group': 'HD'},
        {'label': '🎬 1280x960 (SXGA) - 50 FPS', 'value': '1280x960', 'group': 'HD'},
        {'label': '🎬 1296x972 (Native) - 40 FPS ⭐⭐', 'value': '1296x972', 'group': 'HD'},
        {'label': '🎬 1600x900 (HD+) - 35 FPS', 'value': '1600x900', 'group': 'HD'},
        {'label': '🎬 1600x1200 (UXGA) - 30 FPS', 'value': '1600x1200', 'group': 'HD'},

        # === FULL HD (20-30 FPS) ===
        {'label': '🎥 1920x1080 (Full HD) - 30 FPS ⭐⭐⭐', 'value': '1920x1080', 'group': 'Full HD'},
        {'label': '🎥 1920x1200 (Full HD+) - 25 FPS', 'value': '1920x1200', 'group': 'Full HD'},
        {'label': '🎥 1080x1080 (Square HD) - 30 FPS', 'value': '1080x1080', 'group': 'Full HD'},

        # === 2K/QHD (15-25 FPS) ===
        {'label': '📸 2048x1536 (2K) - 20 FPS', 'value': '2048x1536', 'group': '2K/QHD'},
        {'label': '📸 2560x1440 (QHD) - 15 FPS', 'value': '2560x1440', 'group': '2K/QHD'},
        {'label': '📸 2560x1600 (WQHD) - 12 FPS', 'value': '2560x1600', 'group': '2K/QHD'},

        # === MAKSİMUM (5-15 FPS) ===
        {'label': '📷 2592x1944 (Max 5MP) - 10 FPS', 'value': '2592x1944', 'group': 'Maksimum'},
        {'label': '📷 1944x1944 (Max Square) - 10 FPS', 'value': '1944x1944', 'group': 'Maksimum'},

        # === ÖZEL FORMAT ===
        {'label': '🎞️ 2560x1080 (21:9 Ultrawide) - 20 FPS', 'value': '2560x1080', 'group': 'Özel'},
        {'label': '🎞️ 2048x858 (2.39:1 Cinematic) - 25 FPS', 'value': '2048x858', 'group': 'Özel'},
        {'label': '📱 720x1280 (Portrait HD) - 60 FPS', 'value': '720x1280', 'group': 'Özel'},
        {'label': '📱 1080x1920 (Portrait FHD) - 30 FPS', 'value': '1080x1920', 'group': 'Özel'},
    ]

    # === ÇÖZÜNÜRLÜĞE GÖRE ÖNERİLEN MAX FPS (Güncellenmiş) ===
    RESOLUTION_FPS_LIMITS = {
        # Performans
        (320, 240): 120,
        (640, 480): 90,
        (640, 640): 90,

        # Standart
        (800, 600): 75,
        (1024, 768): 60,

        # HD
        (1280, 720): 60,
        (1280, 960): 50,
        (1296, 972): 40,
        (1600, 900): 35,
        (1600, 1200): 30,

        # Full HD
        (1920, 1080): 30,
        (1920, 1200): 25,
        (1080, 1080): 30,

        # 2K/QHD
        (2048, 1536): 20,
        (2560, 1440): 15,
        (2560, 1600): 12,
        (2560, 1080): 20,  # Ultrawide

        # Maksimum
        (2592, 1944): 10,
        (1944, 1944): 10,

        # Özel
        (2048, 858): 25,   # Cinematic
        (720, 1280): 60,   # Portrait HD
        (1080, 1920): 30,  # Portrait FHD
    }

    # === ÇÖZÜNÜRLÜK GRUPLARI (UI için) ===
    RESOLUTION_GROUPS = {
        'Performans': 'Yüksek FPS - Düşük Çözünürlük',
        'Standart': 'Dengeli - Orta Çözünürlük',
        'HD': 'HD Kalite - İyi FPS',
        'Full HD': 'Full HD - Orta FPS',
        '2K/QHD': 'Yüksek Kalite - Düşük FPS',
        'Maksimum': 'Maksimum Kalite - Fotoğraf İçin',
        'Özel': 'Özel Aspect Ratios'
    }

    # === YENİ (v3.16) FRAMERATE AYARLARI ===
    MIN_FRAMERATE = 5
    MAX_FRAMERATE = 60
    DEFAULT_FRAMERATE = 30



    # === YENİ (v3.16) MANUEL POZLAMA AYARLARI ===
    # Exposure Time (mikrosaniye)
    MIN_EXPOSURE_TIME = 100        # 0.1 ms
    MAX_EXPOSURE_TIME = 200000     # 200 ms
    DEFAULT_EXPOSURE_TIME = 10000  # 10 ms

    # ISO (Analogue Gain)
    MIN_ANALOGUE_GAIN = 1.0
    MAX_ANALOGUE_GAIN = 16.0
    DEFAULT_ANALOGUE_GAIN = 1.0

    # === YENİ (v3.16) GÖRÜNTÜ İYİLEŞTİRME ===
    # Brightness (-1.0 ile 1.0)
    MIN_BRIGHTNESS = -1.0
    MAX_BRIGHTNESS = 1.0
    DEFAULT_BRIGHTNESS = 0.0

    # Contrast (0.0 ile 32.0)
    MIN_CONTRAST = 0.0
    MAX_CONTRAST = 32.0
    DEFAULT_CONTRAST = 1.0

    # Saturation (0.0 ile 32.0)
    MIN_SATURATION = 0.0
    MAX_SATURATION = 32.0
    DEFAULT_SATURATION = 1.0

    # Sharpness (0.0 ile 16.0)
    MIN_SHARPNESS = 0.0
    MAX_SHARPNESS = 16.0
    DEFAULT_SHARPNESS = 1.0

    # === YENİ (v3.16) AWB (AUTO WHITE BALANCE) MODLARI ===
    AWB_MODES = {
        'Auto': 0,       # Otomatik
        'Tungsten': 1,   # Akkor lamba (3000K)
        'Fluorescent': 2,# Floresan (4000K)
        'Indoor': 3,     # İç mekan
        'Daylight': 4,   # Gün ışığı (5500K)
        'Cloudy': 5,     # Bulutlu (6500K)
        'Custom': 6      # Özel
    }
    DEFAULT_AWB_MODE = 'Auto'

    # === YENİ (v3.16) COLOUR EFFECTS (RENK EFEKTLERİ) ===
    COLOUR_EFFECTS = {
        'None': (0, 0),           # Normal
        'Negative': (1, 0),       # Negatif
        'Solarise': (2, 0),       # Solar
        'Sketch': (3, 0),         # Eskiz
        'Denoise': (4, 0),        # Gürültü azaltma
        'Emboss': (5, 0),         # Kabartma
        'Oilpaint': (6, 0),       # Yağlı boya
        'Hatch': (7, 0),          # Tarama
        'Gpen': (8, 0),           # Grafik kalem
        'Pastel': (9, 0),         # Pastel
        'Watercolour': (10, 0),   # Sulu boya
        'Film': (11, 0),          # Film
        'Blur': (12, 0),          # Bulanık
        'Saturation': (13, 0),    # Doygunluk
        'Colourswap': (14, 0),    # Renk takası
        'Washedout': (15, 0),     # Soluk
        'Posterise': (16, 0),     # Posterleştir
        'Colourpoint': (17, 0),   # Renk noktası
        'Colourbalance': (18, 0), # Renk dengesi
        'Cartoon': (19, 0),       # Çizgi film
        'Sepia': (20, 0),         # Sepya
    }
    DEFAULT_COLOUR_EFFECT = 'None'

    # === YENİ (v3.16) FLICKER MODLARI (TITREME AZALTMA) ===
    FLICKER_MODES = {
        'Off': 0,      # Kapalı
        '50Hz': 1,     # 50 Hz (Avrupa)
        '60Hz': 2,     # 60 Hz (Amerika)
        'Auto': 3      # Otomatik
    }
    DEFAULT_FLICKER_MODE = 'Off'

    # === YENİ (v3.16) EXPOSURE MODES ===
    EXPOSURE_MODES = {
        'Normal': 0,      # Normal pozlama
        'Short': 1,       # Kısa pozlama
        'Long': 2,        # Uzun pozlama
        'Custom': 3       # Özel
    }
    DEFAULT_EXPOSURE_MODE = 'Normal'

    # === YENİ (v3.16) METERING MODES (ÖLÇÜM MODLARı) ===
    METERING_MODES = {
        'Centre': 0,         # Merkez ağırlıklı
        'Spot': 1,           # Nokta
        'Matrix': 2,         # Matris
        'Custom': 3          # Özel
    }
    DEFAULT_METERING_MODE = 'Centre'

    # MEVCUT AYARLAR
    IMAGE_QUALITY = 85
    IMAGE_MAX_SIZE = (1920, 1440)

    ENABLE_LENS_CORRECTION = False
    DISTORTION_COEFFICIENTS = [-0.35, 0.15, 0, 0, -0.05]
    ENABLE_PHOTO_LENS_CORRECTION = True
    ENABLE_VIDEO_LENS_CORRECTION = False

    ENABLE_AUTO_WHITE_BALANCE = True
    ENABLE_AUTO_EXPOSURE = True
    ENABLE_DENOISE = True
    DENOISE_MODE = "fast"
    ENABLE_SHARPENING = True
    SHARPNESS_LEVEL = 1.5

    # Video ayarları
    VIDEO_FORMAT = 'h264'
    VIDEO_FRAMERATE = 30
    VIDEO_BITRATE = 8000000
    MAX_VIDEO_DURATION = 600
    VIDEO_PROFILE = 'high'
    VIDEO_LEVEL = '4.1'
    VIDEO_INLINE_HEADERS = True

    # FRAME BUFFER VE CACHE
    CACHE_SIZE = 3
    ENABLE_FRAME_CACHE = True
    FRAME_BUFFER_SIZE = 2
    USE_ZERO_COPY = True
    BUFFER_COUNT = 4

    # PERFORMANS OPTİMİZASYONU
    USE_GPU_ACCELERATION = True
    ENABLE_THREADING = True
    MAX_WORKER_THREADS = 2
    PRIORITY_MODE = "latency"
    ENABLE_FRAME_SKIP = True
    MAX_FRAME_SKIP = 2

    # PICAMERA2 ÖZEL AYARLARI
    PICAMERA2_TUNING_FILE = None
    TRANSFORM = 0
    COLOUR_SPACE = "sRGB"

    # Kontrol algoritmaları
    AE_CONSTRAINT_MODE = 0
    AE_METERING_MODE = 0
    AE_EXPOSURE_MODE = 0
    AWB_MODE = 0
    NOISE_REDUCTION_MODE = 2

    # Kayıt yolları
    PHOTO_SAVE_DIR = Path("media/camera_photos")
    VIDEO_SAVE_DIR = Path("media/camera_videos")
    CALIBRATION_DIR = Path("media/calibration")
    TEMP_DIR = Path("media/temp")

    @classmethod
    def create_directories(cls):
        """Gerekli klasörleri oluştur"""
        try:
            for dir_path in [cls.PHOTO_SAVE_DIR, cls.VIDEO_SAVE_DIR,
                             cls.CALIBRATION_DIR, cls.TEMP_DIR]:
                dir_path.mkdir(parents=True, exist_ok=True)
            logging.info(f"✓ Dizinler oluşturuldu")
        except Exception as e:
            logging.error(f"Dizin oluşturma hatası: {e}")

    @classmethod
    def validate_framerate(cls, fps: float, resolution: Tuple[int, int]) -> float:
        """Framerate'i kamera ve çözünürlük limitlerinde tut"""
        # Genel limitler
        if fps < cls.MIN_FRAMERATE:
            logging.warning(f"FPS çok düşük: {fps}, min {cls.MIN_FRAMERATE}")
            return cls.MIN_FRAMERATE
        if fps > cls.MAX_FRAMERATE:
            logging.warning(f"FPS çok yüksek: {fps}, max {cls.MAX_FRAMERATE}")
            return cls.MAX_FRAMERATE

        # Çözünürlüğe özel limit
        max_fps_for_res = cls.RESOLUTION_FPS_LIMITS.get(resolution, cls.MAX_FRAMERATE)
        if fps > max_fps_for_res:
            logging.warning(f"FPS {resolution} için çok yüksek: {fps}, max {max_fps_for_res}")
            return max_fps_for_res

        return fps

    @classmethod
    def validate_exposure_time(cls, exposure_us: int) -> int:
        """Pozlama süresini validasyon yap"""
        return max(cls.MIN_EXPOSURE_TIME, min(cls.MAX_EXPOSURE_TIME, exposure_us))

    @classmethod
    def validate_gain(cls, gain: float) -> float:
        """ISO gain'i validasyon yap"""
        return max(cls.MIN_ANALOGUE_GAIN, min(cls.MAX_ANALOGUE_GAIN, gain))

    @classmethod
    def validate_brightness(cls, brightness: float) -> float:
        """Brightness'ı validasyon yap"""
        return max(cls.MIN_BRIGHTNESS, min(cls.MAX_BRIGHTNESS, brightness))

    @classmethod
    def validate_contrast(cls, contrast: float) -> float:
        """Contrast'ı validasyon yap"""
        return max(cls.MIN_CONTRAST, min(cls.MAX_CONTRAST, contrast))

    @classmethod
    def validate_saturation(cls, saturation: float) -> float:
        """Saturation'ı validasyon yap"""
        return max(cls.MIN_SATURATION, min(cls.MAX_SATURATION, saturation))

    @classmethod
    def validate_sharpness(cls, sharpness: float) -> float:
        """Sharpness'ı validasyon yap"""
        return max(cls.MIN_SHARPNESS, min(cls.MAX_SHARPNESS, sharpness))

    @classmethod
    def get_camera_settings(cls, **kwargs) -> Dict[str, Any]:
        """
        Kamera için optimize edilmiş ayarları döndür
        YENİ (v3.16): Tüm manuel kontroller destekleniyor

        kwargs:
            framerate: float
            ae_enable: bool
            awb_enable: bool
            exposure_time: int (mikrosaniye)
            analogue_gain: float
            brightness: float
            contrast: float
            saturation: float
            sharpness: float
            awb_mode: str
            colour_effect: str
            flicker_mode: str
            exposure_mode: str
            metering_mode: str
        """
        # Varsayılan değerler
        framerate = kwargs.get('framerate', cls.DEFAULT_FRAMERATE)
        ae_enable = kwargs.get('ae_enable', cls.ENABLE_AUTO_EXPOSURE)
        awb_enable = kwargs.get('awb_enable', cls.ENABLE_AUTO_WHITE_BALANCE)

        # YENİ: Manuel kontroller
        exposure_time = kwargs.get('exposure_time', cls.DEFAULT_EXPOSURE_TIME)
        analogue_gain = kwargs.get('analogue_gain', cls.DEFAULT_ANALOGUE_GAIN)
        brightness = kwargs.get('brightness', cls.DEFAULT_BRIGHTNESS)
        contrast = kwargs.get('contrast', cls.DEFAULT_CONTRAST)
        saturation = kwargs.get('saturation', cls.DEFAULT_SATURATION)
        sharpness = kwargs.get('sharpness', cls.DEFAULT_SHARPNESS)

        awb_mode = kwargs.get('awb_mode', cls.DEFAULT_AWB_MODE)
        colour_effect = kwargs.get('colour_effect', cls.DEFAULT_COLOUR_EFFECT)
        flicker_mode = kwargs.get('flicker_mode', cls.DEFAULT_FLICKER_MODE)
        exposure_mode = kwargs.get('exposure_mode', cls.DEFAULT_EXPOSURE_MODE)
        metering_mode = kwargs.get('metering_mode', cls.DEFAULT_METERING_MODE)

        settings = {
            # Temel kontroller
            "AeEnable": ae_enable,
            "AwbEnable": awb_enable,
            "FrameRate": framerate,

            # Manuel Pozlama (sadece AE kapalıysa)
            "ExposureTime": 0 if ae_enable else cls.validate_exposure_time(exposure_time),
            "AnalogueGain": 0.0 if ae_enable else cls.validate_gain(analogue_gain),

            # Pozlama Modları
            "AeConstraintMode": cls.AE_CONSTRAINT_MODE,
            "AeMeteringMode": cls.METERING_MODES.get(metering_mode, 0),
            "AeExposureMode": cls.EXPOSURE_MODES.get(exposure_mode, 0),

            # White Balance
            "AwbMode": cls.AWB_MODES.get(awb_mode, 0),
            "ColourGains": (0, 0),  # Auto için

            # Görüntü İyileştirme
            "Brightness": cls.validate_brightness(brightness),
            "Contrast": cls.validate_contrast(contrast),
            "Saturation": cls.validate_saturation(saturation),
            "Sharpness": cls.validate_sharpness(sharpness),

            # Gürültü Azaltma
            "NoiseReductionMode": cls.NOISE_REDUCTION_MODE if cls.ENABLE_DENOISE else 0,

            # Frame Duration (FPS kontrolü için - mikrosaniye)
            "FrameDurationLimits": (
                int(1000000 / framerate),  # Min duration (max FPS)
                int(1000000 / framerate)   # Max duration (min FPS)
            ),

            # Diğer
            "ExposureValue": 0.0,
        }

        # Flicker Mode (destekleniyorsa)
        if 'AeFlickerMode' in dir(controls):
            settings["AeFlickerMode"] = cls.FLICKER_MODES.get(flicker_mode, 0)

        # Colour Effect (destekleniyorsa)
        if 'ColourEffect' in dir(controls):
            settings["ColourEffect"] = cls.COLOUR_EFFECTS.get(colour_effect, (0, 0))

        return settings

    @classmethod
    def get_video_config(cls) -> Dict[str, Any]:
        """Video için özel yapılandırma"""
        return {
            "format": cls.VIDEO_FORMAT,
            "bitrate": cls.VIDEO_BITRATE,
            "profile": cls.VIDEO_PROFILE,
            "level": cls.VIDEO_LEVEL,
            "intra_period": cls.VIDEO_FRAMERATE,
            "inline_headers": cls.VIDEO_INLINE_HEADERS,
            "repeat_sequence_header": True,
        }

    @classmethod
    def get_preview_config(cls) -> Dict[str, Any]:
        """Canlı önizleme için optimize yapılandırma"""
        return {
            "size": cls.PERFORMANCE_RESOLUTION,
            "format": "RGB888",
            "buffer_count": cls.BUFFER_COUNT,
        }

    @classmethod
    def get_capture_config(cls) -> Dict[str, Any]:
        """Fotoğraf çekimi için yüksek kalite yapılandırma"""
        return {
            "size": cls.BALANCED_RESOLUTION,
            "format": "RGB888",
            "buffer_count": 1,
        }


# --- UYGULAMA AYARLARI ---
class AppConfig:
    """Dash uygulaması ve sistem ayarları"""

    APP_NAME = 'CameraControl'
    APP_VERSION = "3.18-ULTIMATE-REFACTORED" # Sürüm güncellendi

    # INTERVAL AYARLARI
    CAMERA_INTERVAL_MS = 50
    MOTOR_UPDATE_INTERVAL_MS = 250
    METRICS_INTERVAL_MS = 500
    CLEANUP_INTERVAL_MS = 60000  # 1 dakika

    # YENİ: AI CANLI İŞLEME ARALIĞI
    AI_UPDATE_INTERVAL_MS = 500 # Saniyede 2 kare AI işleme

    ENABLE_FAST_UPDATE_MODE = True

    # Adaptif interval
    ENABLE_ADAPTIVE_INTERVAL = True
    MIN_CAMERA_INTERVAL_MS = 16
    MAX_CAMERA_INTERVAL_MS = 100

    # WebSocket ayarları
    ENABLE_WEBSOCKET = False
    WEBSOCKET_PORT = 8765

    # Bellek yönetimi - OPTİMİZE
    MAX_PHOTOS_IN_MEMORY = 20
    MAX_SCAN_POINTS = 1000
    MAX_METRICS_HISTORY = 50
    MAX_FRAME_BUFFER_AGE_SECONDS = 300  # 5 dakika

    # Garbage collection
    ENABLE_MANUAL_GC = True
    GC_INTERVAL_MS = 10000

    # Thread ayarları
    LOCK_TIMEOUT = 2.0  # v3.16: 1.0'dan 2.0'a çıkarıldı
    USE_THREAD_POOL = True
    MAX_THREAD_POOL_SIZE = 4

    # Retry mekanizması
    MAX_RETRY_COUNT = 3
    RETRY_DELAY = 0.5
    USE_EXPONENTIAL_BACKOFF = True

    # Circuit Breaker
    ENABLE_CIRCUIT_BREAKER = True
    CIRCUIT_FAILURE_THRESHOLD = 3
    CIRCUIT_RECOVERY_TIMEOUT = 30

    # Stil kaynakları
    FONT_AWESOME = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"
    BOOTSTRAP_THEME = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/cyborg/bootstrap.min.css"

    # 3D görünüm ayarları
    RANGE_LIMIT_3D = 300
    ENABLE_3D_ANIMATION = False

    # Cache ayarları
    USE_REDIS_CACHE = False
    REDIS_HOST = 'localhost'
    REDIS_PORT = 6379
    CACHE_TTL = 180


# --- PERFORMANS AYARLARI ---
class PerformanceConfig:
    """Performans optimizasyon ayarları"""

    # CPU Ayarları - RASPBERRY Pi 5 İÇİN
    CPU_AFFINITY = [2, 3]
    NICE_LEVEL = -10

    # CPU Frequency
    SET_CPU_GOVERNOR = True
    CPU_GOVERNOR = "performance"

    # GPU Ayarları
    USE_GPU_ENCODE = True
    GPU_MEM_SPLIT = 256

    # Bellek Ayarları - OPTİMİZE
    PREALLOCATE_BUFFERS = True
    BUFFER_POOL_SIZE = 6
    USE_MEMORY_MAPPING = True

    # Swap
    DISABLE_SWAP = False
    SWAPPINESS = 10

    # I/O Ayarları
    USE_ASYNC_IO = True
    IO_BUFFER_SIZE = 131072
    IO_SCHEDULER = "deadline"

    # Network Ayarları
    ENABLE_TCP_NODELAY = True
    SOCKET_TIMEOUT = 15

    # Profiling
    ENABLE_PROFILING = False
    PROFILE_OUTPUT_DIR = Path("profiling")

    # FPS Monitoring
    ENABLE_FPS_MONITORING = True
    FPS_WINDOW_SIZE = 30


# --- MOTOR AYARLARI ---
class MotorConfig:
    """Step motor için geliştirilmiş ayarlar"""

    # Yatay motor pinleri
    H_MOTOR_IN1 = 26
    H_MOTOR_IN2 = 19
    H_MOTOR_IN3 = 13
    H_MOTOR_IN4 = 6

    # Dikey motor pinleri (opsiyonel)
    V_MOTOR_IN1 = None
    V_MOTOR_IN2 = None
    V_MOTOR_IN3 = None
    V_MOTOR_IN4 = None

    # Limit switch pinleri
    LIMIT_SWITCH_MIN = None
    LIMIT_SWITCH_MAX = None

    # Motor özellikleri
    STEPS_PER_REV = 4096
    INTER_STEP_DELAY = 0.003
    SETTLE_TIME = 0.05

    # Hız profilleri
    SPEED_PROFILES = {
        'slow': {'delay': 0.008, 'acceleration': 0.5},
        'normal': {'delay': 0.003, 'acceleration': 1.0},
        'fast': {'delay': 0.001, 'acceleration': 1.3},
        'scan': {'delay': 0.002, 'acceleration': 1.2}
    }

    INVERT_DIRECTION = True
    MIN_ANGLE = -180
    MAX_ANGLE = 180
    BUTTON_STEP = 10
    FINE_STEP = 1
    BACKLASH_COMPENSATION = 2

    STEP_SEQUENCE = [
        [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
        [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
    ]


# --- SENSÖR AYARLARI ---
class SensorConfig:
    """Ultrasonik sensör için optimize edilmiş ayarlar"""

    # GPIO Pinleri
    H_TRIG = 23
    H_ECHO = 24
    V_TRIG = None
    V_ECHO = None

    # Okuma Parametreleri
    MAX_DISTANCE = 4.0
    QUEUE_LEN = 9
    THRESHOLD_DISTANCE = 0.3

    # Geçerli Mesafe Aralığı
    MIN_VALID_DISTANCE = 2
    MAX_VALID_DISTANCE = 400

    # Kalibrasyon
    CALIBRATION_OFFSET = 0.0

    # Sıcaklık
    TEMPERATURE = 25
    TEMPERATURE_COMPENSATION = True

    # Okuma Ayarları
    SETTLE_TIME = 0.05
    READ_ATTEMPTS = 5
    READ_DELAY = 0.1

    # Adaptif Okuma
    ADAPTIVE_READING = True
    MIN_READ_INTERVAL = 0.1
    MAX_READ_INTERVAL = 1.0

    # Filtreleme
    USE_MEDIAN_FILTER = True
    USE_KALMAN_FILTER = False

    @classmethod
    def calculate_sound_speed(cls) -> float:
        """Sıcaklığa göre ses hızını hesapla"""
        return 331.3 + (0.606 * cls.TEMPERATURE)


# --- LOG AYARLARI ---
class LogConfig:
    """Gelişmiş loglama yapılandırması"""

    CONSOLE_LEVEL = logging.INFO
    FILE_LEVEL = logging.DEBUG

    CONSOLE_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
    FILE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'

    LOG_DIR = Path("logs")
    MAIN_LOG_FILE = LOG_DIR / 'camera_app.log'
    ERROR_LOG_FILE = LOG_DIR / 'errors.log'
    PERFORMANCE_LOG_FILE = LOG_DIR / 'performance.log'
    FPS_LOG_FILE = LOG_DIR / 'fps.log'

    MAX_BYTES = 10 * 1024 * 1024
    BACKUP_COUNT = 5

    ENABLE_MOTOR_LOG = True
    ENABLE_SENSOR_LOG = True
    ENABLE_CAMERA_LOG = True

    @classmethod
    def setup_logging(cls):
        """Logging'i yapılandır"""
        import logging.handlers

        cls.LOG_DIR.mkdir(exist_ok=True)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(cls.CONSOLE_LEVEL)
        console_handler.setFormatter(logging.Formatter(cls.CONSOLE_FORMAT))
        root_logger.addHandler(console_handler)

        # File handler
        file_handler = logging.handlers.RotatingFileHandler(
            cls.MAIN_LOG_FILE,
            maxBytes=cls.MAX_BYTES,
            backupCount=cls.BACKUP_COUNT
        )
        file_handler.setLevel(cls.FILE_LEVEL)
        file_handler.setFormatter(logging.Formatter(cls.FILE_FORMAT))
        root_logger.addHandler(file_handler)

        # Error handler
        error_handler = logging.handlers.RotatingFileHandler(
            cls.ERROR_LOG_FILE,
            maxBytes=cls.MAX_BYTES,
            backupCount=cls.BACKUP_COUNT
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(cls.FILE_FORMAT))
        root_logger.addHandler(error_handler)

        logging.info("="*60)
        logging.info(f"RASPBERRY PI 5 KAMERA SİSTEMİ v{AppConfig.APP_VERSION}")
        logging.info("Tüm Manuel Kontroller + AI Vision + Refactored")
        logging.info("="*60)


# --- SİSTEM KONTROLLERİ ---
class SystemChecks:
    """Sistem gereksinimleri kontrol"""

    @staticmethod
    def check_raspberry_pi() -> bool:
        try:
            with open('/proc/device-tree/model', 'r') as f:
                model = f.read()
                if 'Raspberry Pi' in model:
                    logging.info(f"✓ Sistem: {model.strip()}")
                    return True
        except:
            pass
        logging.warning("⚠ Raspberry Pi algılanamadı")
        return False

    @staticmethod
    def check_camera() -> bool:
        """Kamerayı libcamera ile kontrol et"""
        try:
            from picamera2 import Picamera2
            cameras = Picamera2.global_camera_info()

            if len(cameras) > 0:
                logging.info(f"✓ {len(cameras)} adet kamera algılandı.")
                if cameras[0].get('Model'):
                    logging.info(f"  Model: {cameras[0].get('Model', 'Bilinmeyen')}")
                return True
            else:
                logging.warning("⚠ Kamera bulunamadı.")
                return False

        except ImportError:
            logging.warning("⚠ picamera2 kütüphanesi yok.")
            return False
        except Exception as e:
            logging.error(f"Kamera kontrol hatası: {e}")
            return False

    @staticmethod
    def check_gpio() -> bool:
        try:
            import gpiozero
            logging.info("✓ GPIO kütüphanesi hazır")
            return True
        except ImportError:
            logging.warning("⚠ GPIO kütüphanesi yok - Simülasyon modu")
            return False

    @staticmethod
    def check_cpu_temp() -> Optional[float]:
        """CPU sıcaklığını kontrol et"""
        import subprocess
        try:
            result = subprocess.run(['vcgencmd', 'measure_temp'],
                                    capture_output=True, text=True, timeout=2)
            temp_str = result.stdout.strip()
            temp = float(temp_str.replace("temp=", "").replace("'C", ""))
            logging.info(f"✓ CPU Sıcaklığı: {temp}°C")
            if temp > 80:
                logging.warning(f"⚠ YÜKSEK CPU SICAKLIĞI: {temp}°C")
            return temp
        except:
            return None

    @staticmethod
    def check_memory() -> Dict[str, float]:
        """Bellek kullanımını kontrol et"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            logging.info(f"✓ Bellek: {mem.percent}% ({mem.used // 1024 // 1024}MB / {mem.total // 1024 // 1024}MB)")
            return {
                'percent': mem.percent,
                'used_mb': mem.used // 1024 // 1024,
                'total_mb': mem.total // 1024 // 1024
            }
        except ImportError:
            return {}

    @classmethod
    def run_all_checks(cls) -> Dict[str, Any]:
        """Tüm kontrolleri çalıştır"""
        checks = {
            'raspberry_pi': cls.check_raspberry_pi(),
            'camera': cls.check_camera(),
            'gpio': cls.check_gpio(),
            'cpu_temp': cls.check_cpu_temp(),
            'memory': cls.check_memory()
        }

        logging.info("="*60)
        logging.info("SİSTEM DURUM ÖZETİ:")
        for key, value in checks.items():
            if isinstance(value, bool):
                status = "✓ OK" if value else "✗ FAIL"
                logging.info(f"  {key}: {status}")
        logging.info("="*60)

        return checks


# --- KALİBRASYON AYARLARI ---
class CalibrationConfig:
    """Kamera ve sensör kalibrasyon ayarları"""

    CHECKERBOARD_SIZE = (9, 6)
    SQUARE_SIZE = 25
    MIN_CALIBRATION_IMAGES = 10
    SENSOR_CALIBRATION_POINTS = 10
    SENSOR_CALIBRATION_DISTANCES = [10, 20, 50, 100, 200]
    MOTOR_CALIBRATION_ANGLE = 360
    MOTOR_EXPECTED_STEPS = 4096




# --- DJANGO AYARLARI ---
class DjangoConfig:
    """Django entegrasyonu ayarları"""
    MODEL_NAME = 'CameraCapture'
    MODEL_APP = 'scanner'
    USE_POSTGRES = False
    DB_CONNECTION_POOL_SIZE = 10
    USE_DJANGO_CACHE = True
    CACHE_BACKEND = 'django.core.cache.backends.locmem.LocMemCache'


# Uygulama başlangıcında
def initialize_config():
    """Tüm yapılandırmaları başlat"""
    CameraConfig.create_directories()
    LogConfig.setup_logging()
    system_status = SystemChecks.run_all_checks()

    if PerformanceConfig.ENABLE_PROFILING:
        PerformanceConfig.PROFILE_OUTPUT_DIR.mkdir(exist_ok=True)

    if PerformanceConfig.SET_CPU_GOVERNOR:
        try:
            import subprocess
            subprocess.run(['sudo', 'cpufreq-set', '-g',
                            PerformanceConfig.CPU_GOVERNOR],
                           capture_output=True, timeout=2)
            logging.info(f"✓ CPU Governor: {PerformanceConfig.CPU_GOVERNOR}")
        except:
            logging.debug("CPU governor ayarlanamadı (normal)")

    return system_status


# Otomatik başlatma
if __name__ != "__main__":
    system_status = initialize_config()
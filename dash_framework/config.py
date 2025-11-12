# config.py - OPTIMIZE EDİLMİŞ VERSİYON
# Raspberry Pi 5 + OV5647 130° Kamera
# Görüntü Kalitesi ve FPS İyileştirmeleri

import logging
from pathlib import Path
from typing import Dict, Any, Optional
import json

# --- KAMERA AYARLARI (OPTİMİZE EDİLMİŞ) ---
class CameraConfig:
    """OV5647 130° kamera için optimize edilmiş ayarlar"""

    # Kamera Model Bilgileri
    CAMERA_MODEL = "OV5647"
    FOV_HORIZONTAL = 130  # derece
    FOV_VERTICAL = 100    # derece
    SENSOR_WIDTH = 3.68   # mm
    SENSOR_HEIGHT = 2.76  # mm

    # ÇÖZÜNÜRLÜKLERİ OPTİMİZE ET
    # OV5647 için en iyi performans/kalite dengesi
    DEFAULT_RESOLUTION = (1296, 972)  # Native resolution, en hızlı

    # Alternatif çözünürlükler (FPS için)
    PERFORMANCE_RESOLUTION = (640, 480)   # 60-90 FPS
    BALANCED_RESOLUTION = (1296, 972)     # 30-40 FPS (ÖNERİLEN)
    QUALITY_RESOLUTION = (1920, 1080)     # 15-25 FPS
    MAX_RESOLUTION = (2592, 1944)         # 5-10 FPS (sadece fotoğraf)

    RESOLUTIONS = [
        {'label': '640x480 (VGA - Yüksek FPS)', 'value': '640x480'},
        {'label': '1296x972 (Native - ÖNERİLEN)', 'value': '1296x972'},
        {'label': '1920x1080 (Full HD)', 'value': '1920x1080'},
        {'label': '2592x1944 (Max - Sadece Fotoğraf)', 'value': '2592x1944'},
    ]

    # GÖRÜNTÜ KALİTESİ OPTİMİZASYONU
    IMAGE_QUALITY = 85  # JPEG kalitesi (75'ten 85'e yükseltildi)
    IMAGE_MAX_SIZE = (1920, 1440)  # Daha büyük boyut limiti

    # LENS DİSTORSİYON DÜZELTMESİ - DİKKATLİ KULLAN!
    # Bu işlem CPU yükü yaratır ve FPS düşürür
    ENABLE_LENS_CORRECTION = False  # ÖNEMLİ: False yapıldı (FPS için)
    DISTORTION_COEFFICIENTS = [-0.35, 0.15, 0, 0, -0.05]

    # Lens düzeltmeyi sadece fotoğraflarda uygula
    ENABLE_PHOTO_LENS_CORRECTION = True
    ENABLE_VIDEO_LENS_CORRECTION = False

    # KAMERA KONTROL AYARLARI - OPTİMİZE EDİLDİ
    ENABLE_AUTO_WHITE_BALANCE = True
    ENABLE_AUTO_EXPOSURE = True

    # Ek kontroller
    ENABLE_DENOISE = True          # Gürültü azaltma
    DENOISE_MODE = "fast"          # "off", "fast", "high_quality"
    ENABLE_SHARPENING = True       # Keskinleştirme
    SHARPNESS_LEVEL = 1.5          # 1.0 = normal, 2.0 = maksimum

    # Video ayarları - OPTİMİZE
    VIDEO_FORMAT = 'h264'
    VIDEO_FRAMERATE = 30           # Sabit 30 FPS hedefi
    VIDEO_BITRATE = 8000000        # 5M'den 8M'e yükseltildi (daha iyi kalite)
    MAX_VIDEO_DURATION = 600       # 10 dakika

    # H264 encoder profili
    VIDEO_PROFILE = 'high'         # 'baseline', 'main', 'high'
    VIDEO_LEVEL = '4.1'
    VIDEO_INLINE_HEADERS = True

    # FRAME BUFFER VE CACHE - KRİTİK OPTİMİZASYON
    CACHE_SIZE = 3                 # 5'ten 3'e düşürüldü (bellek)
    ENABLE_FRAME_CACHE = True
    FRAME_BUFFER_SIZE = 2          # 3'ten 2'ye düşürüldü

    # Buffer yönetimi
    USE_ZERO_COPY = True           # YENİ: Zero-copy buffer transfer
    BUFFER_COUNT = 4               # YENİ: Picamera2 buffer sayısı

    # PERFORMANS OPTİMİZASYONU
    USE_GPU_ACCELERATION = True
    ENABLE_THREADING = True
    MAX_WORKER_THREADS = 2         # 4'ten 2'ye (kamera işleri için yeterli)

    # İşlem önceliklendirme
    PRIORITY_MODE = "latency"      # "latency" veya "throughput"

    # Frame atlama (düşük performansta)
    ENABLE_FRAME_SKIP = True       # FPS düşükse frame atla
    MAX_FRAME_SKIP = 2             # En fazla 2 frame atla

    # PICAMERA2 ÖZEL AYARLARI
    PICAMERA2_TUNING_FILE = None   # Özel tuning dosyası (opsiyonel)
    TRANSFORM = 0                  # libcamera.Transform (0=yok, 1=rotate, 2=hflip...)

    # Colour processing
    COLOUR_SPACE = "sRGB"          # "sRGB" veya "Rec709"

    # Kontrol algoritmaları
    AE_CONSTRAINT_MODE = "Normal"  # "Normal", "Highlight", "Shadows"
    AE_METERING_MODE = "CentreWeighted"  # "CentreWeighted", "Spot", "Matrix"
    AWB_MODE = "auto"              # "auto", "daylight", "cloudy", etc.

    # Kayıt yolları
    PHOTO_SAVE_DIR = Path("media/camera_photos")
    VIDEO_SAVE_DIR = Path("media/camera_videos")
    CALIBRATION_DIR = Path("media/calibration")
    TEMP_DIR = Path("media/temp")  # YENİ: Geçici dosyalar için

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
    def get_camera_settings(cls) -> Dict[str, Any]:
        """
        Kamera için optimize edilmiş ayarları döndür
        GÖRÜNTÜ KALİTESİ VE FPS DENGESİ
        """
        return {
            # Exposure - Otomatik ama kontrollü
            "ExposureTime": 0,  # 0 = auto (manuel: 20000)
            "AeEnable": cls.ENABLE_AUTO_EXPOSURE,
            "AeConstraintMode": cls.AE_CONSTRAINT_MODE,
            "AeMeteringMode": cls.AE_METERING_MODE,

            # Gain - Düşük ışıkta iyileştirme
            "AnalogueGain": 0.0,  # 0 = auto (manuel: 2.0)

            # White Balance - Renk kalitesi
            "AwbEnable": cls.ENABLE_AUTO_WHITE_BALANCE,
            "AwbMode": cls.AWB_MODE,
            "ColourGains": (0, 0),  # (0,0) = auto

            # Görüntü iyileştirme
            "Saturation": 1.1,    # Canlı renkler
            "Sharpness": cls.SHARPNESS_LEVEL,
            "Contrast": 1.15,     # Biraz artırıldı
            "Brightness": 0.0,

            # Gürültü azaltma
            "NoiseReductionMode": cls.DENOISE_MODE if cls.ENABLE_DENOISE else "off",

            # Frame rate kontrolü
            "FrameDurationLimits": (33333, 33333),  # 30 FPS sabit (mikrosaniye)

            # Diğer
            "ExposureValue": 0.0,  # EV kompanzasyonu
        }

    @classmethod
    def get_video_config(cls) -> Dict[str, Any]:
        """Video için özel yapılandırma"""
        return {
            "format": cls.VIDEO_FORMAT,
            "bitrate": cls.VIDEO_BITRATE,
            "profile": cls.VIDEO_PROFILE,
            "level": cls.VIDEO_LEVEL,
            "intra_period": cls.VIDEO_FRAMERATE,  # GOP size
            "inline_headers": cls.VIDEO_INLINE_HEADERS,
            "repeat_sequence_header": True,
        }

    @classmethod
    def get_preview_config(cls) -> Dict[str, Any]:
        """Canlı önizleme için optimize yapılandırma"""
        return {
            "size": cls.PERFORMANCE_RESOLUTION,  # Düşük çözünürlük = yüksek FPS
            "format": "RGB888",  # Hızlı format
            "buffer_count": cls.BUFFER_COUNT,
        }

    @classmethod
    def get_capture_config(cls) -> Dict[str, Any]:
        """Fotoğraf çekimi için yüksek kalite yapılandırma"""
        return {
            "size": cls.BALANCED_RESOLUTION,  # Veya QUALITY_RESOLUTION
            "format": "RGB888",
            "buffer_count": 1,  # Tek buffer yeterli
        }


# --- UYGULAMA AYARLARI (OPTİMİZE) ---
class AppConfig:
    """Dash uygulaması ve sistem ayarları"""

    APP_NAME = 'CameraControl'
    APP_VERSION = "3.1-OPTIMIZED"

    # INTERVAL AYARLARI - KRİTİK FPS OPTİMİZASYONU
    CAMERA_INTERVAL_MS = 33        # 100'den 33'e (30 FPS hedefi)
    MOTOR_UPDATE_INTERVAL_MS = 500  # 250'den 500'e (motor için yeterli)
    METRICS_INTERVAL_MS = 2000     # 5000'den 2000'e (daha responsive)

    # Adaptif interval
    ENABLE_ADAPTIVE_INTERVAL = True
    MIN_CAMERA_INTERVAL_MS = 16    # 60 FPS
    MAX_CAMERA_INTERVAL_MS = 100   # 10 FPS

    # WebSocket ayarları
    ENABLE_WEBSOCKET = False
    WEBSOCKET_PORT = 8765

    # Bellek yönetimi - OPTİMİZE
    MAX_PHOTOS_IN_MEMORY = 20      # 50'den 20'ye (bellek tasarrufu)
    MAX_SCAN_POINTS = 1000         # 2000'den 1000'e
    MAX_METRICS_HISTORY = 50       # 100'den 50'ye

    # Garbage collection
    ENABLE_MANUAL_GC = True        # YENİ: Manuel GC
    GC_INTERVAL_MS = 10000         # Her 10 saniyede bir

    # Thread ayarları
    LOCK_TIMEOUT = 1.0             # 2.0'dan 1.0'a (daha responsive)
    USE_THREAD_POOL = True
    MAX_THREAD_POOL_SIZE = 4       # 10'dan 4'e (kamera için yeterli)

    # Retry mekanizması
    MAX_RETRY_COUNT = 3
    RETRY_DELAY = 0.5              # 1.0'dan 0.5'e
    USE_EXPONENTIAL_BACKOFF = True

    # Circuit Breaker
    ENABLE_CIRCUIT_BREAKER = True
    CIRCUIT_FAILURE_THRESHOLD = 3  # 5'ten 3'e (daha hızlı tepki)
    CIRCUIT_RECOVERY_TIMEOUT = 30  # 60'tan 30'a

    # Stil kaynakları
    FONT_AWESOME = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"
    BOOTSTRAP_THEME = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/cyborg/bootstrap.min.css"

    # 3D görünüm ayarları
    RANGE_LIMIT_3D = 300
    ENABLE_3D_ANIMATION = False    # True'dan False'a (performans)

    # Cache ayarları
    USE_REDIS_CACHE = False
    REDIS_HOST = 'localhost'
    REDIS_PORT = 6379
    CACHE_TTL = 180                # 300'den 180'e


# --- PERFORMANS AYARLARI (OPTİMİZE) ---
class PerformanceConfig:
    """Performans optimizasyon ayarları"""

    # CPU Ayarları - RASPBERRY Pi 5 İÇİN
    CPU_AFFINITY = [2, 3]          # Core 2 ve 3'ü kullan (0,1 sistem için)
    NICE_LEVEL = -10               # -5'ten -10'a (daha yüksek öncelik)

    # CPU Frequency (opsiyonel - dikkatli kullanın)
    SET_CPU_GOVERNOR = True
    CPU_GOVERNOR = "performance"   # "ondemand", "performance", "powersave"

    # GPU Ayarları (Raspberry Pi)
    USE_GPU_ENCODE = True
    GPU_MEM_SPLIT = 256            # MB (128-512 arası)

    # Bellek Ayarları - OPTİMİZE
    PREALLOCATE_BUFFERS = True
    BUFFER_POOL_SIZE = 6           # 10'dan 6'ya
    USE_MEMORY_MAPPING = True      # False'dan True'ya (DMA transfer)

    # Swap kullanımını minimize et
    DISABLE_SWAP = False           # True yaparsanız swap kapatılır
    SWAPPINESS = 10                # Default 60, düşük = az swap

    # I/O Ayarları
    USE_ASYNC_IO = True
    IO_BUFFER_SIZE = 131072        # 64KB'den 128KB'ye
    IO_SCHEDULER = "deadline"      # "deadline" veya "noop" (SD kart için)

    # Network Ayarları
    ENABLE_TCP_NODELAY = True
    SOCKET_TIMEOUT = 15            # 30'dan 15'e

    # Profiling
    ENABLE_PROFILING = False
    PROFILE_OUTPUT_DIR = Path("profiling")

    # FPS Monitoring
    ENABLE_FPS_MONITORING = True   # YENİ: FPS takibi
    FPS_WINDOW_SIZE = 30           # Son 30 frame'in ortalaması


# --- MOTOR AYARLARI (DEĞİŞİKLİK YOK AMA EKLENDİ) ---
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
        'fast': {'delay': 0.001, 'acceleration': 2.0},
        'scan': {'delay': 0.002, 'acceleration': 1.5}
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


# --- SENSÖR AYARLARI (DEĞİŞİKLİK YOK AMA EKLENDİ) ---
class SensorConfig:
    """Ultrasonik sensör için optimize edilmiş ayarlar"""

    H_TRIG = 23
    H_ECHO = 24
    V_TRIG = None
    V_ECHO = None

    MAX_DISTANCE = 4.0
    QUEUE_LEN = 9
    THRESHOLD_DISTANCE = 0.3
    MIN_VALID_DISTANCE = 2
    MAX_VALID_DISTANCE = 400
    CALIBRATION_OFFSET = 0.0
    TEMPERATURE = 25
    TEMPERATURE_COMPENSATION = True
    SETTLE_TIME = 0.05
    READ_ATTEMPTS = 3
    READ_DELAY = 0.03
    ADAPTIVE_READING = True
    MIN_READ_INTERVAL = 0.05
    MAX_READ_INTERVAL = 0.5
    USE_MEDIAN_FILTER = True
    USE_KALMAN_FILTER = False

    @classmethod
    def calculate_sound_speed(cls) -> float:
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
    FPS_LOG_FILE = LOG_DIR / 'fps.log'  # YENİ

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
        logging.info("RASPBERRY PI 5 KAMERA SİSTEMİ v3.1-OPTIMIZED")
        logging.info("Görüntü Kalitesi ve FPS İyileştirmeleri Aktif")
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
        import subprocess
        try:
            result = subprocess.run(['vcgencmd', 'get_camera'],
                                    capture_output=True, text=True, timeout=2)
            if 'detected=1' in result.stdout:
                logging.info("✓ OV5647 kamera algılandı")
                return True
        except:
            pass
        logging.warning("⚠ Kamera algılanamadı - Simülasyon modu")
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
                logging.warning(f"⚠ YÜKSEK CPU SICAKLIĞI: {temp}°C - Soğutma gerekebilir!")
            return temp
        except:
            return None

    @staticmethod
    def check_memory() -> Dict[str, float]:
        """Bellek kullanımını kontrol et"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            logging.info(f"✓ Bellek Kullanımı: {mem.percent}% ({mem.used // 1024 // 1024}MB / {mem.total // 1024 // 1024}MB)")
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

        # Özet
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


# --- YAPAY ZEKA AYARLARI ---
class AIConfig:
    """AI entegrasyonu ayarları (opsiyonel)"""

    ENABLE_AI = False
    AI_MODEL = 'tflite'
    MODEL_PATH = Path("models/object_detection.tflite")
    CONFIDENCE_THRESHOLD = 0.5
    NMS_THRESHOLD = 0.4
    MAX_DETECTIONS = 10
    USE_EDGE_TPU = False
    EDGE_TPU_DEVICE = '/dev/bus/usb/001/002'


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
    # Dizinleri oluştur
    CameraConfig.create_directories()

    # Loglama başlat
    LogConfig.setup_logging()

    # Sistem kontrollerini çalıştır
    system_status = SystemChecks.run_all_checks()

    # Performans logları için dizin
    if PerformanceConfig.ENABLE_PROFILING:
        PerformanceConfig.PROFILE_OUTPUT_DIR.mkdir(exist_ok=True)

    # CPU governor ayarla (Linux)
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
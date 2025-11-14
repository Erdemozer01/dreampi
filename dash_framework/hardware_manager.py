# hardware_manager.py - DÜZELTME v3.17 (Savunmacı Frame Yakalama)
# v3.16'ya ek olarak: Ayar değişikliği sonrası retry mekanizması eklendi

import json
import time
import logging
import threading
import warnings
import cv2
import queue
import hashlib
from typing import Optional, Tuple, Dict, List, Any, Callable
from collections import deque
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import numpy as np

# Config ve Utils dosyalarınızın import edildiğini varsayıyoruz.
try:
    from .config import (
        CameraConfig, MotorConfig, SensorConfig, AppConfig,
        PerformanceConfig, SystemChecks
    )
    from .utils import (
        CircuitBreaker, FrameBuffer, FisheyeCorrector,
        profile_performance, PerformanceMonitor
    )
except ImportError:
    logger = logging.getLogger(__name__)
    logging.warning("Config/Utils import edilemedi. Simülasyon modunda varsayılanlar kullanılacak.")
    # === ACİL DURUM CONFIG ===
    class CameraConfig:
        DEFAULT_RESOLUTION = (1296, 972); FRAME_BUFFER_SIZE = 10; ENABLE_LENS_CORRECTION = True
        FOV_HORIZONTAL = 130; ENABLE_AUTO_EXPOSURE = True; ENABLE_AUTO_WHITE_BALANCE = True
        CAMERA_MODEL = "OV5647 130deg"; VIDEO_BITRATE = 10000000; VIDEO_FRAMERATE = 30
        MIN_FRAMERATE = 5; MAX_FRAMERATE = 60; DEFAULT_FRAMERATE = 30
        DEFAULT_EXPOSURE_TIME = 10000; DEFAULT_ANALOGUE_GAIN = 1.0
        DEFAULT_BRIGHTNESS = 0.0; DEFAULT_CONTRAST = 1.0
        DEFAULT_SATURATION = 1.0; DEFAULT_SHARPNESS = 1.0
        DEFAULT_AWB_MODE = 'Auto'; DEFAULT_COLOUR_EFFECT = 'None'
        DEFAULT_FLICKER_MODE = 'Off'; DEFAULT_EXPOSURE_MODE = 'Normal'
        DEFAULT_METERING_MODE = 'Centre'
        @staticmethod
        def get_camera_settings(**kwargs): return {"FrameRate": 30}
        @staticmethod
        def validate_framerate(fps, res): return fps
        @staticmethod
        def validate_exposure_time(exp): return exp
        @staticmethod
        def validate_gain(gain): return gain
        @staticmethod
        def validate_brightness(br): return br
        @staticmethod
        def validate_contrast(co): return co
        @staticmethod
        def validate_saturation(sa): return sa
        @staticmethod
        def validate_sharpness(sh): return sh
        AWB_MODES = {'Auto': 0}
        COLOUR_EFFECTS = {'None': (0, 0)}
        FLICKER_MODES = {'Off': 0}
        EXPOSURE_MODES = {'Normal': 0}
        METERING_MODES = {'Centre': 0}
    class MotorConfig:
        H_MOTOR_IN1=6; H_MOTOR_IN2=13; H_MOTOR_IN3=19; H_MOTOR_IN4=26  # ✅ Düzeltildi: free_movement_script.py ile uyumlu
        LIMIT_SWITCH_MIN=None; LIMIT_SWITCH_MAX=None; STEPS_PER_REV = 4076
        MIN_ANGLE = -90.0; MAX_ANGLE = 90.0; BACKLASH_COMPENSATION = 0.5
        INVERT_DIRECTION = False; SETTLE_TIME = 0.05
        STEP_SEQUENCE = [(1,0,0,1),(1,0,0,0),(1,1,0,0),(0,1,0,0),(0,1,1,0),(0,0,1,0),(0,0,1,1),(0,0,0,1)]
        SPEED_PROFILES = {'slow': {'delay': 0.002, 'acceleration': 1.0}, 'normal': {'delay': 0.001, 'acceleration': 1.2}, 'fast': {'delay': 0.0006, 'acceleration': 1.4}}
    class SensorConfig:
        H_TRIG = 23; H_ECHO = 24; MAX_DISTANCE = 4.0; QUEUE_LEN = 5; THRESHOLD_DISTANCE = 0.01
        MIN_VALID_DISTANCE = 2.0; MAX_VALID_DISTANCE = 400.0; MIN_READ_INTERVAL = 0.06; MAX_READ_INTERVAL = 1.0
        READ_ATTEMPTS = 3; READ_DELAY = 0.01; USE_MEDIAN_FILTER = True; CALIBRATION_OFFSET = 0.0
        TEMPERATURE_COMPENSATION = True
        @staticmethod
        def calculate_sound_speed(): return 343.0
    class AppConfig:
        MAX_THREAD_POOL_SIZE = 5; USE_THREAD_POOL = True; CIRCUIT_FAILURE_THRESHOLD = 3
        CIRCUIT_RECOVERY_TIMEOUT = 30; MAX_RETRY_COUNT = 3; RETRY_DELAY = 1.0; LOCK_TIMEOUT = 2.0
    class PerformanceConfig: pass
    class SystemChecks:
        @staticmethod
        def run_all_checks(): return {'system': True}
    class CircuitBreaker:
        def __init__(self, failure_threshold, recovery_timeout): pass
        def call(self, func): return func()
        @property
        def state(self): return "closed"
    class FrameBuffer:
        def __init__(self, size): self.buffer = deque(maxlen=size); self.size=size
        def add_frame(self, frame): self.buffer.append(frame)
        def get_latest(self): return self.buffer[-1] if self.buffer else None
        def clear(self): self.buffer.clear()
    class FisheyeCorrector:
        def load_calibration(self): pass
        def correct_distortion(self, frame, method='fast'): return frame
    def profile_performance(func): return func
    class PerformanceMonitor:
        def record(self, metric, value): pass
        def get_stats(self, metric): return {}


# Logger
logger = logging.getLogger(__name__)

# Donanım kütüphaneleri
try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False
    logger.warning("picamera2 kütüphanesi bulunamadı. OV5647 simülasyon modunda.")
    class Picamera2:
        def __init__(self): logger.warning("Picamera2 simüle ediliyor.")
        def create_video_configuration(self, main, controls): return {}
        def configure(self, config): pass
        def set_controls(self, controls): pass
        def start(self): pass
        def capture_array(self): return None
        def start_recording(self, encoder, filepath, metadata): pass
        def stop_recording(self): pass
        def stop(self): pass
        def close(self): pass
    class H264Encoder:
        def __init__(self, bitrate): pass

try:
    from gpiozero import OutputDevice, DistanceSensor, Button
    warnings.filterwarnings('ignore', category=Warning, module='gpiozero')
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("GPIO kütüphaneleri bulunamadı. Motor/Sensör simülasyon modunda.")
    class DistanceSensor:
        def __init__(self, echo, trigger, max_distance, queue_len, threshold_distance):
            logger.warning("DistanceSensor simüle ediliyor.")
            self._distance = 0.5
        @property
        def distance(self):
            self._distance = np.random.uniform(0.1, 3.0)
            return self._distance
        def close(self): pass
    class Button:
        def __init__(self, pin): logger.warning(f"Button (Pin {pin}) simüle ediliyor.")
        @property
        def is_pressed(self): return False
    class OutputDevice:
        def __init__(self, pin): self.pin = pin; self._value = 0
        def on(self): self._value = 1
        def off(self): self._value = 0
        def close(self): pass
        @property
        def value(self): return self._value
        @value.setter
        def value(self, val): self._value = 1 if val else 0


# ============================================================================
# MOTOR KOMUT QUEUE SİSTEMİ
# ============================================================================

class MotorCommandQueue:
    """Öncelikli motor komut kuyruğu"""
    def __init__(self):
        self.queue = queue.PriorityQueue()
        self.processing = False
        self.lock = threading.Lock()

    def add_command(self, angle: float, priority: int = 5, callback: Callable = None):
        command = {'angle': angle, 'callback': callback, 'timestamp': time.time()}
        self.queue.put((priority, time.time(), command))

    def get_next(self) -> Optional[Dict]:
        try:
            if not self.queue.empty():
                _, _, command = self.queue.get_nowait()
                return command
        except queue.Empty:
            pass
        return None

    def clear(self):
        with self.lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break

    def size(self) -> int:
        return self.queue.qsize()


# ============================================================================
# ADAPTIVE SENSOR READER
# ============================================================================

class AdaptiveSensorReader:
    """Adaptif hızda sensör okuyucu"""
    def __init__(self, sensor):
        self.sensor = sensor
        self.stable_count = 0
        self.last_reading = None
        self.read_interval = SensorConfig.MIN_READ_INTERVAL
        self.variance_threshold = 2.0

    def get_adaptive_interval(self, new_reading: float) -> float:
        if self.last_reading is None:
            self.last_reading = new_reading
            return self.read_interval

        change = abs(new_reading - self.last_reading)
        if change < self.variance_threshold:
            self.stable_count += 1
            if self.stable_count > 10:
                self.read_interval = min(SensorConfig.MAX_READ_INTERVAL, self.read_interval * 1.1)
        else:
            self.stable_count = 0
            self.read_interval = SensorConfig.MIN_READ_INTERVAL

        self.last_reading = new_reading
        return self.read_interval


# ============================================================================
# ANA DONANIM YÖNETİCİSİ
# ============================================================================

class HardwareManager:
    """
    Geliştirilmiş donanım yönetimi (v3.17 TAM KONTROL):
    - v3.16 + Savunmacı frame yakalama eklendi
    """

    # Versiyon bilgisi
    VERSION = "3.17-ULTIMATE-DEFENSIVE" # GÜNCELLENDİ

    def __init__(self):
        # Donanım objeleri
        self.camera: Optional[Picamera2] = None
        self.motor_devices: Optional[Tuple] = None
        self.sensor: Optional[DistanceSensor] = None
        self.limit_switches: Dict[str, Optional[Button]] = {'min': None, 'max': None}

        # OV5647 lens düzeltici
        self.fisheye_corrector = FisheyeCorrector()
        self.fisheye_corrector.load_calibration()

        # Frame buffer
        self.frame_buffer = FrameBuffer(size=CameraConfig.FRAME_BUFFER_SIZE)

        # Motor yönetimi
        self.motor_ctx = {
            'current_angle': 0.0, 'sequence_index': 0, 'total_steps': 0,
            'is_moving': False, 'last_direction': None, 'target_angle': 0.0,
            'cancel_movement': False, 'speed_profile': 'normal'
        }
        self.motor_command_queue = MotorCommandQueue()

        # Video kaydı
        self.is_recording = False
        self.video_encoder = None
        self.recording_start_time = None

        # Thread yönetimi
        self._locks = {
            'camera': threading.RLock(),
            'motor': threading.RLock(),
            'sensor': threading.RLock(),
            'video': threading.RLock()
        }

        # Thread pool executor
        self.executor = ThreadPoolExecutor(
            max_workers=AppConfig.MAX_THREAD_POOL_SIZE
        ) if AppConfig.USE_THREAD_POOL else None

        # Başlatma durumu
        self._initialized = {'camera': False, 'motor': False, 'sensor': False}

        # === YENİ (v3.16) Mevcut Kamera Ayarları Cache ===
        self._camera_settings_cache = {
            'resolution': CameraConfig.DEFAULT_RESOLUTION,
            'framerate': CameraConfig.DEFAULT_FRAMERATE,
            'ae_enable': CameraConfig.ENABLE_AUTO_EXPOSURE,
            'awb_enable': CameraConfig.ENABLE_AUTO_WHITE_BALANCE,
            'exposure_time': CameraConfig.DEFAULT_EXPOSURE_TIME,
            'analogue_gain': CameraConfig.DEFAULT_ANALOGUE_GAIN,
            'brightness': CameraConfig.DEFAULT_BRIGHTNESS,
            'contrast': CameraConfig.DEFAULT_CONTRAST,
            'saturation': CameraConfig.DEFAULT_SATURATION,
            'sharpness': CameraConfig.DEFAULT_SHARPNESS,
            'awb_mode': CameraConfig.DEFAULT_AWB_MODE,
            'colour_effect': CameraConfig.DEFAULT_COLOUR_EFFECT,
            'flicker_mode': CameraConfig.DEFAULT_FLICKER_MODE,
            'exposure_mode': CameraConfig.DEFAULT_EXPOSURE_MODE,
            'metering_mode': CameraConfig.DEFAULT_METERING_MODE,
        }
        self._settings_hash = None
        # === SON ===

        # Circuit breakers
        self.circuit_breakers = {
            'camera': CircuitBreaker(
                AppConfig.CIRCUIT_FAILURE_THRESHOLD,
                AppConfig.CIRCUIT_RECOVERY_TIMEOUT
            ),
            'motor': CircuitBreaker(3, 30),
            'sensor': CircuitBreaker(5, 20)
        }

        # Performans metrikleri
        self.performance_monitor = PerformanceMonitor()
        self.metrics = {
            'camera_frames': 0, 'motor_moves': 0, 'sensor_reads': 0,
            'errors': 0, 'start_time': datetime.now()
        }

        # Sensör okuma
        self.sensor_thread: Optional[threading.Thread] = None
        self.sensor_enabled = False
        self.sensor_running = False
        self.current_distance = None
        self.adaptive_sensor = None

        # Motor thread
        self.motor_thread: Optional[threading.Thread] = None
        self.motor_queue_running = False

        logger.info("=" * 60)
        logger.info(f"HARDWARE MANAGER BAŞLATILDI ({self.VERSION})")
        logger.info(f"OV5647 130° Kamera: {'Var' if CAMERA_AVAILABLE else 'Simülasyon'}")
        logger.info(f"GPIO: {'Aktif' if GPIO_AVAILABLE else 'Simülasyon'}")
        logger.info("=" * 60)

    # ========================================================================
    # KAMERA YÖNETİMİ (TAM KONTROL)
    # ========================================================================

    def _calculate_settings_hash(self, **settings) -> str:
        """Ayarlar hash'i hesapla (değişiklik tespiti için)"""
        settings_str = json.dumps(settings, sort_keys=True)
        return hashlib.md5(settings_str.encode()).hexdigest()

    @profile_performance
    def initialize_camera(self, retry: bool = True) -> bool:
        """OV5647 130° kamerayı başlat"""
        if not CAMERA_AVAILABLE:
            logger.warning("OV5647 simülasyon modunda (kamera takılı değil)")
            self._initialized['camera'] = False
            return False

        def _init_camera():
            if self.camera:
                self.cleanup_camera()

            logger.info("OV5647 130° kamera başlatılıyor...")
            self.camera = Picamera2()

            # Başlangıç ayarlarını cache'den al
            initial_settings = self._camera_settings_cache.copy()

            # libcamera kontrolleri oluştur
            try:
                camera_controls = CameraConfig.get_camera_settings(**initial_settings)
            except TypeError as e:
                logger.error(f"Config hatası: {e}. Varsayılan ayarlar kullanılıyor.")
                camera_controls = CameraConfig.get_camera_settings()

            config = self.camera.create_video_configuration(
                main={
                    "size": initial_settings['resolution'],
                    "format": "RGB888"
                },
                controls=camera_controls
            )
            self.camera.configure(config)
            self.camera.start()

            # Hash hesapla
            self._settings_hash = self._calculate_settings_hash(**initial_settings)

            time.sleep(2)

            # Test frame
            test_frame = self.camera.capture_array()
            if test_frame is None or test_frame.size == 0:
                raise Exception("Test frame alınamadı")

            self.frame_buffer.add_frame(test_frame)
            self._initialized['camera'] = True

            logger.info("✓ OV5647 130° kamera başarıyla başlatıldı")
            logger.info(f"  Çözünürlük: {initial_settings['resolution']}")
            logger.info(f"  FPS: {initial_settings['framerate']}")
            logger.info(f"  AE/AWB: {initial_settings['ae_enable']}/{initial_settings['awb_enable']}")
            logger.info(f"  FOV: {CameraConfig.FOV_HORIZONTAL}° yatay")

            return True

        try:
            if retry:
                for attempt in range(AppConfig.MAX_RETRY_COUNT):
                    try:
                        return self.circuit_breakers['camera'].call(_init_camera)
                    except Exception as e:
                        logger.error(f"Kamera başlatma hatası (Deneme {attempt + 1}): {e}")
                        if attempt < AppConfig.MAX_RETRY_COUNT - 1:
                            time.sleep(AppConfig.RETRY_DELAY * (2 ** attempt))
            else:
                return self.circuit_breakers['camera'].call(_init_camera)
        except Exception as e:
            logger.error(f"Kamera başlatılamadı: {e}")
            self.metrics['errors'] += 1

        return False

    @profile_performance
    def capture_frame(self,
                      # Temel ayarlar
                      resolution: Optional[Tuple[int, int]] = None,
                      framerate: Optional[float] = None,
                      apply_lens_correction: bool = True,

                      # Otomatik kontroller
                      ae_enable: Optional[bool] = None,
                      awb_enable: Optional[bool] = None,

                      # YENİ (v3.16) Manuel Pozlama
                      exposure_time: Optional[int] = None,
                      analogue_gain: Optional[float] = None,

                      # YENİ (v3.16) Görüntü İyileştirme
                      brightness: Optional[float] = None,
                      contrast: Optional[float] = None,
                      saturation: Optional[float] = None,
                      sharpness: Optional[float] = None,

                      # YENİ (v3.16) Gelişmiş Modlar
                      awb_mode: Optional[str] = None,
                      colour_effect: Optional[str] = None,
                      flicker_mode: Optional[str] = None,
                      exposure_mode: Optional[str] = None,
                      metering_mode: Optional[str] = None,

                      ) -> Optional[np.ndarray]:
        """
        (v3.17 TAM KONTROL + SAVUNMACI)
        OV5647'den görüntü al - TÜM ayarlar dinamik olarak değiştirilebilir

        Returns:
            numpy.ndarray or None
        """

        # Varsayılan değerler (cache'den)
        cache = self._camera_settings_cache

        new_settings = {
            'resolution': resolution or cache['resolution'],
            'framerate': framerate or cache['framerate'],
            'ae_enable': ae_enable if ae_enable is not None else cache['ae_enable'],
            'awb_enable': awb_enable if awb_enable is not None else cache['awb_enable'],
            'exposure_time': exposure_time or cache['exposure_time'],
            'analogue_gain': analogue_gain or cache['analogue_gain'],
            'brightness': brightness if brightness is not None else cache['brightness'],
            'contrast': contrast if contrast is not None else cache['contrast'],
            'saturation': saturation if saturation is not None else cache['saturation'],
            'sharpness': sharpness if sharpness is not None else cache['sharpness'],
            'awb_mode': awb_mode or cache['awb_mode'],
            'colour_effect': colour_effect or cache['colour_effect'],
            'flicker_mode': flicker_mode or cache['flicker_mode'],
            'exposure_mode': exposure_mode or cache['exposure_mode'],
            'metering_mode': metering_mode or cache['metering_mode'],
        }

        # Validasyonlar
        new_settings['framerate'] = CameraConfig.validate_framerate(
            new_settings['framerate'],
            new_settings['resolution']
        )
        new_settings['exposure_time'] = CameraConfig.validate_exposure_time(new_settings['exposure_time'])
        new_settings['analogue_gain'] = CameraConfig.validate_gain(new_settings['analogue_gain'])
        new_settings['brightness'] = CameraConfig.validate_brightness(new_settings['brightness'])
        new_settings['contrast'] = CameraConfig.validate_contrast(new_settings['contrast'])
        new_settings['saturation'] = CameraConfig.validate_saturation(new_settings['saturation'])
        new_settings['sharpness'] = CameraConfig.validate_sharpness(new_settings['sharpness'])

        # Simülasyon modu
        if not self._initialized['camera'] or self.camera is None:
            return self._generate_test_frame(**new_settings)

        # Kilit al
        if not self._locks['camera'].acquire(timeout=AppConfig.LOCK_TIMEOUT):
            logger.warning("Kamera kilidi alınamadı (timeout)")
            return self.frame_buffer.get_latest()

        try:
            # Hash hesapla ve değişiklik kontrolü
            new_hash = self._calculate_settings_hash(**new_settings)

            # *** YENİ: v3.17 DEĞİŞİKLİĞİ ***
            needs_retry = False # Flag

            if new_hash != self._settings_hash:
                logger.info("🔄 Kamera ayarları değişti, yeniden yapılandırılıyor...")
                self._reconfigure_camera(new_settings)
                self._settings_hash = new_hash
                self._camera_settings_cache = new_settings.copy()
                needs_retry = True # Ayar değişti, ilk kare riskli olabilir
            # *** DEĞİŞİKLİK SONU ***

            # Frame yakala
            frame = self.camera.capture_array()

            # *** YENİ: v3.17 DEĞİŞİKLİĞİ (SAVUNMACI YAKALAMA) ***
            if (frame is None or frame.size == 0) and needs_retry:
                logger.warning("Yeniden yapılandırma sonrası ilk kare başarısız. 0.5sn beklenip tekrar denenecek...")
                time.sleep(0.5)
                frame = self.camera.capture_array() # Tekrar dene
            # *** DEĞİŞİKLİK SONU ***

            if frame is not None and frame.size > 0:
                # Lens düzeltme
                if apply_lens_correction and CameraConfig.ENABLE_LENS_CORRECTION:
                    frame = self.fisheye_corrector.correct_distortion(frame, method='fast')

                self.metrics['camera_frames'] += 1
                self.frame_buffer.add_frame(frame)
                self.performance_monitor.record('capture_frame', time.time())
                return frame
            else:
                logger.warning("Frame alınamadı, test frame döndürülüyor")
                return self._generate_test_frame(**new_settings)

        except Exception as e:
            logger.error(f"Görüntü alma hatası: {e}", exc_info=True)
            self.metrics['errors'] += 1
            return self.frame_buffer.get_latest()

        finally:
            self._locks['camera'].release()

    def _reconfigure_camera(self, settings: Dict[str, Any]):
        """
        Kamerayı yeni ayarlarla yeniden yapılandır

        Stratejik karar:
        - Çözünürlük veya FPS değişirse → Tam yeniden başlatma
        - Sadece image parameters değişirse → set_controls() kullan
        """
        try:
            # "Ağır" değişiklikler (stream yeniden başlatma gerektirir)
            heavy_changes = (
                    settings['resolution'] != self._camera_settings_cache['resolution'] or
                    settings['framerate'] != self._camera_settings_cache['framerate']
            )

            if heavy_changes:
                logger.info(f"🔄 Tam yeniden yapılandırma: {settings['resolution']} @ {settings['framerate']}fps")

                self.camera.stop()

                # Yeni kontroller
                try:
                    camera_controls = CameraConfig.get_camera_settings(**settings)
                except TypeError as e:
                    logger.warning(f"Config uyumsuzluğu: {e}. Temel ayarlar kullanılıyor.")
                    camera_controls = {
                        "FrameRate": settings['framerate'],
                        "AeEnable": settings['ae_enable'],
                        "AwbEnable": settings['awb_enable'],
                    }

                new_config = self.camera.create_video_configuration(
                    main={"size": settings['resolution'], "format": "RGB888"},
                    controls=camera_controls
                )

                self.camera.configure(new_config)
                self.camera.start()
                time.sleep(1.0)  # Stabilizasyon

            else:
                # "Hafif" değişiklikler (sadece kontroller)
                logger.info("⚡ Hafif güncelleme: set_controls() kullanılıyor")

                try:
                    controls_update = CameraConfig.get_camera_settings(**settings)
                    self.camera.set_controls(controls_update)
                    time.sleep(0.3)  # Kısa bekleme
                except TypeError as e:
                    logger.warning(f"set_controls hatası: {e}")
                    # Fallback: Temel kontroller
                    self.camera.set_controls({
                        "AeEnable": settings['ae_enable'],
                        "AwbEnable": settings['awb_enable'],
                        "Brightness": settings['brightness'],
                        "Contrast": settings['contrast'],
                        "Saturation": settings['saturation'],
                        "Sharpness": settings['sharpness'],
                    })

            logger.info("✓ Kamera yeniden yapılandırıldı")

        except Exception as e:
            logger.error(f"Yeniden yapılandırma hatası: {e}", exc_info=True)
            raise

    def _generate_test_frame(self, **settings) -> Optional[np.ndarray]:
        """
        Simülasyon frame'i (tüm ayarlar görünür)
        """
        try:
            resolution = settings.get('resolution', (1296, 972))
            width, height = resolution

            # Gradient arka plan
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            for i in range(height):
                frame[i, :] = [
                    50 + int(i / height * 100),
                    100 + int(i / height * 80),
                    150 - int(i / height * 100)
                ]

            # Çapraz çizgiler
            center_x, center_y = width // 2, height // 2
            cv2.line(frame, (center_x, 0), (center_x, height), (0, 255, 0), 2)
            cv2.line(frame, (0, center_y), (width, center_y), (0, 255, 0), 2)

            # FOV işaretleri
            fov_angles = [-65, -45, -30, -15, 0, 15, 30, 45, 65]
            for angle in fov_angles:
                x = int(center_x + (width / 2) * np.tan(np.radians(angle)) / np.tan(np.radians(65)))
                if 0 <= x < width:
                    cv2.line(frame, (x, 0), (x, height), (255, 255, 0), 1)
                    cv2.putText(
                        frame, f"{angle}°", (x - 15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1
                    )

            # === Ayar Bilgileri ===
            info_texts = [
                "OV5647 130° SİMÜLASYON MODU",
                f"Çözünürlük: {width}x{height}",
                f"FPS: {settings.get('framerate', 30):.1f}",
                f"FOV: {CameraConfig.FOV_HORIZONTAL}° yatay",
                f"AE: {'AKTİF' if settings.get('ae_enable') else 'KAPALI'}",
                f"AWB: {settings.get('awb_mode', 'Auto')}",
                f"Pozlama: {settings.get('exposure_time', 0)/1000:.1f}ms" if not settings.get('ae_enable') else "Pozlama: OTO",
                f"ISO: {settings.get('analogue_gain', 1.0):.1f}x" if not settings.get('ae_enable') else "ISO: OTO",
                f"Parlaklık: {settings.get('brightness', 0.0):.1f}",
                f"Kontrast: {settings.get('contrast', 1.0):.1f}",
                f"Doygunluk: {settings.get('saturation', 1.0):.1f}",
                f"Keskinlik: {settings.get('sharpness', 1.0):.1f}",
                f"Zaman: {datetime.now().strftime('%H:%M:%S')}",
                "⚠️ Kamera takılı değil!"
            ]

            y_pos = 80
            for text in info_texts:
                color = (0, 255, 255) if "takılı değil" in text else (255, 255, 255)
                cv2.putText(
                    frame, text, (30, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
                )
                y_pos += 25

            # Hareketli obje
            angle = (time.time() * 50) % 360
            radius = min(width, height) // 4
            obj_x = int(center_x + radius * np.cos(np.radians(angle)))
            obj_y = int(center_y + radius * np.sin(np.radians(angle)))
            cv2.circle(frame, (obj_x, obj_y), 30, (0, 0, 255), -1)

            # Motor ve sensör durumu
            motor_angle = self.get_motor_angle()
            distance = self.current_distance or 0

            status_text = [
                f"Motor: {motor_angle:.1f}°",
                f"Sensör: {distance:.1f}cm" if distance > 0 else "Sensör: Kapalı"
            ]

            y_pos = height - 60
            for text in status_text:
                cv2.putText(
                    frame, text, (30, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1
                )
                y_pos += 25

            return frame

        except Exception as e:
            logger.error(f"Test frame oluşturma hatası: {e}")
            return np.zeros((480, 640, 3), dtype=np.uint8)

    # ========================================================================
    # VİDEO FONKSİYONLARI (v3.15 ile aynı)
    # ========================================================================

    def start_recording(self, filepath: str) -> Tuple[bool, str]:
        """Video kaydını başlat"""
        if not self._initialized['camera'] or self.camera is None:
            return False, "Kamera kullanılamıyor"

        with self._locks['video']:
            try:
                if self.is_recording:
                    return False, "Zaten kayıt yapılıyor"

                self.video_encoder = H264Encoder(bitrate=CameraConfig.VIDEO_BITRATE)

                # Mevcut ayarları metadata'ya ekle
                cache = self._camera_settings_cache
                metadata = {
                    'camera': CameraConfig.CAMERA_MODEL,
                    'fov': f"{CameraConfig.FOV_HORIZONTAL}°",
                    'resolution': f"{cache['resolution'][0]}x{cache['resolution'][1]}",
                    'framerate': cache['framerate'],
                    'ae_enable': cache['ae_enable'],
                    'awb_enable': cache['awb_enable'],
                    'awb_mode': cache['awb_mode'],
                    'date': datetime.now().isoformat()
                }

                self.camera.start_recording(self.video_encoder, filepath, metadata=metadata)
                self.is_recording = True
                self.recording_start_time = time.time()

                logger.info(f"✓ Video kaydı başlatıldı: {filepath}")
                return True, "Kayıt başlatıldı"

            except Exception as e:
                logger.error(f"Video başlatma hatası: {e}", exc_info=True)
                self.metrics['errors'] += 1
                self.is_recording = False
                self.video_encoder = None
                return False, str(e)

    def stop_recording(self) -> Tuple[bool, str]:
        """Video kaydını durdur"""
        if not self._initialized['camera'] or self.camera is None:
            return False, "Kamera kullanılamıyor"

        with self._locks['video']:
            try:
                if not self.is_recording:
                    return False, "Kayıt yapılmıyor"

                self.camera.stop_recording()
                duration = time.time() - self.recording_start_time if self.recording_start_time else 0

                self.is_recording = False
                self.video_encoder = None
                self.recording_start_time = None

                logger.info(f"✓ Video kaydı durduruldu. Süre: {duration:.1f} saniye")
                return True, f"Kayıt durduruldu ({duration:.1f} saniye)"

            except Exception as e:
                logger.error(f"Video durdurma hatası: {e}", exc_info=True)
                self.metrics['errors'] += 1
                return False, str(e)

    def cleanup_camera(self):
        """Kamerayı temizle"""
        try:
            if self.camera:
                if self.is_recording:
                    self.stop_recording()
                self.camera.stop()
                self.camera.close()
                self.camera = None
                self._initialized['camera'] = False
                self.frame_buffer.clear()
                self._settings_hash = None
                logger.info("✓ Kamera temizlendi")
        except Exception as e:
            logger.error(f"Kamera temizleme hatası: {e}")
            self.metrics['errors'] += 1

    # ========================================================================
    # MOTOR YÖNETİMİ (v3.15 ile aynı - değişiklik yok)
    # ========================================================================

    @profile_performance
    def initialize_motor(self, retry: bool = True) -> bool:
        """
        Step motoru başlat
        ❌ GPIO yoksa HATA (Simülasyon YOK)
        """

        # ✅ SADECE BU BÖLÜM DEĞİŞTİ
        if not GPIO_AVAILABLE:
            logger.error("❌ GPIO kütüphaneleri yok!")
            logger.error("   Yüklemek için: sudo apt install -y python3-gpiozero")
            self._initialized['motor'] = False
            return False  # ✅ Simülasyon yok, direk False

        # ✅ BURADAN SONRASI AYNI (Değiştirme!)
        def _init_motor():
            if self.motor_devices:
                self.cleanup_motor()

            logger.info("🔧 Step motor başlatılıyor...")
            logger.info(f"   GPIO Pinler: IN1={MotorConfig.H_MOTOR_IN1}, IN2={MotorConfig.H_MOTOR_IN2}, IN3={MotorConfig.H_MOTOR_IN3}, IN4={MotorConfig.H_MOTOR_IN4}")

            self.motor_devices = (
                OutputDevice(MotorConfig.H_MOTOR_IN1),
                OutputDevice(MotorConfig.H_MOTOR_IN2),
                OutputDevice(MotorConfig.H_MOTOR_IN3),
                OutputDevice(MotorConfig.H_MOTOR_IN4)
            )

            if MotorConfig.LIMIT_SWITCH_MIN:
                self.limit_switches['min'] = Button(MotorConfig.LIMIT_SWITCH_MIN)
                logger.info(f"   Min limit switch: GPIO{MotorConfig.LIMIT_SWITCH_MIN}")

            if MotorConfig.LIMIT_SWITCH_MAX:
                self.limit_switches['max'] = Button(MotorConfig.LIMIT_SWITCH_MAX)
                logger.info(f"   Max limit switch: GPIO{MotorConfig.LIMIT_SWITCH_MAX}")

            self.motor_ctx = {
                'current_angle': 0.0,
                'sequence_index': 0,
                'total_steps': 0,
                'is_moving': False,
                'last_direction': None,
                'target_angle': 0.0,
                'cancel_movement': False,
                'speed_profile': 'normal',
                'backlash_compensation': MotorConfig.BACKLASH_COMPENSATION
            }

            self._stop_motor_internal()

            # Motor thread başlat
            self.motor_queue_running = True
            self.motor_thread = threading.Thread(
                target=self._motor_command_processor,
                name="MotorCommandProcessor",
                daemon=True
            )
            self.motor_thread.start()

            self._initialized['motor'] = True
            logger.info("✅ Step motor başarıyla başlatıldı")
            logger.info(f"   Adım/Tur: {MotorConfig.STEPS_PER_REV}")
            logger.info(f"   Açı Aralığı: {MotorConfig.MIN_ANGLE}° - {MotorConfig.MAX_ANGLE}°")

            return True

        try:
            return self.circuit_breakers['motor'].call(_init_motor)
        except Exception as e:
            logger.error(f"Motor başlatma hatası: {e}")
            self.metrics['errors'] += 1
            return False

    def _motor_command_processor(self):
        """Motor komutlarını işleyen thread"""
        logger.info("Motor komut işleyici başladı")

        while self.motor_queue_running:
            try:
                command = self.motor_command_queue.get_next()
                if command:
                    target_angle = command['angle']
                    callback = command.get('callback')

                    # ASENKRON ÇAĞRI: Kilit motor thread'i tarafından alınır
                    success = self._move_to_angle_internal(target_angle, from_queue=True)

                    if callback:
                        try:
                            callback(success, target_angle)
                        except Exception as e:
                            logger.error(f"Motor callback hatası: {e}")

                time.sleep(0.01) # CPU kullanımı için kısa bir bekleme
            except Exception as e:
                logger.error(f"Motor komut işleme hatası: {e}")
                time.sleep(0.1)

        logger.info("Motor komut işleyici durdu")

    @profile_performance
    def move_to_angle(self,
                      target_angle: float,
                      speed_profile: str = 'normal',
                      priority: int = 5,
                      force: bool = False,
                      callback: Callable = None,
                      wait: bool = False, # ✅ VARSAYILAN DEĞİŞTİ: Artık False
                      timeout: float = 10.0) -> bool:
        """
        Motoru belirtilen açıya götür (v3.17 ASENKRON ODAKLI)

        Args:
            wait: Hareket bitene kadar bekle (Dash için False olmalı)
        """
        target_angle = self._validate_angle(target_angle)

        # Motor başlatılmamışsa
        if not self._initialized['motor']:
            logger.error("❌ Motor başlatılmamış! initialize_motor() çağırın.")
            return False

        # Thread kontrolü
        if not self.motor_queue_running or not self.motor_thread or not self.motor_thread.is_alive():
            logger.error("❌ Motor thread/queue çalışmıyor!")
            # Yeniden başlatmayı deneyebiliriz
            # self.initialize_motor() # Dikkatli kullanılmalı
            return False

        logger.info(f"📡 move_to_angle() çağrıldı: {target_angle}° (speed={speed_profile}, force={force}, wait={wait})")

        # Force mode
        if force:
            logger.info("🛑 Force mode: Mevcut komutlar iptal ediliyor...")
            self.motor_ctx['cancel_movement'] = True
            self.motor_command_queue.clear()
            # Kısa bir bekleme, çalışan thread'in iptali fark etmesi için
            time.sleep(0.05)

        self.motor_ctx['speed_profile'] = speed_profile

        # Komutu kuyruğa ekle
        self.motor_command_queue.add_command(target_angle, priority, callback)
        logger.info(f"✅ Komut kuyruğa eklendi. Queue boyutu: {self.motor_command_queue.size()}")

        # ✅ SENKRON BEKLEME (Sadece gerekliyse)
        if wait and not callback:
            logger.info(f"⏳ Senkron bekleme başladı (timeout={timeout}s)...")
            start_time = time.time()
            last_log = 0

            while time.time() - start_time < timeout:
                current = self.motor_ctx['current_angle']
                is_moving = self.motor_ctx['is_moving']
                queue_size = self.motor_command_queue.size()
                diff = abs(current - target_angle)

                # Hedefe ulaştı mı? (Hareket bitti VE kuyruk boş VE hedefe yakın)
                if not is_moving and queue_size == 0 and diff < 0.5:
                    elapsed = time.time() - start_time
                    logger.info(f"✅ Motor hedefte: {current:.1f}° (Süre: {elapsed:.2f}s)")
                    return True

                # Her saniye log
                now = time.time()
                if now - last_log >= 1.0:
                    logger.info(f"   ⏳ Bekliyor... Açı: {current:.1f}° | Hedef: {target_angle:.1f}° | Hareket: {is_moving} | Kuyruk: {queue_size}")
                    last_log = now

                time.sleep(0.05)

            # Timeout
            logger.error(f"⚠️ Motor hareketi TIMEOUT! Son açı: {self.motor_ctx['current_angle']:.1f}°")
            return False

        # Asenkron mod (wait=False)
        return True

    def _move_to_angle_internal(self, target_angle: float, from_queue: bool = False) -> bool:
        """Motor hareketi (internal)"""
        # Sadece motor thread'i (from_queue=True) bu kilidi almalı
        if not from_queue:
            logger.warning("move_to_angle_internal doğrudan çağrılmamalı!")
            return False

        if not self._locks['motor'].acquire(timeout=AppConfig.LOCK_TIMEOUT):
            logger.warning("Motor kilidi alınamadı (thread içinde)")
            return False

        try:
            self.motor_ctx['is_moving'] = True
            self.motor_ctx['target_angle'] = target_angle
            self.motor_ctx['cancel_movement'] = False

            current = self.motor_ctx['current_angle']
            deg_per_step = 360.0 / MotorConfig.STEPS_PER_REV
            angle_diff = target_angle - current

            # Backlash compensation
            if self.motor_ctx['last_direction'] is not None:
                new_direction = (angle_diff > 0)
                if new_direction != self.motor_ctx['last_direction']:
                    compensation = self.motor_ctx.get('backlash_compensation', MotorConfig.BACKLASH_COMPENSATION)
                    if new_direction:
                        angle_diff += compensation
                    else:
                        angle_diff -= compensation

            if abs(angle_diff) < deg_per_step / 2:
                logger.debug(f"Motor zaten hedefte ({target_angle:.1f}°)")
                self.motor_ctx['is_moving'] = False
                return True

            logger.info(f"🔄 Motor: {current:.1f}° → {target_angle:.1f}° (Δ={angle_diff:.1f}°)")

            num_steps = round(abs(angle_diff) / deg_per_step)
            direction = (angle_diff > 0)

            profile = MotorConfig.SPEED_PROFILES.get(
                self.motor_ctx['speed_profile'],
                MotorConfig.SPEED_PROFILES['normal']
            )

            step_delay = profile['delay']
            acceleration = profile['acceleration']

            success = self._step_motor_with_acceleration(
                num_steps, direction, step_delay, deg_per_step, acceleration
            )

            if success:
                self.motor_ctx['current_angle'] = target_angle
                self.motor_ctx['last_direction'] = direction
                self.metrics['motor_moves'] += 1
                time.sleep(MotorConfig.SETTLE_TIME)
                logger.info(f"✓ Motor hedefte: {target_angle:.1f}°")
                self.performance_monitor.record('motor_move', angle_diff)
            elif self.motor_ctx['cancel_movement']:
                logger.info(f"⚠️ Motor hareketi iptal edildi ({self.motor_ctx['current_angle']:.1f}°)")
            else:
                logger.error("Motor hareketi başarısız")

            return success

        except Exception as e:
            logger.error(f"Motor hareket hatası: {e}", exc_info=True)
            self.metrics['errors'] += 1
            return False

        finally:
            self.motor_ctx['is_moving'] = False
            self._stop_motor_internal() # Her hareketten sonra pinleri kapat
            self._locks['motor'].release()

    def _step_motor_with_acceleration(self, num_steps: int, direction: bool,
                                      base_delay: float, deg_per_step: float,
                                      acceleration: float) -> bool:
        """Hızlanma/yavaşlama profili ile motor hareketi"""
        acceleration = min(acceleration, 1.3)
        step_increment = 1 if direction else -1

        if MotorConfig.INVERT_DIRECTION:
            step_increment *= -1

        angle_increment = deg_per_step * (1 if direction else -1)

        accel_steps = min(100, num_steps // 4)
        decel_steps = accel_steps
        current_delay = base_delay * 3

        for step in range(num_steps):
            if self.motor_ctx['cancel_movement']:
                logger.debug(f"Hareket iptal edildi (Adım {step}/{num_steps})")
                self._stop_motor_internal()
                return False

            if self._check_limits(direction):
                logger.warning(f"⚠️ Limit switch tetiklendi!")
                self._stop_motor_internal()
                return False

            # Hızlanma/yavaşlama
            if step < accel_steps:
                progress = step / accel_steps
                current_delay = base_delay * (3 - 2 * progress * acceleration)
            elif step >= num_steps - decel_steps:
                progress = (num_steps - step) / decel_steps
                current_delay = base_delay * (3 - 2 * progress * acceleration)
            else:
                current_delay = base_delay

            # Step
            idx = self.motor_ctx['sequence_index']
            idx = (idx + step_increment) % len(MotorConfig.STEP_SEQUENCE)
            self.motor_ctx['sequence_index'] = idx

            self._set_motor_pins(*MotorConfig.STEP_SEQUENCE[idx])

            self.motor_ctx['current_angle'] += angle_increment
            self.motor_ctx['total_steps'] += 1

            current_delay = max(0.0001, current_delay)
            time.sleep(current_delay)

            if step > 0 and step % 200 == 0:
                logger.debug(f"  Motor: {step}/{num_steps} adım | {self.motor_ctx['current_angle']:.1f}°")

        self._stop_motor_internal()
        logger.debug(f"✓ {num_steps} adım tamamlandı")
        return True

    def _validate_angle(self, angle: float) -> float:
        """Açıyı sınırlar içinde tut"""
        return max(MotorConfig.MIN_ANGLE, min(MotorConfig.MAX_ANGLE, angle))

    def _check_limits(self, direction_positive: bool) -> bool:
        """Limit switch kontrolü"""
        try:
            if direction_positive and self.limit_switches['max']:
                if self.limit_switches['max'].is_pressed:
                    return True
            elif not direction_positive and self.limit_switches['min']:
                if self.limit_switches['min'].is_pressed:
                    return True
        except Exception as e:
            logger.warning(f"Limit switch okuma hatası: {e}")
        return False

    def _set_motor_pins(self, pin1: int, pin2: int, pin3: int, pin4: int):
        """Motor pinlerini ayarla"""
        if self.motor_devices:
            self.motor_devices[0].value = bool(pin1)
            self.motor_devices[1].value = bool(pin2)
            self.motor_devices[2].value = bool(pin3)
            self.motor_devices[3].value = bool(pin4)

    def _stop_motor_internal(self):
        """Motoru durdur (internal)"""
        if self.motor_devices:
            for dev in self.motor_devices:
                dev.off()

    def cancel_movement(self):
        """Mevcut motor hareketini iptal et"""
        if self.motor_ctx['is_moving']:
            logger.info("🛑 Motor hareketi iptal ediliyor...")
            self.motor_ctx['cancel_movement'] = True
        self.motor_command_queue.clear() # Kuyruktakileri de temizle

    def get_motor_angle(self) -> float:
        """Mevcut motor açısını al"""
        return self.motor_ctx['current_angle']

    def calibrate_motor(self):
        """Motor kalibrasyonu (home position)"""
        with self._locks['motor']:
            self.motor_ctx['current_angle'] = 0.0
            self.motor_ctx['sequence_index'] = 0
            self.motor_ctx['total_steps'] = 0

            if self.motor_devices:
                for dev in self.motor_devices:
                    dev.off()

            logger.info("✓ Motor kalibre edildi (0°)")

    def get_motor_info(self) -> Dict[str, Any]:
        """Detaylı motor bilgileri"""
        return {
            'angle': self.motor_ctx['current_angle'],
            'target_angle': self.motor_ctx['target_angle'],
            'is_moving': self.motor_ctx['is_moving'],
            'cancel_movement': self.motor_ctx['cancel_movement'],
            'total_steps': self.motor_ctx['total_steps'],
            'sequence_index': self.motor_ctx['sequence_index'],
            'last_direction': self.motor_ctx['last_direction'],
            'speed_profile': self.motor_ctx['speed_profile'],
            'deg_per_step': 360.0 / MotorConfig.STEPS_PER_REV,
            'queue_size': self.motor_command_queue.size(),
            'queue_running': self.motor_queue_running,
            'thread_alive': self.motor_thread.is_alive() if self.motor_thread else False
        }

    def cleanup_motor(self):
        """Motoru temizle"""
        try:
            self.motor_queue_running = False

            if self.motor_thread and self.motor_thread.is_alive():
                self.motor_thread.join(timeout=2.0)

            if self.motor_devices:
                for dev in self.motor_devices:
                    dev.close()
                self.motor_devices = None

            self._initialized['motor'] = False
            logger.info("✓ Motor temizlendi")
        except Exception as e:
            logger.error(f"Motor temizleme hatası: {e}")
            self.metrics['errors'] += 1

    # ========================================================================
    # SENSÖR YÖNETİMİ (v3.15 ile aynı - değişiklik yok)
    # ========================================================================

    @profile_performance
    def initialize_sensor(self, retry: bool = True) -> bool:
        """Ultrasonik sensörü başlat"""
        if not GPIO_AVAILABLE:
            logger.warning("⚠️ Sensör simülasyon modunda (GPIO yok)")
            self._initialized['sensor'] = False
            return False

        def _init_sensor():
            if self.sensor:
                try:
                    self.sensor.close()
                except:
                    pass
                self.sensor = None

            logger.info("📡 Ultrasonik sensör başlatılıyor...")
            logger.info(f"  TRIG Pin: GPIO{SensorConfig.H_TRIG}")
            logger.info(f"  ECHO Pin: GPIO{SensorConfig.H_ECHO}")

            try:
                self.sensor = DistanceSensor(
                    echo=SensorConfig.H_ECHO,
                    trigger=SensorConfig.H_TRIG,
                    max_distance=SensorConfig.MAX_DISTANCE,
                    queue_len=SensorConfig.QUEUE_LEN,
                    threshold_distance=SensorConfig.THRESHOLD_DISTANCE
                )

                self.adaptive_sensor = AdaptiveSensorReader(self.sensor)

                logger.info("⏳ Sensör stabilizasyonu bekleniyor (2 saniye)...")
                time.sleep(2.0)

                # Test okumaları
                test_success = False
                for test_num in range(5):
                    try:
                        test_reading_m = self.sensor.distance
                        if test_reading_m is not None and test_reading_m > 0:
                            test_cm = test_reading_m * 100
                            if SensorConfig.MIN_VALID_DISTANCE <= test_cm <= SensorConfig.MAX_VALID_DISTANCE:
                                logger.info(f"✅ Test okuması #{test_num + 1}: {test_cm:.1f} cm - BAŞARILI")
                                test_success = True
                                break
                            else:
                                logger.warning(f"⚠️ Test okuması #{test_num + 1}: {test_cm:.1f} cm - ARALIK DIŞI")
                        else:
                            logger.warning(f"⚠️ Test okuması #{test_num + 1}: None")
                    except Exception as e:
                        logger.warning(f"⚠️ Test okuması #{test_num + 1} hatası: {e}")
                    time.sleep(0.5)

                if test_success:
                    self._initialized['sensor'] = True
                    logger.info("✅ Sensör başarıyla başlatıldı")
                    logger.info(f"  Menzil: {SensorConfig.MIN_VALID_DISTANCE}-{SensorConfig.MAX_VALID_DISTANCE} cm")
                    return True
                else:
                    raise Exception("5 test okuması da başarısız oldu")

            except Exception as e:
                logger.error(f"❌ Sensör başlatma hatası: {e}")
                raise

        if retry:
            for attempt in range(3):
                try:
                    return _init_sensor()
                except Exception as e:
                    logger.error(f"❌ Sensör başlatma denemesi {attempt + 1}/3 başarısız: {e}")
                    if attempt < 2:
                        time.sleep(2)
            return False
        else:
            try:
                return _init_sensor()
            except:
                return False

    def start_continuous_sensor_reading(self):
        """Adaptif hızda sürekli sensör okuma"""
        if not self._initialized['sensor']:
            if GPIO_AVAILABLE:
                logger.error("Sensör başlatılmamış!")
                return False
            else:
                # Simülasyon modu
                self.sensor_enabled = True
                self.sensor_running = True
                self.sensor_thread = threading.Thread(
                    target=self._adaptive_sensor_loop,
                    name="AdaptiveSensorThread",
                    daemon=True
                )
                self.sensor_thread.start()
                logger.info("✓ Adaptif sensör okuma (simülasyon) başlatıldı")
                return True

        if self.sensor_running:
            logger.warning("Sensör zaten çalışıyor")
            return True

        self.sensor_enabled = True
        self.sensor_running = True
        self.sensor_thread = threading.Thread(
            target=self._adaptive_sensor_loop,
            name="AdaptiveSensorThread",
            daemon=True
        )
        self.sensor_thread.start()
        logger.info("✓ Adaptif sensör okuma başlatıldı")
        return True

    def _adaptive_sensor_loop(self):
        """Adaptif hızda sensör okuma döngüsü"""
        logger.info("📡 Adaptif sensör thread başladı")

        while self.sensor_running and self.sensor_enabled:
            try:
                if (self._initialized['sensor'] and self.sensor) or not GPIO_AVAILABLE:
                    distance_cm = self._read_distance_internal()

                    if distance_cm is not None:
                        self.current_distance = distance_cm
                        self.metrics['sensor_reads'] += 1

                        if self.adaptive_sensor:
                            interval = self.adaptive_sensor.get_adaptive_interval(distance_cm)
                        else:
                            interval = SensorConfig.MIN_READ_INTERVAL

                        self.performance_monitor.record('sensor_distance', distance_cm)
                        time.sleep(interval)
                    else:
                        time.sleep(SensorConfig.MAX_READ_INTERVAL)
                else:
                    logger.warning("Sensör thread çalışıyor ancak sensör hazır değil.")
                    time.sleep(1.0)
            except Exception as e:
                logger.error(f"Sensör thread hatası: {e}")
                time.sleep(0.5)

        logger.info("📡 Adaptif sensör thread durdu")

    def _read_distance_internal(self) -> Optional[float]:
        """Sensörden mesafe oku (internal, 400cm düzeltmeli)"""
        if not self._initialized['sensor'] and not GPIO_AVAILABLE:
            # Simülasyon
            self.current_distance = np.random.uniform(10, 200)
            return self.current_distance

        try:
            if not self.sensor:
                return None

            readings = []
            for attempt in range(SensorConfig.READ_ATTEMPTS):
                try:
                    dist_m = self.sensor.distance
                    if dist_m is not None and dist_m > 0:
                        readings.append(dist_m)
                        logger.debug(f"  Okuma #{attempt + 1}: {dist_m * 100:.1f} cm")
                    else:
                        logger.debug(f"  Okuma #{attempt + 1}: None/Geçersiz")
                except Exception as e:
                    logger.debug(f"  Okuma #{attempt + 1} hatası: {e}")

                if attempt < SensorConfig.READ_ATTEMPTS - 1:
                    time.sleep(SensorConfig.READ_DELAY)

            if not readings:
                logger.debug("❌ Hiç geçerli okuma yapılamadı")
                return None

            # Median veya ortalama
            if SensorConfig.USE_MEDIAN_FILTER and len(readings) >= 3:
                readings.sort()
                median_dist_m = readings[len(readings) // 2]
                logger.debug(f"📊 Median mesafe: {median_dist_m * 100:.1f} cm")
            else:
                median_dist_m = np.mean(readings)
                logger.debug(f"📊 Ortalama mesafe: {median_dist_m * 100:.1f} cm")

            dist_cm_raw = median_dist_m * 100 + SensorConfig.CALIBRATION_OFFSET

            # Aralık kontrolü
            if not (SensorConfig.MIN_VALID_DISTANCE <= dist_cm_raw <= SensorConfig.MAX_VALID_DISTANCE):
                logger.debug(f"⚠️ Mesafe geçersiz (sınır dışı): {dist_cm_raw:.1f} cm")
                return None

            # Sıcaklık kompanzasyonu
            if SensorConfig.TEMPERATURE_COMPENSATION:
                sound_speed = SensorConfig.calculate_sound_speed()
                correction_factor = sound_speed / 343.0
                dist_cm_corrected = dist_cm_raw * correction_factor

                logger.debug(f"🌡️ Sıcaklık düzeltmesi: {dist_cm_raw:.1f}cm -> {dist_cm_corrected:.1f}cm")

                if not (SensorConfig.MIN_VALID_DISTANCE <= dist_cm_corrected <= SensorConfig.MAX_VALID_DISTANCE):
                    logger.debug(f"⚠️ Düzeltilmiş mesafe geçersiz: {dist_cm_corrected:.1f} cm. Orijinal kullanılacak.")
                    logger.debug(f"✅ Geçerli mesafe (orijinal): {dist_cm_raw:.1f} cm")
                    return dist_cm_raw

                logger.debug(f"✅ Geçerli mesafe (düzeltilmiş): {dist_cm_corrected:.1f} cm")
                return dist_cm_corrected

            logger.debug(f"✅ Geçerli mesafe: {dist_cm_raw:.1f} cm")
            return dist_cm_raw

        except Exception as e:
            logger.error(f"❌ Sensör okuma hatası: {e}")
            return None

    def stop_continuous_sensor_reading(self):
        """Sürekli sensör okumayı durdur"""
        if not self.sensor_running:
            return

        self.sensor_enabled = False
        self.sensor_running = False

        if self.sensor_thread and self.sensor_thread.is_alive():
            self.sensor_thread.join(timeout=2.0)

        logger.info("✓ Sensör okuma durduruldu")

    def read_distance(self) -> Optional[float]:
        """Anlık mesafe oku"""
        if self.sensor_enabled and self.sensor_running:
            return self.current_distance

        if not self._initialized['sensor'] and not GPIO_AVAILABLE:
            return np.random.uniform(10, 200)

        return self._read_distance_internal()

    def get_current_distance(self) -> Optional[float]:
        """Son okunan mesafe"""
        return self.current_distance

    def is_sensor_active(self) -> bool:
        """Sensör aktif mi?"""
        return self.sensor_enabled and self.sensor_running

    def cleanup_sensor(self):
        """Sensörü temizle"""
        try:
            self.stop_continuous_sensor_reading()

            if self.sensor:
                self.sensor.close()
                self.sensor = None
                self.adaptive_sensor = None
                self.current_distance = None
                self._initialized['sensor'] = False

            logger.info("✓ Sensör temizlendi")
        except Exception as e:
            logger.error(f"Sensör temizleme hatası: {e}")
            self.metrics['errors'] += 1

    # ========================================================================
    # GENEL YÖNETİM
    # ========================================================================

    def initialize_all(self) -> Dict[str, bool]:
        """Tüm donanımı başlat"""
        logger.info("=" * 60)
        logger.info("TÜM DONANIM BAŞLATILIYOR")
        logger.info("=" * 60)

        try:
            system_checks = SystemChecks.run_all_checks()
            for check, result in system_checks.items():
                status = "✓" if result else "✗"
                logger.info(f"{status} {check.upper()}: {'Başarılı' if result else 'Başarısız'}")
        except Exception as e:
            logger.error(f"Sistem kontrolü hatası: {e}")

        results = {'camera': False, 'motor': False, 'sensor': False}

        if self.executor:
            futures = []
            if CAMERA_AVAILABLE:
                futures.append(('camera', self.executor.submit(self.initialize_camera)))
            if GPIO_AVAILABLE:
                futures.append(('motor', self.executor.submit(self.initialize_motor)))
                futures.append(('sensor', self.executor.submit(self.initialize_sensor)))

            for name, future in futures:
                try:
                    results[name] = future.result(timeout=10)
                except Exception as e:
                    logger.error(f"{name} başlatma hatası: {e}")
                    results[name] = False
        else:
            if CAMERA_AVAILABLE:
                results['camera'] = self.initialize_camera()
            if GPIO_AVAILABLE:
                results['motor'] = self.initialize_motor()
                results['sensor'] = self.initialize_sensor()

        if not CAMERA_AVAILABLE:
            results['camera'] = False
        if not GPIO_AVAILABLE:
            results['motor'] = False
            results['sensor'] = False

        logger.info("=" * 60)
        logger.info("BAŞLATMA TAMAMLANDI")
        for component, success in results.items():
            status = "✓" if success else "✗"
            logger.info(f"{status} {component.upper()}: {'Başarılı' if success else 'Başarısız'}")
        logger.info("=" * 60)

        return results

    def cleanup_all(self):
        """Tüm donanımı temizle"""
        logger.info("=" * 60)
        logger.info("DONANIM TEMİZLİĞİ BAŞLADI")
        logger.info("=" * 60)

        if self.executor:
            futures = [
                self.executor.submit(self.cleanup_camera),
                self.executor.submit(self.cleanup_motor),
                self.executor.submit(self.cleanup_sensor)
            ]
            for future in futures:
                try:
                    future.result(timeout=5)
                except Exception as e:
                    logger.error(f"Temizleme hatası: {e}")
        else:
            self.cleanup_camera()
            self.cleanup_motor()
            self.cleanup_sensor()

        if self.executor:
            self.executor.shutdown(wait=True)

        logger.info("=" * 60)
        logger.info("DONANIM TEMİZLİĞİ TAMAMLANDI")
        logger.info("=" * 60)

    def get_system_status(self) -> Dict[str, Any]:
        """Detaylı sistem durumu"""
        uptime = datetime.now() - self.metrics['start_time']

        # Kamera ayarları cache'den
        cache = self._camera_settings_cache
        res_str = f"{cache['resolution'][0]}x{cache['resolution'][1]}"

        return {
            'initialized': self._initialized.copy(),
            'version': self.VERSION,
            'metrics': {
                **self.metrics,
                'uptime_seconds': uptime.total_seconds(),
                'fps': self.metrics['camera_frames'] / max(uptime.total_seconds(), 1)
            },
            'motor': self.get_motor_info(),
            'sensor': {
                'last_reading': self.current_distance,
                'is_active': self.is_sensor_active(),
                'adaptive_interval': self.adaptive_sensor.read_interval if self.adaptive_sensor else None
            },
            'camera': {
                'is_recording': self.is_recording,
                'model': CameraConfig.CAMERA_MODEL,
                'fov': CameraConfig.FOV_HORIZONTAL,
                'lens_correction': CameraConfig.ENABLE_LENS_CORRECTION,
                'buffer_size': len(self.frame_buffer.buffer) if hasattr(self, 'frame_buffer') else 0,
                'settings': cache,
                'settings_hash': self._settings_hash,
            },
            'circuit_breakers': {
                name: breaker.state
                for name, breaker in self.circuit_breakers.items()
            },
            'performance': {
                metric: self.performance_monitor.get_stats(metric)
                for metric in ['capture_frame', 'motor_move', 'sensor_distance']
            }
        }

    def __del__(self):
        """Destructor - temizlik yap"""
        try:
            self.cleanup_all()
        except:
            pass


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================
hardware_manager = HardwareManager()

# Export listesi
__all__ = [
    'HardwareManager',
    'hardware_manager',
    'CAMERA_AVAILABLE',
    'GPIO_AVAILABLE',
    'MotorCommandQueue',
    'AdaptiveSensorReader'
]

# Test modu
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logger.info(f"HardwareManager ({HardwareManager.VERSION}) doğrudan çalıştırıldı (Test Modu)...")

    results = hardware_manager.initialize_all()
    print(f"Başlatma Sonuçları: {results}")

    if True:
        print("\n=== KAMERA TEST ===")

        # Test 1: Varsayılan
        print("Test 1: Varsayılan ayarlar")
        frame1 = hardware_manager.capture_frame()
        if frame1 is not None:
            print(f"✓ Frame 1 alındı, Boyut: {frame1.shape}")

        # Test 2: Düşük çözünürlük + yüksek FPS
        print("\nTest 2: 640x480, 60fps, Manuel pozlama")
        frame2 = hardware_manager.capture_frame(
            resolution=(640, 480),
            framerate=60,
            ae_enable=False,
            exposure_time=5000,  # 5ms
            analogue_gain=2.0,    # ISO 200
        )
        if frame2 is not None:
            print(f"✓ Frame 2 alındı, Boyut: {frame2.shape}")

        # Test 3: Yüksek çözünürlük + görüntü ayarları
        print("\nTest 3: 1920x1080, Brightness/Contrast/Saturation")
        frame3 = hardware_manager.capture_frame(
            resolution=(1920, 1080),
            framerate=30,
            brightness=0.3,
            contrast=1.5,
            saturation=1.2,
            sharpness=2.0,
        )
        if frame3 is not None:
            print(f"✓ Frame 3 alındı, Boyut: {frame3.shape}")

        # Test 4: AWB Modu ve Colour Effect
        print("\nTest 4: AWB Daylight + Sepia Effect")
        frame4 = hardware_manager.capture_frame(
            awb_mode='Daylight',
            colour_effect='Sepia',
        )
        if frame4 is not None:
            print(f"✓ Frame 4 alındı, Boyut: {frame4.shape}")

        # Sistem durumu
        status = hardware_manager.get_system_status()
        print("\n=== SİSTEM DURUMU ===")
        print(json.dumps(status, indent=2, default=str))

    hardware_manager.cleanup_all()
    print("\nTest tamamlan")
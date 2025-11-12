# hardware_manager.py - Geliştirilmiş Donanım Yönetimi
# OV5647 130° kamera desteği, performans optimizasyonları ve hata yönetimi
import json
import time
import logging
import threading
import warnings
import cv2
import queue
from typing import Optional, Tuple, Dict, List, Any, Callable
from collections import deque
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from .config import (
    CameraConfig, MotorConfig, SensorConfig, AppConfig,
    PerformanceConfig, SystemChecks
)
from .utils import (
    CircuitBreaker, FrameBuffer, FisheyeCorrector,
    profile_performance, PerformanceMonitor
)

# Logger
logger = logging.getLogger(__name__)

# Donanım kütüphaneleri
try:
    from picamera2 import Picamera2
    from libcamera import controls
    from picamera2.encoders import H264Encoder

    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False
    logger.warning("picamera2 kütüphanesi bulunamadı. OV5647 simülasyon modunda.")

try:
    from gpiozero import OutputDevice, DistanceSensor, Button

    warnings.filterwarnings('ignore', category=Warning, module='gpiozero')
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("GPIO kütüphaneleri bulunamadı. Motor/Sensör simülasyon modunda.")


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
        """
        Komut ekle
        priority: 0 (en yüksek) - 10 (en düşük)
        """
        command = {
            'angle': angle,
            'callback': callback,
            'timestamp': time.time()
        }
        self.queue.put((priority, time.time(), command))

    def get_next(self) -> Optional[Dict]:
        """Sıradaki komutu al"""
        try:
            if not self.queue.empty():
                _, _, command = self.queue.get_nowait()
                return command
        except queue.Empty:
            pass
        return None

    def clear(self):
        """Kuyruğu temizle"""
        with self.lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break


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
        self.variance_threshold = 2.0  # cm

    def get_adaptive_interval(self, new_reading: float) -> float:
        """Okuma hızını adaptif olarak ayarla"""
        if self.last_reading is None:
            self.last_reading = new_reading
            return self.read_interval

        # Değişim miktarı
        change = abs(new_reading - self.last_reading)

        if change < self.variance_threshold:
            # Sabit okuma - yavaşlat
            self.stable_count += 1
            if self.stable_count > 10:
                self.read_interval = min(
                    SensorConfig.MAX_READ_INTERVAL,
                    self.read_interval * 1.1
                )
        else:
            # Hızlı değişim - hızlandır
            self.stable_count = 0
            self.read_interval = SensorConfig.MIN_READ_INTERVAL

        self.last_reading = new_reading
        return self.read_interval


# ============================================================================
# ANA DONANIM YÖNETİCİSİ
# ============================================================================

class HardwareManager:
    """
    Geliştirilmiş donanım yönetimi:
    - OV5647 130° kamera desteği
    - Adaptif sensör okuma
    - Motor komut kuyruğu
    - Circuit breaker pattern
    - Thread pool executor
    """

    def __init__(self):
        # Donanım objeleri
        self.camera: Optional[Picamera2] = None
        self.motor_devices: Optional[Tuple] = None
        self.sensor: Optional[DistanceSensor] = None
        self.limit_switches: Dict[str, Optional[Button]] = {
            'min': None,
            'max': None
        }

        # OV5647 lens düzeltici
        self.fisheye_corrector = FisheyeCorrector()
        self.fisheye_corrector.load_calibration()

        # Frame buffer
        self.frame_buffer = FrameBuffer(size=CameraConfig.FRAME_BUFFER_SIZE)

        # Motor yönetimi
        self.motor_ctx = {
            'current_angle': 0.0,
            'sequence_index': 0,
            'total_steps': 0,
            'is_moving': False,
            'last_direction': None,
            'target_angle': 0.0,
            'cancel_movement': False,
            'speed_profile': 'normal'
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
        self._initialized = {
            'camera': False,
            'motor': False,
            'sensor': False
        }

        # Circuit breakers
        self.circuit_breakers = {
            'camera': CircuitBreaker(
                failure_threshold=AppConfig.CIRCUIT_FAILURE_THRESHOLD,
                recovery_timeout=AppConfig.CIRCUIT_RECOVERY_TIMEOUT
            ),
            'motor': CircuitBreaker(failure_threshold=3, recovery_timeout=30),
            'sensor': CircuitBreaker(failure_threshold=5, recovery_timeout=20)
        }

        # Performans metrikleri
        self.performance_monitor = PerformanceMonitor()
        self.metrics = {
            'camera_frames': 0,
            'motor_moves': 0,
            'sensor_reads': 0,
            'errors': 0,
            'start_time': datetime.now()
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
        logger.info("HARDWARE MANAGER BAŞLATILDI")
        logger.info(f"OV5647 130° Kamera: {'Var' if CAMERA_AVAILABLE else 'Simülasyon'}")
        logger.info(f"GPIO: {'Aktif' if GPIO_AVAILABLE else 'Simülasyon'}")
        logger.info("=" * 60)

    # ========================================================================
    # KAMERA YÖNETİMİ (OV5647 130°)
    # ========================================================================

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

            # OV5647 için optimize edilmiş yapılandırma
            config = self.camera.create_video_configuration(
                main={"size": CameraConfig.DEFAULT_RESOLUTION, "format": "RGB888"},
                controls=CameraConfig.get_camera_settings()
            )

            self.camera.configure(config)

            # Otomatik ayarları etkinleştir
            if CameraConfig.ENABLE_AUTO_EXPOSURE:
                self.camera.set_controls({"AeEnable": True})
            if CameraConfig.ENABLE_AUTO_WHITE_BALANCE:
                self.camera.set_controls({"AwbEnable": True})

            self.camera.start()
            time.sleep(2)  # Kamera stabilizasyonu

            # Test frame'i al
            test_frame = self.camera.capture_array()
            if test_frame is None or test_frame.size == 0:
                raise Exception("Test frame alınamadı")

            # Frame buffer'a ekle
            self.frame_buffer.add_frame(test_frame)

            self._initialized['camera'] = True
            logger.info("✓ OV5647 130° kamera başarıyla başlatıldı")
            logger.info(f"  Çözünürlük: {CameraConfig.DEFAULT_RESOLUTION}")
            logger.info(f"  FOV: {CameraConfig.FOV_HORIZONTAL}° yatay")

            return True

        # Circuit breaker ile çağır
        try:
            if retry:
                for attempt in range(AppConfig.MAX_RETRY_COUNT):
                    try:
                        return self.circuit_breakers['camera'].call(_init_camera)
                    except Exception as e:
                        logger.error(f"Kamera başlatma hatası (Deneme {attempt + 1}): {e}")
                        if attempt < AppConfig.MAX_RETRY_COUNT - 1:
                            time.sleep(AppConfig.RETRY_DELAY * (2 ** attempt))  # Exponential backoff

            else:
                return self.circuit_breakers['camera'].call(_init_camera)

        except Exception as e:
            logger.error(f"Kamera başlatılamadı: {e}")
            self.metrics['errors'] += 1

        return False

    @profile_performance
    def capture_frame(self, apply_lens_correction: bool = True) -> Optional[np.ndarray]:
        """OV5647'den görüntü al (lens düzeltmeli)"""
        if not self._initialized['camera'] or self.camera is None:
            return self._generate_test_frame_ov5647()

        if self._locks['camera'].acquire(timeout=AppConfig.LOCK_TIMEOUT):
            try:
                frame = self.camera.capture_array()

                if frame is not None and frame.size > 0:
                    # Lens düzeltmesi (130° için)
                    if apply_lens_correction and CameraConfig.ENABLE_LENS_CORRECTION:
                        frame = self.fisheye_corrector.correct_distortion(frame, method='fast')

                    # Frame buffer'a ekle
                    if self.frame_buffer.add_frame(frame):
                        self.metrics['camera_frames'] += 1

                    # Performans metriği
                    self.performance_monitor.record('capture_frame', time.time())

                    return frame
                else:
                    return self._generate_test_frame_ov5647()

            except Exception as e:
                logger.error(f"Görüntü alma hatası: {e}")
                self.metrics['errors'] += 1
                return self.frame_buffer.get_latest()  # Son başarılı frame

            finally:
                self._locks['camera'].release()
        else:
            logger.warning("Kamera kilidi alınamadı (timeout)")
            return self.frame_buffer.get_latest()

    def _generate_test_frame_ov5647(self) -> Optional[np.ndarray]:
        """OV5647 130° simülasyon frame'i"""
        try:
            # OV5647 varsayılan çözünürlük
            height, width = 972, 1296
            frame = np.zeros((height, width, 3), dtype=np.uint8)

            # Arka plan gradyanı (mavi-yeşil)
            for i in range(height):
                frame[i, :] = [50 + i // 10, 100 + i // 8, 150 - i // 10]

            # 130° FOV grid çizgileri
            center_x, center_y = width // 2, height // 2

            # Merkez çizgileri
            cv2.line(frame, (center_x, 0), (center_x, height), (0, 255, 0), 2)
            cv2.line(frame, (0, center_y), (width, center_y), (0, 255, 0), 2)

            # FOV açı göstergeleri (130° için)
            fov_angles = [-65, -45, -30, -15, 0, 15, 30, 45, 65]
            for angle in fov_angles:
                # 130° lens projeksiyon formülü
                x = int(center_x + (width / 2) * np.tan(np.radians(angle)) / np.tan(np.radians(65)))
                if 0 <= x < width:
                    cv2.line(frame, (x, 0), (x, height), (255, 255, 0), 1)
                    cv2.putText(frame, f"{angle}°", (x - 15, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

            # Lens distorsiyon simülasyonu (barrel effect)
            k1, k2 = -0.35, 0.15  # OV5647 130° tipik değerler
            for r in range(100, min(center_x, center_y), 50):
                cv2.circle(frame, (center_x, center_y), r, (100, 100, 100), 1)

            # Bilgi metni
            info_texts = [
                "OV5647 130° SIMULASYON MODU",
                f"Çözünürlük: {width}x{height}",
                f"FOV: {CameraConfig.FOV_HORIZONTAL}° yatay",
                f"Zaman: {datetime.now().strftime('%H:%M:%S')}",
                f"FPS: {CameraConfig.VIDEO_FRAMERATE}",
                "Kamera takılı değil!"
            ]

            y_pos = 100
            for text in info_texts:
                color = (0, 255, 255) if "takılı değil" in text else (255, 255, 255)
                cv2.putText(frame, text, (50, y_pos),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                y_pos += 35

            # Simüle hareket (dönen nesne)
            angle = (time.time() * 50) % 360
            radius = 150
            obj_x = int(center_x + radius * np.cos(np.radians(angle)))
            obj_y = int(center_y + radius * np.sin(np.radians(angle)))

            # 3D efekt için gölge
            shadow_offset = 10
            cv2.circle(frame, (obj_x + shadow_offset, obj_y + shadow_offset),
                       35, (30, 30, 30), -1)
            cv2.circle(frame, (obj_x, obj_y), 30, (0, 0, 255), -1)
            cv2.circle(frame, (obj_x - 10, obj_y - 10), 10, (255, 100, 100), -1)

            # Motor ve sensör durumu göstergesi
            motor_angle = self.get_motor_angle()
            distance = self.current_distance or 0

            status_text = [
                f"Motor: {motor_angle:.1f}°",
                f"Sensör: {distance:.1f}cm" if distance > 0 else "Sensör: Kapalı"
            ]

            y_pos = height - 60
            for text in status_text:
                cv2.putText(frame, text, (50, y_pos),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
                y_pos += 25

            return frame

        except Exception as e:
            logger.error(f"Test frame oluşturma hatası: {e}")
            return np.zeros((972, 1296, 3), dtype=np.uint8)

    def start_recording(self, filepath: str) -> Tuple[bool, str]:
        """Video kaydını başlat (H264)"""
        if not self._initialized['camera'] or self.camera is None:
            return False, "Kamera kullanılamıyor"

        with self._locks['video']:
            try:
                if self.is_recording:
                    return False, "Zaten kayıt yapılıyor"

                # H264 encoder
                self.video_encoder = H264Encoder(bitrate=CameraConfig.VIDEO_BITRATE)

                # Metadata ekle
                metadata = {
                    'camera': CameraConfig.CAMERA_MODEL,
                    'fov': f"{CameraConfig.FOV_HORIZONTAL}°",
                    'resolution': f"{CameraConfig.DEFAULT_RESOLUTION[0]}x{CameraConfig.DEFAULT_RESOLUTION[1]}",
                    'date': datetime.now().isoformat()
                }

                self.camera.start_recording(self.video_encoder, filepath, metadata=metadata)

                self.is_recording = True
                self.recording_start_time = time.time()

                logger.info(f"✓ Video kaydı başlatıldı: {filepath}")
                logger.info(f"  Codec: H264, Bitrate: {CameraConfig.VIDEO_BITRATE / 1000000:.1f} Mbps")

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
                file_size_mb = 0  # Dosya boyutu hesaplanabilir

                self.is_recording = False
                self.video_encoder = None
                self.recording_start_time = None

                logger.info(f"✓ Video kaydı durduruldu")
                logger.info(f"  Süre: {duration:.1f} saniye")

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
                logger.info("✓ Kamera temizlendi")
        except Exception as e:
            logger.error(f"Kamera temizleme hatası: {e}")
            self.metrics['errors'] += 1

    # ========================================================================
    # MOTOR YÖNETİMİ (QUEUE SİSTEMİ İLE)
    # ========================================================================

    @profile_performance
    def initialize_motor(self, retry: bool = True) -> bool:
        """Step motoru başlat"""
        if not GPIO_AVAILABLE:
            logger.warning("Motor simülasyon modunda")
            self.motor_ctx['current_angle'] = 0.0
            self._initialized['motor'] = False
            return False

        def _init_motor():
            if self.motor_devices:
                self.cleanup_motor()

            logger.info("Step motor başlatılıyor...")

            # Motor pinlerini ayarla
            self.motor_devices = (
                OutputDevice(MotorConfig.H_MOTOR_IN1),
                OutputDevice(MotorConfig.H_MOTOR_IN2),
                OutputDevice(MotorConfig.H_MOTOR_IN3),
                OutputDevice(MotorConfig.H_MOTOR_IN4)
            )

            # Limit switch'leri ayarla
            if MotorConfig.LIMIT_SWITCH_MIN:
                self.limit_switches['min'] = Button(MotorConfig.LIMIT_SWITCH_MIN)
                logger.info(f"Min limit switch: GPIO{MotorConfig.LIMIT_SWITCH_MIN}")

            if MotorConfig.LIMIT_SWITCH_MAX:
                self.limit_switches['max'] = Button(MotorConfig.LIMIT_SWITCH_MAX)
                logger.info(f"Max limit switch: GPIO{MotorConfig.LIMIT_SWITCH_MAX}")

            # Motor context'i sıfırla
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

            # Motorları durdur
            self._stop_motor_internal()

            # Motor komut thread'ini başlat
            self.motor_queue_running = True
            self.motor_thread = threading.Thread(
                target=self._motor_command_processor,
                name="MotorCommandProcessor",
                daemon=True
            )
            self.motor_thread.start()

            self._initialized['motor'] = True
            logger.info("✓ Step motor başarıyla başlatıldı")
            logger.info(f"  Adım/Tur: {MotorConfig.STEPS_PER_REV}")
            logger.info(f"  Açı Aralığı: {MotorConfig.MIN_ANGLE}° - {MotorConfig.MAX_ANGLE}°")

            return True

        # Circuit breaker ile başlat
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

                    # Komutu işle
                    success = self._move_to_angle_internal(target_angle)

                    # Callback varsa çağır
                    if callback:
                        callback(success, target_angle)

                time.sleep(0.01)  # CPU kullanımını azalt

            except Exception as e:
                logger.error(f"Motor komut işleme hatası: {e}")
                time.sleep(0.1)

        logger.info("Motor komut işleyici durdu")

    @profile_performance
    def move_to_angle(self, target_angle: float,
                      speed_profile: str = 'normal',
                      priority: int = 5,
                      force: bool = False,
                      callback: Callable = None) -> bool:
        """
        Motoru belirtilen açıya götür (queue sistemi ile)

        Args:
            target_angle: Hedef açı
            speed_profile: Hız profili ('slow', 'normal', 'fast', 'scan')
            priority: Öncelik (0 en yüksek)
            force: Mevcut hareketi iptal et
            callback: Tamamlandığında çağrılacak fonksiyon
        """
        target_angle = self._validate_angle(target_angle)

        if not self._initialized['motor']:
            self.motor_ctx['current_angle'] = target_angle
            self.motor_ctx['target_angle'] = target_angle
            logger.debug(f"Motor simülasyon: {target_angle}°")
            if callback:
                callback(True, target_angle)
            return True

        if force:
            # Mevcut hareketi iptal et
            # Mevcut hareketi iptal et devamı
            self.motor_ctx['cancel_movement'] = True
            self.motor_command_queue.clear()
            time.sleep(0.1)

        # Hız profilini ayarla
        self.motor_ctx['speed_profile'] = speed_profile

        # Komut kuyruğuna ekle
        self.motor_command_queue.add_command(target_angle, priority, callback)

        # Senkron mod (callback yoksa bekle)
        if not callback:
            timeout = 10  # saniye
            start_time = time.time()

            while time.time() - start_time < timeout:
                if abs(self.motor_ctx['current_angle'] - target_angle) < 0.5:
                    return True
                time.sleep(0.1)

            logger.warning(f"Motor hareketi zaman aşımı: {target_angle}°")
            return False

        return True

    def _move_to_angle_internal(self, target_angle: float) -> bool:
        """Motor hareketi (internal)"""
        if self._locks['motor'].acquire(timeout=AppConfig.LOCK_TIMEOUT):
            try:
                self.motor_ctx['is_moving'] = True
                self.motor_ctx['target_angle'] = target_angle
                self.motor_ctx['cancel_movement'] = False

                current = self.motor_ctx['current_angle']
                deg_per_step = 360.0 / MotorConfig.STEPS_PER_REV
                angle_diff = target_angle - current

                # Backlash kompanzasyonu
                if self.motor_ctx['last_direction'] is not None:
                    new_direction = (angle_diff > 0)
                    if new_direction != self.motor_ctx['last_direction']:
                        # Yön değişimi - backlash kompanzasyonu ekle
                        compensation = MotorConfig.BACKLASH_COMPENSATION
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

                # Hız profilini al
                profile = MotorConfig.SPEED_PROFILES.get(
                    self.motor_ctx['speed_profile'],
                    MotorConfig.SPEED_PROFILES['normal']
                )
                step_delay = profile['delay']
                acceleration = profile['acceleration']

                # Acceleration ramp
                success = self._step_motor_with_acceleration(
                    num_steps, direction, step_delay,
                    deg_per_step, acceleration
                )

                if success:
                    self.motor_ctx['current_angle'] = target_angle
                    self.motor_ctx['last_direction'] = direction
                    self.metrics['motor_moves'] += 1

                    # Settle time
                    time.sleep(MotorConfig.SETTLE_TIME)

                    logger.info(f"✓ Motor hedefte: {target_angle:.1f}°")

                    # Performans metriği
                    self.performance_monitor.record('motor_move', angle_diff)

                elif self.motor_ctx['cancel_movement']:
                    logger.info(f"⚠️ Motor hareketi iptal edildi ({self.motor_ctx['current_angle']:.1f}°)")
                else:
                    logger.error("Motor hareketi başarısız")

                self.motor_ctx['is_moving'] = False
                return success

            except Exception as e:
                logger.error(f"Motor hareket hatası: {e}", exc_info=True)
                self.metrics['errors'] += 1
                self.motor_ctx['is_moving'] = False
                return False

            finally:
                self._locks['motor'].release()
        else:
            logger.warning("Motor kilidi alınamadı")
            return False

    def _step_motor_with_acceleration(self, num_steps: int, direction: bool,
                                      base_delay: float, deg_per_step: float,
                                      acceleration: float) -> bool:
        """Hızlanma/yavaşlama profili ile motor hareketi"""
        # GÜVENLIK: Acceleration çok yüksek olursa delay negatif olabilir
        acceleration = min(acceleration, 1.4)  # Maksimum 1.4x hızlanma

        step_increment = 1 if direction else -1
        if MotorConfig.INVERT_DIRECTION:
            step_increment *= -1

        angle_increment = deg_per_step * (1 if direction else -1)

        # Hızlanma ve yavaşlama bölgeleri
        accel_steps = min(100, num_steps // 4)
        decel_steps = accel_steps
        constant_steps = num_steps - accel_steps - decel_steps

        current_delay = base_delay * 3  # Yavaş başla

        for step in range(num_steps):
            # İptal kontrolü
            if self.motor_ctx['cancel_movement']:
                logger.debug(f"Hareket iptal edildi (Adım {step}/{num_steps})")
                self._stop_motor_internal()
                return False

            # Limit switch kontrolü
            if self._check_limits(direction):
                logger.warning(f"⚠️ Limit switch tetiklendi!")
                self._stop_motor_internal()
                return False

            # Hız profili hesapla
            if step < accel_steps:
                # Hızlanma
                progress = step / accel_steps
                current_delay = base_delay * (3 - 2 * progress * acceleration)
            elif step >= num_steps - decel_steps:
                # Yavaşlama
                progress = (num_steps - step) / decel_steps
                current_delay = base_delay * (3 - 2 * progress * acceleration)
            else:
                # Sabit hız
                current_delay = base_delay

            # Motor adımı
            idx = self.motor_ctx['sequence_index']
            idx = (idx + step_increment) % len(MotorConfig.STEP_SEQUENCE)
            self.motor_ctx['sequence_index'] = idx

            self._set_motor_pins(*MotorConfig.STEP_SEQUENCE[idx])

            # Pozisyon güncelle
            self.motor_ctx['current_angle'] += angle_increment
            self.motor_ctx['total_steps'] += 1

            # GÜVENLIK: Delay negatif olamaz!
            current_delay = max(0.0001, current_delay)  # Minimum 0.1ms
            time.sleep(current_delay)

            # İlerleme raporu
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
            self.motor_command_queue.clear()

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
            'queue_size': self.motor_command_queue.queue.qsize() if hasattr(self.motor_command_queue, 'queue') else 0
        }

    def cleanup_motor(self):
        """Motoru temizle"""
        try:
            # Thread'i durdur
            self.motor_queue_running = False
            if self.motor_thread and self.motor_thread.is_alive():
                self.motor_thread.join(timeout=2.0)

            # Motorları kapat
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
    # SENSÖR YÖNETİMİ (ADAPTİF OKUMA)
    # ========================================================================

    @profile_performance
    def initialize_sensor(self, retry: bool = True) -> bool:
        """Ultrasonik sensörü başlat"""
        if not GPIO_AVAILABLE:
            logger.warning("Sensör simülasyon modunda")
            self._initialized['sensor'] = False
            return False

        def _init_sensor():
            if self.sensor:
                self.cleanup_sensor()

            logger.info("Ultrasonik sensör başlatılıyor...")

            self.sensor = DistanceSensor(
                echo=SensorConfig.H_ECHO,
                trigger=SensorConfig.H_TRIG,
                max_distance=SensorConfig.MAX_DISTANCE,
                queue_len=SensorConfig.QUEUE_LEN,
                threshold_distance=SensorConfig.THRESHOLD_DISTANCE
            )

            # Adaptif okuyucu
            self.adaptive_sensor = AdaptiveSensorReader(self.sensor)

            time.sleep(1.0)  # Sensör stabilizasyonu

            # Test okumaları
            test_success = False
            for test in range(3):
                try:
                    test_reading = self.sensor.distance
                    if test_reading is not None:
                        test_cm = test_reading * 100
                        logger.info(f"✓ Test okuması #{test + 1}: {test_cm:.1f} cm")
                        test_success = True
                        break
                except Exception as e:
                    logger.warning(f"Test okuması #{test + 1} hatası: {e}")
                time.sleep(0.5)

            if test_success:
                self._initialized['sensor'] = True
                logger.info("✓ Sensör başarıyla başlatıldı")
                logger.info(f"  Menzil: {SensorConfig.MIN_VALID_DISTANCE}-{SensorConfig.MAX_VALID_DISTANCE} cm")
                return True
            else:
                raise Exception("Test okumaları başarısız")

        # Circuit breaker ile başlat
        try:
            return self.circuit_breakers['sensor'].call(_init_sensor)
        except Exception as e:
            logger.error(f"Sensör başlatma hatası: {e}")
            self.metrics['errors'] += 1
            return False

    def start_continuous_sensor_reading(self):
        """Adaptif hızda sürekli sensör okuma"""
        if not self._initialized['sensor']:
            logger.error("Sensör başlatılmamış!")
            return False

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
                if self._initialized['sensor'] and self.sensor:
                    distance_cm = self._read_distance_internal()

                    if distance_cm is not None:
                        self.current_distance = distance_cm
                        self.metrics['sensor_reads'] += 1

                        # Adaptif interval hesapla
                        if self.adaptive_sensor:
                            interval = self.adaptive_sensor.get_adaptive_interval(distance_cm)
                        else:
                            interval = SensorConfig.MIN_READ_INTERVAL

                        # Performans metriği
                        self.performance_monitor.record('sensor_distance', distance_cm)

                        time.sleep(interval)
                    else:
                        time.sleep(SensorConfig.MAX_READ_INTERVAL)
                else:
                    time.sleep(1.0)

            except Exception as e:
                logger.error(f"Sensör thread hatası: {e}")
                time.sleep(0.5)

        logger.info("📡 Adaptif sensör thread durdu")

    def _read_distance_internal(self) -> Optional[float]:
        """Sensörden mesafe oku (internal)"""
        try:
            if not self.sensor:
                return None

            readings = []

            for _ in range(SensorConfig.READ_ATTEMPTS):
                dist_m = self.sensor.distance
                if dist_m is not None:
                    readings.append(dist_m)
                time.sleep(SensorConfig.READ_DELAY)

            if not readings:
                return None

            # Median filter
            if SensorConfig.USE_MEDIAN_FILTER:
                readings.sort()
                median_dist_m = readings[len(readings) // 2]
            else:
                median_dist_m = np.mean(readings)

            # Sıcaklık kompanzasyonu
            if SensorConfig.TEMPERATURE_COMPENSATION:
                sound_speed = SensorConfig.calculate_sound_speed()
                correction_factor = sound_speed / 343.0  # 20°C'deki ses hızı
                median_dist_m *= correction_factor

            dist_cm = median_dist_m * 100 + SensorConfig.CALIBRATION_OFFSET

            # Geçerlilik kontrolü
            if SensorConfig.MIN_VALID_DISTANCE <= dist_cm <= SensorConfig.MAX_VALID_DISTANCE:
                return dist_cm

            return None

        except Exception as e:
            logger.debug(f"Sensör okuma hatası: {e}")
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

        if not self._initialized['sensor']:
            # Simülasyon modu
            return np.random.uniform(10, 200)

        # Tek okuma
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
            # Thread'i durdur
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

        # Sistem kontrollerini çalıştır
        system_checks = SystemChecks.run_all_checks()
        for check, result in system_checks.items():
            status = "✓" if result else "✗"
            logger.info(f"{status} {check.upper()}: {'Başarılı' if result else 'Başarısız'}")

        results = {
            'camera': False,
            'motor': False,
            'sensor': False
        }

        # Paralel başlatma (thread pool ile)
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
            # Sıralı başlatma
            if CAMERA_AVAILABLE:
                results['camera'] = self.initialize_camera()
            if GPIO_AVAILABLE:
                results['motor'] = self.initialize_motor()
                results['sensor'] = self.initialize_sensor()

        # Özet
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

        # Paralel temizleme
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

        # Thread pool'u kapat
        if self.executor:
            self.executor.shutdown(wait=True)

        logger.info("=" * 60)
        logger.info("DONANIM TEMİZLİĞİ TAMAMLANDI")
        logger.info("=" * 60)

    def get_system_status(self) -> Dict[str, Any]:
        """Detaylı sistem durumu"""
        uptime = datetime.now() - self.metrics['start_time']

        return {
            'initialized': self._initialized.copy(),
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
                'buffer_size': len(self.frame_buffer.buffer) if hasattr(self, 'frame_buffer') else 0
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

    # Donanımı başlat
    results = hardware_manager.initialize_all()
    print(f"Başlatma sonuçları: {results}")

    # Test hareketleri
    if results['motor']:
        hardware_manager.move_to_angle(90, speed_profile='fast')
        time.sleep(2)
        hardware_manager.move_to_angle(0, speed_profile='slow')

    # Sistem durumu
    status = hardware_manager.get_system_status()
    print(f"Sistem durumu: {json.dumps(status, indent=2)}")

    # Temizlik
    hardware_manager.cleanup_all()
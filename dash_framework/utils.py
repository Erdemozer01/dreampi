# utils.py - Geliştirilmiş Yardımcı Fonksiyonlar
# OV5647 130° lens düzeltme, performans optimizasyonları ve hata yönetimi

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
from datetime import datetime
from functools import wraps, lru_cache
from dataclasses import dataclass
import json

from .config import CameraConfig, AppConfig, SensorConfig, PerformanceConfig

try:
    from PIL import Image, ImageFilter, ExifTags
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL kütüphanesi bulunamadı. Görüntü işleme sınırlı.")

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Store güncellemeleri için kilit
store_lock = threading.Lock()

# Logger
logger = logging.getLogger(__name__)


# ============================================================================
# PERFORMANS İZLEME VE PROFİLİNG
# ============================================================================

class PerformanceMonitor:
    """Performans metriklerini izle"""

    def __init__(self):
        self.metrics = deque(maxlen=AppConfig.MAX_METRICS_HISTORY)
        self.lock = threading.Lock()

    def record(self, metric_name: str, value: float, timestamp: Optional[datetime] = None):
        """Metrik kaydet"""
        with self.lock:
            self.metrics.append({
                'name': metric_name,
                'value': value,
                'timestamp': timestamp or datetime.now()
            })

    def get_stats(self, metric_name: str) -> Dict[str, float]:
        """İstatistikleri al"""
        with self.lock:
            values = [m['value'] for m in self.metrics if m['name'] == metric_name]
            if not values:
                return {}
            return {
                'mean': np.mean(values),
                'std': np.std(values),
                'min': np.min(values),
                'max': np.max(values),
                'count': len(values)
            }


def profile_performance(func: Callable) -> Callable:
    """Fonksiyon performansını ölç"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not PerformanceConfig.ENABLE_PROFILING:
            return func(*args, **kwargs)

        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()

        duration = (end_time - start_time) * 1000  # ms
        logger.debug(f"{func.__name__} took {duration:.2f}ms")

        # Metrik kaydet
        if hasattr(wrapper, '_monitor'):
            wrapper._monitor.record(func.__name__, duration)

        return result

    wrapper._monitor = PerformanceMonitor()
    return wrapper


# ============================================================================
# CİRCUİT BREAKER PATTERN
# ============================================================================

class CircuitBreaker:
    """Hata durumlarında sistemi koru"""

    CLOSED = 'CLOSED'
    OPEN = 'OPEN'
    HALF_OPEN = 'HALF_OPEN'

    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: int = 60,
                 expected_exception: type = Exception):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = None
        self.state = self.CLOSED
        self.lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs):
        """Fonksiyonu circuit breaker ile çağır"""
        with self.lock:
            if self.state == self.OPEN:
                if self._should_attempt_reset():
                    self.state = self.HALF_OPEN
                else:
                    raise Exception("Circuit breaker is OPEN")

            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result

            except self.expected_exception as e:
                self._on_failure()
                raise e

    def _should_attempt_reset(self) -> bool:
        """Reset denemeli mi?"""
        return (self.last_failure_time and
                time.time() - self.last_failure_time >= self.recovery_timeout)

    def _on_success(self):
        """Başarılı çağrı"""
        self.failure_count = 0
        self.state = self.CLOSED

    def _on_failure(self):
        """Başarısız çağrı"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


# ============================================================================
# FRAME CACHE VE BUFFER YÖNETİMİ
# ============================================================================

class FrameBuffer:
    """Thread-safe frame buffer yönetimi"""

    def __init__(self, size: int = 3):
        self.buffer = deque(maxlen=size)
        self.lock = threading.Lock()
        self.last_frame = None
        self.last_hash = None
        self.frame_id = 0

    def add_frame(self, frame: np.ndarray) -> bool:
        """Frame'i buffer'a ekle (duplicate kontrolü ile)"""
        with self.lock:
            # Frame hash'i hesapla (performans için sadece köşeleri kontrol et)
            frame_hash = self._calculate_frame_hash(frame)

            # Aynı frame ise ekleme
            if frame_hash == self.last_hash:
                return False

            self.buffer.append({
                'id': self.frame_id,
                'frame': frame.copy(),
                'hash': frame_hash,
                'timestamp': time.time()
            })

            self.last_frame = frame.copy()
            self.last_hash = frame_hash
            self.frame_id += 1

            return True

    def get_latest(self) -> Optional[np.ndarray]:
        """En son frame'i al"""
        with self.lock:
            if self.buffer:
                return self.buffer[-1]['frame'].copy()
            return None

    def get_by_id(self, frame_id: int) -> Optional[np.ndarray]:
        """ID'ye göre frame al"""
        with self.lock:
            for item in self.buffer:
                if item['id'] == frame_id:
                    return item['frame'].copy()
            return None

    def _calculate_frame_hash(self, frame: np.ndarray) -> str:
        """Frame hash'i hesapla (hızlı)"""
        # Sadece köşeleri ve merkezi kontrol et
        h, w = frame.shape[:2]
        sample = np.concatenate([
            frame[0:10, 0:10].flatten(),       # Sol üst
            frame[0:10, w-10:w].flatten(),     # Sağ üst
            frame[h-10:h, 0:10].flatten(),     # Sol alt
            frame[h-10:h, w-10:w].flatten(),   # Sağ alt
            frame[h//2-5:h//2+5, w//2-5:w//2+5].flatten()  # Merkez
        ])
        return hashlib.md5(sample.tobytes()).hexdigest()

    def clear(self):
        """Buffer'ı temizle"""
        with self.lock:
            self.buffer.clear()
            self.last_frame = None
            self.last_hash = None


# ============================================================================
# LENS DİSTORSİYON DÜZELTME (OV5647 130°)
# ============================================================================

class FisheyeCorrector:
    """OV5647 130° geniş açı lens düzeltme"""

    def __init__(self):
        self.calibrated = False
        self.camera_matrix = None
        self.dist_coeffs = None
        self.new_camera_matrix = None
        self.map1 = None
        self.map2 = None
        self.roi = None

        # OV5647 için varsayılan parametreler
        self.default_dist_coeffs = np.array(CameraConfig.DISTORTION_COEFFICIENTS)

    def calibrate_from_checkerboard(self, images: List[np.ndarray],
                                    pattern_size: Tuple[int, int] = (9, 6),
                                    square_size: float = 25.0) -> bool:
        """Satranç tahtası görüntüleri ile kalibrasyon"""
        if len(images) < 10:
            logger.error("Kalibrasyon için en az 10 görüntü gerekli")
            return False

        # Kalibrasyon noktaları
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

        # 3D noktalar
        objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
        objp[:,:2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2)
        objp *= square_size

        objpoints = []  # 3D noktalar
        imgpoints = []  # 2D noktalar

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)

            if ret:
                objpoints.append(objp)
                corners2 = cv2.cornerSubPix(gray, corners, (11,11), (-1,-1), criteria)
                imgpoints.append(corners2)

        if len(objpoints) < 5:
            logger.error("Yeterli kalibrasyon noktası bulunamadı")
            return False

        # Kalibrasyon
        h, w = images[0].shape[:2]
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
            objpoints, imgpoints, (w, h), None, None
        )

        if ret:
            self.camera_matrix = mtx
            self.dist_coeffs = dist

            # Optimal kamera matrisi
            self.new_camera_matrix, self.roi = cv2.getOptimalNewCameraMatrix(
                mtx, dist, (w, h), 1, (w, h)
            )

            # Remap için haritalar
            self.map1, self.map2 = cv2.initUndistortRectifyMap(
                mtx, dist, None, self.new_camera_matrix, (w, h), cv2.CV_16SC2
            )

            self.calibrated = True
            self._save_calibration()
            logger.info("✓ Lens kalibrasyonu başarılı")
            return True

        return False

    @profile_performance
    def correct_distortion(self, image: np.ndarray, method: str = 'fast') -> np.ndarray:
        """Lens distorsiyonunu düzelt"""
        if image is None or image.size == 0:
            return image

        h, w = image.shape[:2]

        if method == 'fast' or not self.calibrated:
            # Hızlı yaklaşık düzeltme
            return self._correct_simple(image)

        elif method == 'precise' and self.calibrated:
            # Kalibre edilmiş düzeltme
            return cv2.remap(image, self.map1, self.map2,
                             interpolation=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT)

        elif method == 'fisheye':
            # Balık gözü düzeltme
            return self._correct_fisheye(image)

        return image

    def _correct_simple(self, image: np.ndarray) -> np.ndarray:
        """Basit barrel distortion düzeltme"""
        h, w = image.shape[:2]

        # OV5647 için kamera matrisi (yaklaşık)
        focal_length = w * 0.8  # 130° FOV için
        center = (w/2, h/2)

        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype="double")

        # OV5647 130° lens için tipik distorsiyon
        dist_coeffs = self.default_dist_coeffs

        # Düzeltme uygula
        newcam, roi = cv2.getOptimalNewCameraMatrix(
            camera_matrix, dist_coeffs, (w,h), 0.8, (w,h)
        )

        dst = cv2.undistort(image, camera_matrix, dist_coeffs, None, newcam)

        # ROI kırp (opsiyonel)
        if roi != (0, 0, 0, 0):
            x, y, w, h = roi
            dst = dst[y:y+h, x:x+w]
            # Orijinal boyuta geri döndür
            dst = cv2.resize(dst, (image.shape[1], image.shape[0]))

        return dst

    def _correct_fisheye(self, image: np.ndarray) -> np.ndarray:
        """Balık gözü modeli ile düzeltme"""
        h, w = image.shape[:2]

        # Balık gözü kamera modeli
        K = np.array([[w/2, 0, w/2],
                      [0, h/2, h/2],
                      [0, 0, 1]], dtype=np.float32)

        D = np.array([0.1, -0.2, 0.0, 0.0], dtype=np.float32)

        # Düzeltme haritaları
        map1, map2 = cv2.fisheye.initUndistortRectifyMap(
            K, D, np.eye(3), K, (w, h), cv2.CV_16SC2
        )

        return cv2.remap(image, map1, map2,
                         interpolation=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT)

    def _save_calibration(self):
        """Kalibrasyon verilerini kaydet"""
        if not self.calibrated:
            return

        calib_file = CameraConfig.CALIBRATION_DIR / "ov5647_calibration.npz"
        np.savez(calib_file,
                 camera_matrix=self.camera_matrix,
                 dist_coeffs=self.dist_coeffs,
                 new_camera_matrix=self.new_camera_matrix,
                 roi=self.roi)
        logger.info(f"Kalibrasyon kaydedildi: {calib_file}")

    def load_calibration(self) -> bool:
        """Kalibrasyon verilerini yükle"""
        calib_file = CameraConfig.CALIBRATION_DIR / "ov5647_calibration.npz"

        if not calib_file.exists():
            return False

        try:
            data = np.load(calib_file)
            self.camera_matrix = data['camera_matrix']
            self.dist_coeffs = data['dist_coeffs']
            self.new_camera_matrix = data['new_camera_matrix']
            self.roi = data['roi']

            # Remap haritalarını oluştur
            h, w = 972, 1296  # OV5647 varsayılan
            self.map1, self.map2 = cv2.initUndistortRectifyMap(
                self.camera_matrix, self.dist_coeffs, None,
                self.new_camera_matrix, (w, h), cv2.CV_16SC2
            )

            self.calibrated = True
            logger.info("✓ Kalibrasyon verileri yüklendi")
            return True

        except Exception as e:
            logger.error(f"Kalibrasyon yükleme hatası: {e}")
            return False


# ============================================================================
# GELİŞMİŞ GÖRÜNTÜ İŞLEME
# ============================================================================

class ImageProcessor:
    """Görüntü işleme pipeline"""

    def __init__(self):
        self.processors = []
        self.fisheye_corrector = FisheyeCorrector()
        self.fisheye_corrector.load_calibration()

    def add_processor(self, func: Callable, name: str = None):
        """İşlemci ekle"""
        self.processors.append({
            'func': func,
            'name': name or func.__name__
        })

    @profile_performance
    def process(self, image: np.ndarray) -> np.ndarray:
        """Tüm işlemcileri uygula"""
        for proc in self.processors:
            try:
                image = proc['func'](image)
            except Exception as e:
                logger.error(f"İşlemci hatası ({proc['name']}): {e}")
        return image

    def apply_effect(self, image: np.ndarray, effect_type: str) -> np.ndarray:
        """Görüntü efekti uygula"""
        if effect_type == 'none' or image is None:
            return image

        try:
            if effect_type == 'grayscale':
                return self._grayscale(image)
            elif effect_type == 'edges':
                return self._edge_detection(image)
            elif effect_type == 'invert':
                return 255 - image
            elif effect_type == 'blur':
                return cv2.GaussianBlur(image, (5, 5), 0)
            elif effect_type == 'sharpen':
                return self._sharpen(image)
            elif effect_type == 'hdr':
                return self._hdr_effect(image)
            elif effect_type == 'night_vision':
                return self._night_vision(image)
            elif effect_type == 'thermal':
                return self._thermal_effect(image)

        except Exception as e:
            logger.error(f"Efekt uygulama hatası ({effect_type}): {e}")

        return image

    def _grayscale(self, image: np.ndarray) -> np.ndarray:
        """Weighted grayscale dönüşüm"""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        return image

    def _edge_detection(self, image: np.ndarray) -> np.ndarray:
        """Canny edge detection"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    def _sharpen(self, image: np.ndarray) -> np.ndarray:
        """Keskinleştirme filtresi"""
        kernel = np.array([[-1,-1,-1],
                           [-1, 9,-1],
                           [-1,-1,-1]])
        return cv2.filter2D(image, -1, kernel)

    def _hdr_effect(self, image: np.ndarray) -> np.ndarray:
        """HDR benzeri efekt"""
        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        l = clahe.apply(l)

        lab = cv2.merge([l, a, b])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    def _night_vision(self, image: np.ndarray) -> np.ndarray:
        """Gece görüşü efekti"""
        # Yeşil tonlama
        green_channel = image[:,:,1]
        night = np.zeros_like(image)
        night[:,:,1] = green_channel

        # Kontrast artır
        return cv2.addWeighted(night, 1.5, night, 0, 30)

    def _thermal_effect(self, image: np.ndarray) -> np.ndarray:
        """Termal kamera efekti"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thermal = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
        return thermal


# ============================================================================
# OPTİMİZE EDİLMİŞ GÖRÜNTÜ DÖNÜŞTÜRME
# ============================================================================


@profile_performance
def image_to_base64(
        image: Optional[np.ndarray],
        quality: int = None,
        max_size: tuple = None,
        format: str = 'JPEG',
        apply_lens_correction: bool = True
) -> str:
    """
    NumPy array'i optimize edilmiş base64'e çevir
    OV5647 130° lens düzeltmesi opsiyonel
    """
    if image is None:
        logger.warning("image_to_base64: Görüntü None")
        return ""

    if not PIL_AVAILABLE:
        logger.error("PIL kütüphanesi yüklü değil")
        return ""

    # Varsayılan değerler
    if quality is None:
        quality = CameraConfig.IMAGE_QUALITY
    if max_size is None:
        max_size = CameraConfig.IMAGE_MAX_SIZE

    try:
        # Lens düzeltmesi (opsiyonel)
        if apply_lens_correction and CameraConfig.ENABLE_LENS_CORRECTION:
            corrector = FisheyeCorrector()
            image = corrector.correct_distortion(image, method='fast')

        # NumPy -> PIL
        pil_img = Image.fromarray(image)

        if pil_img.mode == 'RGBA':
            pil_img = pil_img.convert('RGB')
        # ================================

        # Boyutu optimize et
        pil_img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Format seçimi ve optimizasyon
        buffer = io.BytesIO()
        save_kwargs = {
            'format': format,
            'optimize': True,
        }

        if format == 'JPEG':
            save_kwargs['quality'] = quality
            save_kwargs['progressive'] = True
        elif format == 'PNG':
            save_kwargs['compress_level'] = 6
        elif format == 'WEBP':
            save_kwargs['quality'] = quality
            save_kwargs['method'] = 6

        # EXIF eklemeyi atla - sorun yaratıyor
        # Not: EXIF metadata eklemek isterseniz, doğru şekilde yapılmalı
        # Şimdilik kaldırıldı çünkü struct.pack hatası veriyor

        pil_img.save(buffer, **save_kwargs)

        # Base64 encode
        img_str = base64.b64encode(buffer.getvalue()).decode()
        mime_type = f"image/{format.lower()}"

        return f"data:{mime_type};base64,{img_str}"

    except Exception as e:
        logger.error(f"Base64 dönüştürme hatası: {e}", exc_info=True)
        return ""

# ============================================================================
# 3D POZİSYON HESAPLAMALARI (130° FOV)
# ============================================================================

@lru_cache(maxsize=128)
def calculate_3d_position_with_fov(
        angle_deg: float,
        distance_cm: float,
        fov_horizontal: float = 130,
        tilt_deg: float = 0,
        height_offset: float = 0
) -> Tuple[float, float, float]:
    """
    OV5647 130° FOV için düzeltilmiş 3D pozisyon hesaplama
    """
    if distance_cm is None or not isinstance(distance_cm, (int, float)):
        return (0.0, 0.0, 0.0)

    # FOV düzeltme faktörü
    fov_factor = math.tan(math.radians(fov_horizontal/2)) / math.tan(math.radians(45))

    # Geniş açı lens için düzeltme
    corrected_angle = angle_deg / fov_factor

    # Açıları radyana çevir
    pan_rad = math.radians(corrected_angle)
    tilt_rad = math.radians(tilt_deg)

    # Lens distorsiyonu kompanzasyonu
    # 130° lens için merkeze uzaklık arttıkça distorsiyon artar
    distortion_factor = 1.0 + (0.002 * abs(angle_deg))
    distance_corrected = distance_cm * distortion_factor

    # Sensör kalibrasyon offset'i
    distance_corrected += SensorConfig.CALIBRATION_OFFSET

    # 3D koordinatları hesapla
    horizontal_distance = distance_corrected * math.cos(tilt_rad)

    x = horizontal_distance * math.sin(pan_rad)
    y = horizontal_distance * math.cos(pan_rad)
    z = distance_corrected * math.sin(tilt_rad) + height_offset

    return (round(x, 2), round(y, 2), round(z, 2))


# ============================================================================
# STORE YÖNETİMİ
# ============================================================================

class StoreManager:
    """Thread-safe store yönetimi"""

    def __init__(self, use_redis: bool = AppConfig.USE_REDIS_CACHE):
        self.use_redis = use_redis and REDIS_AVAILABLE
        self.local_store = {}
        self.lock = threading.Lock()

        if self.use_redis:
            try:
                self.redis_client = redis.Redis(
                    host=AppConfig.REDIS_HOST,
                    port=AppConfig.REDIS_PORT,
                    decode_responses=True
                )
                self.redis_client.ping()
                logger.info("✓ Redis cache bağlantısı kuruldu")
            except:
                self.use_redis = False
                logger.warning("Redis bağlantısı kurulamadı, local store kullanılıyor")

    def get(self, key: str, default=None):
        """Değer al"""
        if self.use_redis:
            try:
                value = self.redis_client.get(key)
                return json.loads(value) if value else default
            except:
                pass

        with self.lock:
            return self.local_store.get(key, default)

    def set(self, key: str, value: Any, ttl: int = None):
        """Değer kaydet"""
        if self.use_redis:
            try:
                self.redis_client.set(
                    key,
                    json.dumps(value),
                    ex=ttl or AppConfig.CACHE_TTL
                )
                return
            except:
                pass

        with self.lock:
            self.local_store[key] = value

    def update(self, updates: Dict[str, Any]):
        """Toplu güncelleme"""
        if self.use_redis:
            try:
                pipe = self.redis_client.pipeline()
                for key, value in updates.items():
                    pipe.set(key, json.dumps(value), ex=AppConfig.CACHE_TTL)
                pipe.execute()
                return
            except:
                pass

        with self.lock:
            self.local_store.update(updates)


def safe_update_store(store_data: dict, updates: dict) -> dict:
    """Thread-safe store güncellemesi"""
    with store_lock:
        try:
            # Deep copy ile veri bütünlüğünü koru
            updated_store = deepcopy(store_data)

            # Her güncellemeyi kontrollü uygula
            for key, value in updates.items():
                # Liste güncellemeleri için boyut kontrolü
                if isinstance(value, list):
                    if key == 'photos' and len(value) > AppConfig.MAX_PHOTOS_IN_MEMORY:
                        value = value[-AppConfig.MAX_PHOTOS_IN_MEMORY:]
                    elif key == 'scan_points' and len(value) > AppConfig.MAX_SCAN_POINTS:
                        value = value[-AppConfig.MAX_SCAN_POINTS:]

                updated_store[key] = value

            # Metadata ekle
            updated_store['last_updated'] = datetime.now().isoformat()
            updated_store['update_count'] = updated_store.get('update_count', 0) + 1

            return updated_store

        except Exception as e:
            logger.error(f"Store güncelleme hatası: {e}")
            return store_data


# ============================================================================
# YARDIMCI FONKSİYONLAR
# ============================================================================

def limit_list_size(data_list: list, max_size: int, keep: str = 'recent') -> list:
    """Liste boyutunu sınırla"""
    if not isinstance(data_list, list):
        logger.warning(f"limit_list_size: Geçersiz veri tipi {type(data_list)}")
        return []

    if len(data_list) <= max_size:
        return data_list

    if keep == 'recent':
        return data_list[-max_size:]
    elif keep == 'old':
        return data_list[:max_size]
    elif keep == 'distributed':
        # Eşit aralıklarla örnekle
        step = len(data_list) / max_size
        indices = [int(i * step) for i in range(max_size)]
        return [data_list[i] for i in indices]
    else:
        return data_list[-max_size:]


def format_distance(distance_cm: Optional[float], precision: int = 1) -> str:
    """Mesafe değerini formatla"""
    if distance_cm is None:
        return "Okuma Hatası"

    if distance_cm < 0:
        return "Geçersiz"

    if distance_cm < SensorConfig.MIN_VALID_DISTANCE:
        return f"Çok Yakın (<{SensorConfig.MIN_VALID_DISTANCE}cm)"

    if distance_cm > SensorConfig.MAX_VALID_DISTANCE:
        return f"Çok Uzak (>{SensorConfig.MAX_VALID_DISTANCE}cm)"

    # Birim dönüşümü
    if distance_cm >= 100:
        return f"{distance_cm/100:.{precision}f} m"
    else:
        return f"{distance_cm:.{precision}f} cm"


def validate_resolution(resolution_str: str) -> Tuple[int, int]:
    """Çözünürlük string'ini doğrula"""
    try:
        if 'x' not in resolution_str:
            raise ValueError(f"Geçersiz format: {resolution_str}")

        width, height = map(int, resolution_str.split('x'))

        # OV5647 için mantıklı sınırlar
        if not (320 <= width <= 2592) or not (240 <= height <= 1944):
            raise ValueError(f"Çözünürlük sınır dışı: {width}x{height}")

        return (width, height)

    except (ValueError, AttributeError) as e:
        logger.warning(f"Geçersiz çözünürlük: {resolution_str} - {e}")
        return CameraConfig.DEFAULT_RESOLUTION


def get_photo_metadata(
        angle: float,
        distance: str,
        effect: str,
        timestamp: str,
        additional_data: Dict[str, Any] = None
) -> dict:
    """Fotoğraf metadata'sını oluştur"""
    metadata = {
        'timestamp': timestamp,
        'angle': angle,
        'distance': distance,
        'effect': effect,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'time': datetime.now().strftime('%H:%M:%S'),
        'camera_model': CameraConfig.CAMERA_MODEL,
        'fov': CameraConfig.FOV_HORIZONTAL,
        'version': AppConfig.APP_VERSION
    }

    # Ek veri varsa ekle
    if additional_data:
        metadata.update(additional_data)

    # Unique ID oluştur
    hash_input = f"{timestamp}{angle}{distance}".encode()
    metadata['id'] = hashlib.md5(hash_input).hexdigest()[:8]

    return metadata


def create_scan_point(
        angle: float,
        distance_cm: float,
        tilt: float = 0,
        timestamp: Optional[str] = None
) -> dict:
    """3D tarama noktası oluştur"""
    x, y, z = calculate_3d_position_with_fov(
        angle, distance_cm, CameraConfig.FOV_HORIZONTAL, tilt
    )

    point = {
        'angle': angle,
        'tilt': tilt,
        'distance': distance_cm,
        'x': x,
        'y': y,
        'z': z,
        'timestamp': timestamp or datetime.now().isoformat(),
        'confidence': calculate_confidence(distance_cm)
    }

    return point


def calculate_confidence(distance_cm: float) -> float:
    """Mesafe ölçümü güven skoru"""
    if distance_cm is None:
        return 0.0

    # OV5647 130° için optimal mesafe aralığı
    optimal_min = 30   # 130° lens için minimum
    optimal_max = 250  # 130° lens için maksimum

    if optimal_min <= distance_cm <= optimal_max:
        return 1.0
    elif distance_cm < optimal_min:
        return max(0.3, distance_cm / optimal_min)
    else:
        return max(0.3, optimal_max / distance_cm)


def validate_gpio_pin(pin: int, pin_type: str = 'general') -> bool:
    """GPIO pin numarasını doğrula"""
    # Raspberry Pi 5 GPIO pinleri (BCM numaralandırma)
    valid_pins = list(range(2, 28))  # GPIO2-GPIO27

    # Özel pinler
    reserved_pins = {
        'i2c': [2, 3],  # I2C1
        'spi': [7, 8, 9, 10, 11],  # SPI0
        'uart': [14, 15],  # UART0
    }

    if pin not in valid_pins:
        logger.error(f"Geçersiz GPIO pin: {pin}")
        return False

    # Rezerve pin kontrolü
    for bus_type, pins in reserved_pins.items():
        if pin in pins and pin_type != bus_type:
            logger.warning(f"GPIO{pin}, {bus_type} için rezerve edilmiş")

    return True


def interpolate_scan_points(points: List[dict], max_gap: float = 10.0) -> List[dict]:
    """Tarama noktaları arasında interpolasyon"""
    if len(points) < 2:
        return points

    interpolated = []

    for i in range(len(points) - 1):
        current = points[i]
        next_point = points[i + 1]

        interpolated.append(current)

        # Açı farkını kontrol et
        angle_diff = abs(next_point['angle'] - current['angle'])

        if angle_diff > max_gap:
            # İnterpolasyon gerekli
            num_points = int(angle_diff / max_gap)

            for j in range(1, num_points):
                ratio = j / num_points

                # Lineer interpolasyon
                interp_point = {
                    'angle': current['angle'] + (next_point['angle'] - current['angle']) * ratio,
                    'distance': current['distance'] + (next_point['distance'] - current['distance']) * ratio,
                    'interpolated': True
                }

                # 3D koordinatları hesapla
                x, y, z = calculate_3d_position_with_fov(
                    interp_point['angle'],
                    interp_point['distance'],
                    CameraConfig.FOV_HORIZONTAL
                )
                interp_point.update({'x': x, 'y': y, 'z': z})

                interpolated.append(interp_point)

    # Son noktayı ekle
    if points:
        interpolated.append(points[-1])

    return interpolated


# ============================================================================
# TEST FONKSİYONLARI
# ============================================================================

def run_self_test() -> bool:
    """Modül self-test"""
    tests_passed = True

    try:
        # Resolution validation testi
        assert validate_resolution("1296x972") == (1296, 972)
        assert validate_resolution("invalid") == CameraConfig.DEFAULT_RESOLUTION

        # Distance formatting testi
        assert format_distance(50.5) == "50.5 cm"
        assert format_distance(150) == "1.5 m"
        assert format_distance(None) == "Okuma Hatası"

        # 3D position testi (130° FOV ile)
        x, y, z = calculate_3d_position_with_fov(90, 100, 130, 0)
        assert abs(y) < 1  # 90 derece yaklaşık x ekseni

        # GPIO validation testi
        assert validate_gpio_pin(26) == True
        assert validate_gpio_pin(35) == False

        logger.info("✓ Utils modülü self-test başarılı")

    except AssertionError as e:
        logger.error(f"✗ Self-test başarısız: {e}")
        tests_passed = False

    return tests_passed


# Global instances
frame_buffer = FrameBuffer(size=CameraConfig.FRAME_BUFFER_SIZE)
image_processor = ImageProcessor()
store_manager = StoreManager()
performance_monitor = PerformanceMonitor()

# Circuit breakers
camera_circuit_breaker = CircuitBreaker(
    failure_threshold=AppConfig.CIRCUIT_FAILURE_THRESHOLD,
    recovery_timeout=AppConfig.CIRCUIT_RECOVERY_TIMEOUT
)

# Modül yüklendiğinde
if __name__ != "__main__":
    logger.info("Utils modülü yüklendi (OV5647 130° desteği aktif)")
    if CameraConfig.ENABLE_LENS_CORRECTION:
        logger.info("Lens distorsiyon düzeltme aktif")
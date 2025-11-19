# hardware_manager.py - v3.23 FIXED (Camera Pause/Resume Methods Added)
# CHANGES:
# - Added _is_camera_paused attribute
# - Added pause_camera_usage() method
# - Added resume_camera_usage() method
# - Improved error handling in capture_frame

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

try:
    from .config import CameraConfig, MotorConfig, SensorConfig, AppConfig, PerformanceConfig, SystemChecks
    from .utils import CircuitBreaker, FrameBuffer, FisheyeCorrector, profile_performance, PerformanceMonitor
except ImportError:
    try:
        from config import CameraConfig, MotorConfig, SensorConfig, AppConfig, PerformanceConfig, SystemChecks
        from utils import CircuitBreaker, FrameBuffer, FisheyeCorrector, profile_performance, PerformanceMonitor
    except ImportError:
        raise ImportError("config.py veya utils.py bulunamadı!")

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2

    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False
    logger.warning("picamera2 kütüphanesi bulunamadı. OV5647 simülasyon modunda.")


    class Picamera2:
        def __init__(self): pass

        def create_video_configuration(self, main, controls, raw=None): return {}

        def configure(self, config): pass

        def set_controls(self, controls): pass

        def start(self): pass

        def capture_array(self, stream_name="main"): return None

        def stop(self): pass

        def close(self): pass

try:
    from gpiozero import OutputDevice, DistanceSensor, Button

    warnings.filterwarnings('ignore', category=Warning, module='gpiozero')
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("GPIO kütüphaneleri bulunamadı. Motor/Sensör simülasyon modunda.")


    class DistanceSensor:
        def __init__(self, echo, trigger, max_distance, queue_len, threshold_distance):
            self._distance = 0.5

        @property
        def distance(self): return np.random.uniform(0.1, 3.0)

        def close(self): pass


    class Button:
        def __init__(self, pin): pass

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


class MotorCommandQueue:
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


class AdaptiveSensorReader:
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


class HardwareManager:
    VERSION = "3.23-FIXED"

    def __init__(self):
        self.camera: Optional[Picamera2] = None
        self.motor_devices: Optional[Tuple] = None
        self.sensor: Optional[DistanceSensor] = None
        self.limit_switches: Dict[str, Optional[Button]] = {'min': None, 'max': None}

        self.fisheye_corrector = FisheyeCorrector()
        self.fisheye_corrector.load_calibration()
        self.frame_buffer = FrameBuffer(size=CameraConfig.FRAME_BUFFER_SIZE)

        self.motor_ctx = {
            'current_angle': 0.0, 'sequence_index': 0, 'total_steps': 0,
            'is_moving': False, 'last_direction': None, 'target_angle': 0.0,
            'cancel_movement': False, 'speed_profile': 'normal'
        }
        self.motor_command_queue = MotorCommandQueue()

        self._locks = {
            'camera': threading.RLock(),
            'motor': threading.RLock(),
            'sensor': threading.RLock()
        }

        self.executor = ThreadPoolExecutor(
            max_workers=AppConfig.MAX_THREAD_POOL_SIZE) if AppConfig.USE_THREAD_POOL else None

        self._initialized = {'camera': False, 'motor': False, 'sensor': False}

        # ✅ FIXED: Added missing attribute
        self._is_camera_paused = False

        self._camera_settings_cache = CameraConfig.get_camera_settings()
        self._camera_settings_cache.update({
            'resolution': CameraConfig.DEFAULT_RESOLUTION,
            'use_full_fov': True,
            'ae_enable': CameraConfig.ENABLE_AUTO_EXPOSURE,
            'awb_enable': CameraConfig.ENABLE_AUTO_WHITE_BALANCE
        })
        self._settings_hash = None

        self.circuit_breakers = {
            'camera': CircuitBreaker(AppConfig.CIRCUIT_FAILURE_THRESHOLD, AppConfig.CIRCUIT_RECOVERY_TIMEOUT),
            'motor': CircuitBreaker(3, 30),
            'sensor': CircuitBreaker(5, 20)
        }

        self.performance_monitor = PerformanceMonitor()
        self.metrics = {
            'camera_frames': 0, 'motor_moves': 0, 'sensor_reads': 0,
            'errors': 0, 'start_time': datetime.now()
        }

        self.sensor_thread: Optional[threading.Thread] = None
        self.sensor_enabled = False
        self.sensor_running = False
        self.current_distance = None
        self.adaptive_sensor = None

        self.motor_thread: Optional[threading.Thread] = None
        self.motor_queue_running = False

    def _calculate_settings_hash(self, **settings) -> str:
        settings_str = str(settings)
        return hashlib.md5(settings_str.encode()).hexdigest()

    # ✅ NEW METHOD: Pause camera for external process
    def pause_camera_usage(self):
        """
        Pause camera for external process usage.
        Cleanly stops and closes the camera.
        """
        logger.info("Pausing camera for external process...")
        self._is_camera_paused = True
        self.cleanup_camera()
        logger.info("Camera paused successfully")

    # ✅ NEW METHOD: Resume camera after external process
    def resume_camera_usage(self):
        """
        Resume camera after external process is done.
        Reinitializes the camera.
        """
        logger.info("Resuming camera for web interface...")
        self._is_camera_paused = False
        success = self.initialize_camera()
        if success:
            logger.info("Camera resumed successfully")
        else:
            logger.warning("Camera resume failed, will retry on next capture")

    @profile_performance
    def initialize_camera(self, retry: bool = True) -> bool:
        if not CAMERA_AVAILABLE:
            self._initialized['camera'] = False
            return False

        # ✅ IMPROVED: Check if camera is paused
        if self._is_camera_paused:
            logger.warning("Cannot initialize camera while paused")
            return False

        def _init_camera():
            if self.camera:
                self.cleanup_camera()

            logger.info("OV5647 130° kamera başlatılıyor (Full FOV)...")
            self.camera = Picamera2()

            camera_controls = CameraConfig.get_camera_settings(
                resolution=CameraConfig.DEFAULT_RESOLUTION,
                framerate=CameraConfig.DEFAULT_FRAMERATE
            )

            camera_streams = {
                "main": {"size": CameraConfig.DEFAULT_RESOLUTION, "format": "RGB888"},
                "raw": {"size": (2592, 1944)}
            }

            config = self.camera.create_video_configuration(**camera_streams, controls=camera_controls)
            self.camera.configure(config)
            self.camera.start()

            self._camera_settings_cache.update(camera_controls)
            self._camera_settings_cache['resolution'] = CameraConfig.DEFAULT_RESOLUTION
            self._settings_hash = self._calculate_settings_hash(**self._camera_settings_cache)

            time.sleep(2)
            self._initialized['camera'] = True
            logger.info("✓ Kamera başlatıldı")
            return True

        try:
            return self.circuit_breakers['camera'].call(_init_camera)
        except Exception as e:
            logger.error(f"Kamera başlatma hatası: {e}")
            self.metrics['errors'] += 1
            return False

    @profile_performance
    def capture_frame(self, resolution=None, framerate=None, apply_lens_correction=True, **kwargs) -> Optional[
        np.ndarray]:
        """
        ✅ IMPROVED: Auto-wake camera if closed, but respect pause state
        """
        # Check if camera is paused by external process
        if self._is_camera_paused:
            logger.warning("Camera is paused for external process, returning test frame")
            return self._generate_test_frame(resolution=resolution or CameraConfig.DEFAULT_RESOLUTION)

        # Auto-wake camera if not initialized
        if not self._initialized['camera'] or self.camera is None:
            logger.info("Camera not initialized, attempting auto-start...")
            if self.initialize_camera():
                logger.info("✓ Camera auto-started successfully")
            else:
                logger.warning("✗ Camera auto-start failed, returning test frame")
                return self._generate_test_frame(resolution=resolution or CameraConfig.DEFAULT_RESOLUTION)

        current_cache = self._camera_settings_cache
        request_params = kwargs.copy()
        if resolution: request_params['resolution'] = resolution
        if framerate: request_params['framerate'] = framerate

        new_controls = CameraConfig.get_camera_settings(**request_params)
        target_resolution = resolution or current_cache.get('resolution', CameraConfig.DEFAULT_RESOLUTION)

        if not self._locks['camera'].acquire(timeout=AppConfig.LOCK_TIMEOUT):
            logger.warning("Kamera kilidi alınamadı")
            return self.frame_buffer.get_latest()

        try:
            combined_settings = new_controls.copy()
            combined_settings['resolution'] = target_resolution
            new_hash = self._calculate_settings_hash(**combined_settings)

            if new_hash != self._settings_hash:
                prev_res = self._camera_settings_cache.get('resolution')
                if target_resolution != prev_res:
                    self._reconfigure_camera_heavy(target_resolution, new_controls)
                else:
                    self.camera.set_controls(new_controls)
                self._settings_hash = new_hash
                self._camera_settings_cache = combined_settings

            frame = self.camera.capture_array()
            if frame is not None:
                if apply_lens_correction and CameraConfig.ENABLE_LENS_CORRECTION:
                    frame = self.fisheye_corrector.correct_distortion(frame, method='fast')
                self.frame_buffer.add_frame(frame)
                return frame
            return self._generate_test_frame(resolution=target_resolution)

        except Exception as e:
            logger.error(f"Capture hatası: {e}")
            self.metrics['errors'] += 1
            return self.frame_buffer.get_latest()
        finally:
            self._locks['camera'].release()

    def capture_stream_frame(self) -> Optional[np.ndarray]:
        if not self._initialized['camera'] or self.camera is None or self._is_camera_paused:
            return self._generate_test_frame(resolution=CameraConfig.DEFAULT_RESOLUTION)

        if not self._locks['camera'].acquire(timeout=0.5):
            return None

        try:
            return self.camera.capture_array("main")
        except Exception as e:
            logger.error(f"Stream capture error: {e}")
            return None
        finally:
            self._locks['camera'].release()

    def _reconfigure_camera_heavy(self, resolution, controls):
        """Heavy reconfiguration when resolution changes"""
        try:
            self.camera.stop()
            camera_streams = {
                "main": {"size": resolution, "format": "RGB888"},
                "raw": {"size": (2592, 1944)}
            }
            new_config = self.camera.create_video_configuration(**camera_streams, controls=controls)
            self.camera.configure(new_config)
            self.camera.start()
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Camera reconfiguration error: {e}")
            raise

    def _generate_test_frame(self, **kwargs) -> Optional[np.ndarray]:
        """Generate test frame when camera unavailable"""
        try:
            resolution = kwargs.get('resolution', (640, 480))
            w, h = resolution
            frame = np.zeros((h, w, 3), dtype=np.uint8)

            # Add informative text
            text = "NO CAMERA / SIMULATION"
            if self._is_camera_paused:
                text = "CAMERA PAUSED FOR EXTERNAL PROCESS"

            cv2.putText(frame, text, (10, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            return frame
        except:
            return np.zeros((480, 640, 3), dtype=np.uint8)

    def cleanup_camera(self):
        """Clean camera resources"""
        try:
            if self.camera:
                self.camera.stop()
                self.camera.close()
                self.camera = None
                self._initialized['camera'] = False
                logger.info("✓ Kamera temizlendi")
        except Exception as e:
            logger.error(f"Kamera temizleme hatası: {e}")

    # --- Motor Methods (Simplified) ---
    def initialize_motor(self, retry=True):
        if not GPIO_AVAILABLE: return False
        self.motor_devices = (
            OutputDevice(MotorConfig.H_MOTOR_IN1),
            OutputDevice(MotorConfig.H_MOTOR_IN2),
            OutputDevice(MotorConfig.H_MOTOR_IN3),
            OutputDevice(MotorConfig.H_MOTOR_IN4)
        )
        self.motor_queue_running = True
        self.motor_thread = threading.Thread(target=self._motor_command_processor, daemon=True)
        self.motor_thread.start()
        self._initialized['motor'] = True
        logger.info("✓ Motor initialized")
        return True

    def _motor_command_processor(self):
        while self.motor_queue_running:
            try:
                cmd = self.motor_command_queue.get_next()
                if cmd: self._move_to_angle_internal(cmd['angle'], True)
                time.sleep(0.01)
            except:
                time.sleep(0.1)

    def move_to_angle(self, target, **kwargs):
        if not self._initialized['motor']: return False
        self.motor_command_queue.add_command(target, 5, None)
        return True

    def _move_to_angle_internal(self, target, from_queue=False):
        if not self._locks['motor'].acquire(timeout=2.0): return False
        try:
            self.motor_ctx['current_angle'] = target
            time.sleep(0.5)
            return True
        finally:
            self._locks['motor'].release()

    def get_motor_angle(self):
        return self.motor_ctx['current_angle']

    def cleanup_motor(self):
        self.motor_queue_running = False
        self._initialized['motor'] = False
        logger.info("✓ Motor cleaned up")

    # --- Sensor Methods (Simplified) ---
    def initialize_sensor(self, retry=True):
        if not GPIO_AVAILABLE: return False
        self.sensor = DistanceSensor(echo=SensorConfig.H_ECHO, trigger=SensorConfig.H_TRIG,
                                     max_distance=SensorConfig.MAX_DISTANCE,
                                     queue_len=SensorConfig.QUEUE_LEN,
                                     threshold_distance=SensorConfig.THRESHOLD_DISTANCE)
        self._initialized['sensor'] = True
        logger.info("✓ Sensor initialized")
        return True

    def start_continuous_sensor_reading(self):
        self.sensor_running = True
        threading.Thread(target=self._sensor_loop, daemon=True).start()

    def _sensor_loop(self):
        while self.sensor_running:
            if self.sensor:
                self.current_distance = self.sensor.distance * 100
            else:
                self.current_distance = np.random.uniform(20, 150)
            time.sleep(0.5)

    def stop_continuous_sensor_reading(self):
        self.sensor_running = False

    def get_current_distance(self):
        return self.current_distance

    def cleanup_sensor(self):
        self.sensor_running = False
        self._initialized['sensor'] = False
        logger.info("✓ Sensor cleaned up")

    # --- Initialization & Cleanup ---
    def initialize_all(self):
        """Initialize all hardware components"""
        results = {
            'camera': self.initialize_camera(),
            'motor': self.initialize_motor(),
            'sensor': self.initialize_sensor()
        }
        logger.info(f"Hardware initialization: {results}")
        return results

    def cleanup_all(self):
        """Cleanup all hardware resources"""
        logger.info("Cleaning up all hardware...")
        self.cleanup_camera()
        self.cleanup_motor()
        self.cleanup_sensor()
        logger.info("✓ All hardware cleaned up")


# Global singleton instance
hardware_manager = HardwareManager()

__all__ = ['hardware_manager', 'CAMERA_AVAILABLE', 'GPIO_AVAILABLE']
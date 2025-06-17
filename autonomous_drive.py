# autonomous_drive.py - Otonom Sürüş ve Canlı Veri Kaydı Betiği

import os
import sys
import time
import logging
import atexit
import signal
import threading
import traceback
import math
from gpiozero import Motor, DistanceSensor, OutputDevice
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device

# --- TEMEL YAPILANDIRMA ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- DJANGO ENTEGRASYONU ---
try:
    sys.path.append(os.getcwd())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dreampi.settings')
    import django

    django.setup()
    from django.utils import timezone
    from scanner.models import Scan, ScanPoint

    logger = logging.getLogger(__name__)  # Django yüklendikten sonra logger'ı al
    logger.info("SensorScript: Django entegrasyonu başarılı.")
except Exception as e:
    logging.error(f"SensorScript: Django entegrasyonu BAŞARISIZ: {e}", exc_info=True)
    sys.exit(1)

try:
    Device.pin_factory = PiGPIOFactory()
    logger.info("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    logger.warning(f"pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

# --- SABİTLER ve PINLER ---
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'
MOTOR_LEFT_FORWARD, MOTOR_LEFT_BACKWARD = 10, 9
MOTOR_RIGHT_FORWARD, MOTOR_RIGHT_BACKWARD = 8, 7
FRONT_SCAN_MOTOR_IN1, FRONT_SCAN_MOTOR_IN2, FRONT_SCAN_MOTOR_IN3, FRONT_SCAN_MOTOR_IN4 = 21, 20, 16, 12
REAR_MIRROR_MOTOR_IN1, REAR_MIRROR_MOTOR_IN2, REAR_MIRROR_MOTOR_IN3, REAR_MIRROR_MOTOR_IN4 = 26, 19, 13, 6
TRIG_PIN_1, ECHO_PIN_1 = 23, 24

# --- PARAMETRELER ---
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
MOVE_DURATION, TURN_DURATION = 1.0, 0.4
OBSTACLE_DISTANCE_CM = 35

# --- GLOBAL NESNELER ---
left_motors: Motor = None;
right_motors: Motor = None;
sensor: DistanceSensor = None
rear_mirror_motor_devices: tuple = None;
front_scan_motor_devices: tuple = None
rear_mirror_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
front_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]
stop_event = threading.Event()
current_scan_object_global: Scan = None
script_exit_status_global = Scan.Status.ERROR


# --- SÜREÇ, KAYNAK ve DB YÖNETİMİ ---
def signal_handler(sig, frame):
    global script_exit_status_global
    logging.warning("Durdurma sinyali alındı. Program sonlandırılıyor...")
    script_exit_status_global = Scan.Status.INTERRUPTED
    stop_event.set()


def create_pid_file():
    try:
        with open(AUTONOMOUS_SCRIPT_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def cleanup_on_exit():
    logging.info("Program sonlanıyor. Kaynaklar temizleniyor...")
    stop_event.set()
    if current_scan_object_global and current_scan_object_global.status == Scan.Status.RUNNING:
        current_scan_object_global.status = script_exit_status_global
        current_scan_object_global.end_time = timezone.now()
        current_scan_object_global.save()
    stop_motors()
    if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE): os.remove(AUTONOMOUS_SCRIPT_PID_FILE)


def setup_hardware():
    global left_motors, right_motors, sensor, rear_mirror_motor_devices, front_scan_motor_devices
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)
    sensor = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1)
    rear_mirror_motor_devices = (OutputDevice(REAR_MIRROR_MOTOR_IN1), OutputDevice(REAR_MIRROR_MOTOR_IN2),
                                 OutputDevice(REAR_MIRROR_MOTOR_IN3), OutputDevice(REAR_MIRROR_MOTOR_IN4))
    front_scan_motor_devices = (OutputDevice(FRONT_SCAN_MOTOR_IN1), OutputDevice(FRONT_SCAN_MOTOR_IN2),
                                OutputDevice(FRONT_SCAN_MOTOR_IN3), OutputDevice(FRONT_SCAN_MOTOR_IN4))
    logging.info("Tüm donanım nesneleri başarıyla oluşturuldu.")


def create_scan_entry():
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())
        current_scan_object_global = Scan.objects.create(status=Scan.Status.RUNNING)
        logger.info(f"Otonom sürüş için yeni tarama kaydı oluşturuldu: ID {current_scan_object_global.id}")
        return True
    except Exception as e:
        logger.error(f"DB Hatası (create_scan_entry): {e}", exc_info=True)
        return False


# --- HAREKET VE TARAMA FONKSİYONLARI ---
def move_forward(): logging.info("İleri Gidiliyor..."); left_motors.forward(); right_motors.forward(); time.sleep(
    MOVE_DURATION); stop_motors()


def move_backward(): logging.info("Geri Gidiliyor..."); left_motors.backward(); right_motors.backward(); time.sleep(
    MOVE_DURATION); stop_motors()


def turn_left(): logging.info("Sola Dönülüyor..."); left_motors.backward(); right_motors.forward(); time.sleep(
    TURN_DURATION); stop_motors()


def turn_right(): logging.info("Sağa Dönülüyor..."); left_motors.forward(); right_motors.backward(); time.sleep(
    TURN_DURATION); stop_motors()


def stop_motors(): logging.info("Tekerlek Motorları Durduruldu."); left_motors.stop(); right_motors.stop()


def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    motor_devices[0].value, motor_devices[1].value, motor_devices[2].value, motor_devices[3].value = bool(s1), bool(
        s2), bool(s3), bool(s4)


def _step_motor(motor_devices, motor_ctx, num_steps, direction_positive):
    step_increment = 1 if direction_positive else -1
    for _ in range(int(num_steps)):
        if stop_event.is_set(): break
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']]);
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_step_motor_to_angle(motor_devices, motor_ctx, target_angle_deg):
    deg_per_step = 360.0 / STEPS_PER_REVOLUTION;
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step: return
    num_steps = round(abs(angle_diff) / deg_per_step);
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0))
    if not stop_event.is_set(): motor_ctx['current_angle'] = target_angle_deg


def save_scan_point(pan_angle, tilt_angle, distance):
    """Hesaplanan noktayı veritabanına kaydeder."""
    if distance <= 0 or distance == float('inf'): return

    angle_pan_rad = math.radians(pan_angle)
    angle_tilt_rad = math.radians(tilt_angle)

    h_radius = distance * math.cos(angle_tilt_rad)
    z = distance * math.sin(angle_tilt_rad)
    x = h_radius * math.cos(angle_pan_rad)
    y = h_radius * math.sin(angle_pan_rad)

    ScanPoint.objects.create(
        scan=current_scan_object_global,
        derece=pan_angle, dikey_aci=tilt_angle,
        mesafe_cm=distance, x_cm=x, y_cm=y, z_cm=z,
        timestamp=timezone.now()
    )


def perform_scan(motor_devices, motor_ctx, scan_angles, is_front_scan):
    measurements = {}
    for angle in scan_angles:
        if stop_event.is_set(): break
        move_step_motor_to_angle(motor_devices, motor_ctx, angle)
        time.sleep(0.1)
        distance = sensor.distance * 100 if sensor.distance else float('inf')
        measurements[angle] = distance

        # Veritabanına kaydet
        if is_front_scan:
            # Ön tarama için, dikey motor hareket ediyor, yatay sabit (0)
            save_scan_point(pan_angle=0, tilt_angle=angle, distance=distance)
        else:  # Arka tarama
            # Arka tarama için, yatay motor hareket ediyor, dikey sabit (0)
            save_scan_point(pan_angle=angle, tilt_angle=0, distance=distance)

        logging.info(f"  Tarama: Açı={angle}°, Mesafe={distance:.1f} cm")
    move_step_motor_to_angle(motor_devices, motor_ctx, 0)
    return measurements


# --- ANA ÇALIŞMA DÖNGÜSÜ ---
def main():
    atexit.register(cleanup_on_exit);
    signal.signal(signal.SIGTERM, signal_handler);
    signal.signal(signal.SIGINT, signal_handler);
    create_pid_file()

    try:
        setup_hardware()
        if not create_scan_entry(): sys.exit(1)

        move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 0)
        move_step_motor_to_angle(front_scan_motor_devices, front_scan_motor_ctx, 0)

        logging.info("Otonom sürüş modu başlatıldı...")

        while not stop_event.is_set():
            logging.info("\n--- YENİ DÖNGÜ: En Uygun Yolu Bul ve İlerle ---")
            stop_motors()

            logging.info("1. Ön Taraf Taranıyor...")
            front_scan_data = perform_scan(front_scan_motor_devices, front_scan_motor_ctx, [-60, 0, 60],
                                           is_front_scan=True)
            if stop_event.is_set(): break

            safe_paths = {angle: dist for angle, dist in front_scan_data.items() if dist > OBSTACLE_DISTANCE_CM}

            if not safe_paths:
                logging.warning("Önde güvenli bir yol bulunamadı! Arka taraf kontrol ediliyor...")
                rear_scan_data = perform_scan(rear_mirror_motor_devices, rear_mirror_motor_ctx, [180],
                                              is_front_scan=False)
                if rear_scan_data.get(180, 0) > OBSTACLE_DISTANCE_CM:
                    logging.info("Karar: Arka taraf açık. Geri gidilecek.")
                    move_backward()
                else:
                    logging.error("SIKIŞTI! Hem ön hem arka taraf kapalı. İşlem durduruluyor.")
                    script_exit_status_global = Scan.Status.COMPLETED
                    break
            else:
                best_angle = max(safe_paths, key=safe_paths.get)
                logging.info(f"Karar: En uygun yol {best_angle}° yönünde. Mesafe: {safe_paths[best_angle]:.1f} cm")

                if best_angle < -15:
                    turn_left()
                elif best_angle > 15:
                    turn_right()
                move_forward()

            time.sleep(1)

        if not stop_event.is_set():  # Eğer döngü normal bittiyse (sıkıştığı için)
            script_exit_status_global = Scan.Status.COMPLETED

    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        print("\nProgram kullanıcı tarafından sonlandırıldı (CTRL+C).")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        logging.error(f"KRİTİK BİR HATA OLUŞTU: {e}", exc_info=True)
    finally:
        logging.info("Ana döngüden çıkıldı.")


if __name__ == '__main__':
    main()

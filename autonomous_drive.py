# autonomous_drive.py - Tepkisel ve Akıllı Navigasyon Betiği

import os
import sys
import time
import logging
import atexit
import signal
import threading
import traceback  # DÜZELTME: Eksik olan import eklendi
from gpiozero import Motor, DistanceSensor, OutputDevice
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device

# --- TEMEL YAPILANDIRMA ---
try:
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SABİTLER ---
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'

# --- DONANIM PIN TANIMLAMALARI (GÖREVE GÖRE İSİMLENDİRİLMİŞ) ---
# L298N Motor Sürücü Pinleri
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# Fiziksel olarak DİKEY duran ve ÖN TARAFI TARAYAN motorun pinleri
FRONT_SCAN_MOTOR_IN1, FRONT_SCAN_MOTOR_IN2, FRONT_SCAN_MOTOR_IN3, FRONT_SCAN_MOTOR_IN4 = 26, 19, 13, 6
# Fiziksel olarak YATAY duran ve ARKAYI KONTROL EDEN motorun pinleri
REAR_MIRROR_MOTOR_IN1, REAR_MIRROR_MOTOR_IN2, REAR_MIRROR_MOTOR_IN3, REAR_MIRROR_MOTOR_IN4 = 21, 20, 16, 12

# Ultrasonik Sensör Pinleri
TRIG_PIN_1, ECHO_PIN_1 = 23, 24

# --- PARAMETRELER ---
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
MOVE_DURATION = 1.0
TURN_DURATION = 0.4
OBSTACLE_DISTANCE_CM = 35
REAR_TRIGGER_DISTANCE_CM = 20

# --- GLOBAL NESNELER ---
left_motors: Motor = None
right_motors: Motor = None
sensor: DistanceSensor = None
rear_mirror_motor_devices: tuple = None
front_scan_motor_devices: tuple = None
rear_mirror_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
front_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]

stop_event = threading.Event()


# --- SÜREÇ, DONANIM VE HAREKET FONKSİYONLARI ---
def signal_handler(sig, frame):
    logging.warning("Durdurma sinyali (SIGTERM) alındı. Program güvenli bir şekilde sonlandırılıyor...")
    stop_event.set()


def create_pid_file():
    try:
        with open(AUTONOMOUS_SCRIPT_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logging.info(f"Otonom sürüş PID dosyası oluşturuldu: {os.getpid()}")
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def cleanup_on_exit():
    logging.info("Program sonlanıyor. Tüm kaynaklar temizleniyor...")
    try:
        if left_motors: left_motors.stop()
        if right_motors: right_motors.stop()
        if rear_mirror_motor_devices: _set_motor_pins(rear_mirror_motor_devices, 0, 0, 0, 0)
        if front_scan_motor_devices: _set_motor_pins(front_scan_motor_devices, 0, 0, 0, 0)
    except Exception as e:
        logging.error(f"Motorlar durdurulurken hata: {e}")
    finally:
        if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE):
            os.remove(AUTONOMOUS_SCRIPT_PID_FILE)
            logging.info("Otonom sürüş PID dosyası temizlendi.")
        logging.info("Temizleme tamamlandı.")


def setup_hardware():
    global left_motors, right_motors, sensor, rear_mirror_motor_devices, front_scan_motor_devices
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)
    sensor = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1)

    # DÜZELTME: Değişken adları, dosyanın en üstündeki tanımlarla eşleşecek şekilde düzeltildi.
    rear_mirror_motor_devices = (OutputDevice(REAR_MIRROR_MOTOR_IN1), OutputDevice(REAR_MIRROR_MOTOR_IN2),
                                 OutputDevice(REAR_MIRROR_MOTOR_IN3), OutputDevice(REAR_MIRROR_MOTOR_IN4))
    front_scan_motor_devices = (OutputDevice(FRONT_SCAN_MOTOR_IN1), OutputDevice(FRONT_SCAN_MOTOR_IN2),
                                OutputDevice(FRONT_SCAN_MOTOR_IN3), OutputDevice(FRONT_SCAN_MOTOR_IN4))

    logging.info("Tüm donanım nesneleri başarıyla oluşturuldu.")


def move_forward():
    logging.info("İleri Gidiliyor...")
    left_motors.forward();
    right_motors.forward();
    time.sleep(MOVE_DURATION);
    stop_motors()


def turn_left():
    logging.info("Sola Dönülüyor...");
    left_motors.backward();
    right_motors.forward();
    time.sleep(TURN_DURATION);
    stop_motors()


def turn_right():
    logging.info("Sağa Dönülüyor...");
    left_motors.forward();
    right_motors.backward();
    time.sleep(TURN_DURATION);
    stop_motors()


def stop_motors():
    logging.info("Tekerlek Motorları Durduruldu.");
    left_motors.stop();
    right_motors.stop()


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
    deg_per_step = 360.0 / STEPS_PER_REVOLUTION
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step: return
    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0))
    if not stop_event.is_set():
        motor_ctx['current_angle'] = target_angle_deg


def check_rear_trigger():
    move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 180)
    if stop_event.is_set(): return False
    time.sleep(0.1)
    distance = sensor.distance * 100 if sensor.distance else float('inf')
    logging.info(f"Arka kontrol: Mesafe={distance:.1f} cm")
    move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 0)
    return distance < REAR_TRIGGER_DISTANCE_CM


def perform_front_scan():
    logging.info("Ön taraf taranıyor...")
    scan_angles = [-60, -30, 0, 30, 60]
    measurements = {}
    for angle in scan_angles:
        if stop_event.is_set(): break
        move_step_motor_to_angle(front_scan_motor_devices, front_scan_motor_ctx, angle)
        time.sleep(0.1)
        distance = sensor.distance * 100 if sensor.distance else float('inf')
        measurements[angle] = distance
        logging.info(f"  Ön Tarama: Açı={angle}°, Mesafe={distance:.1f} cm")
    move_step_motor_to_angle(front_scan_motor_devices, front_scan_motor_ctx, 0)
    return measurements


def find_best_path(front_scan):
    safe_options = {angle: dist for angle, dist in front_scan.items() if dist > OBSTACLE_DISTANCE_CM}
    if not safe_options:
        logging.warning("Önde hareket edecek güvenli bir yol bulunamadı.")
        return None
    best_angle = max(safe_options, key=safe_options.get)
    logging.info(f"Karar: En uygun yol {best_angle}° yönünde. Mesafe: {safe_options[best_angle]:.1f} cm")
    return best_angle


def main():
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGTERM, signal_handler)
    create_pid_file()

    try:
        setup_hardware()
        move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 0)
        move_step_motor_to_angle(front_scan_motor_devices, front_scan_motor_ctx, 0)

        logging.info("Otonom sürüş modu başlatıldı. Arkadan bir nesne yaklaştırılması bekleniyor...")

        while not stop_event.is_set():
            if check_rear_trigger():
                if stop_event.is_set(): break
                logging.info("Tetikleyici algılandı! Hareket döngüsü başlıyor...")
                front_scan_data = perform_front_scan()
                if stop_event.is_set(): break
                best_path_angle = find_best_path(front_scan_data)

                if best_path_angle is not None:
                    if best_path_angle < -15:
                        turn_left()
                    elif best_path_angle > 15:
                        turn_right()
                    move_forward()
                else:
                    logging.warning("Ön taraf kapalı, hareket edilemiyor.")
                    stop_motors()
                    time.sleep(2)
            else:
                stop_motors()
                logging.info("Arkada tetikleyici bekleniyor...")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nProgram kullanıcı tarafından sonlandırıldı (CTRL+C).")
    except Exception as e:
        logging.error(f"KRİTİK BİR HATA OLUŞTU: {e}")
        traceback.print_exc()
    finally:
        logging.info("Ana döngüden çıkıldı.")


if __name__ == '__main__':
    main()

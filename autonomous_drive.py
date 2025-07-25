# autonomous_drive.py - Proaktif ve Akıllı Navigasyon Betiği (PWM Hız Kontrolü ile)

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
try:
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SABİTLER ---
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'

# --- DONANIM PIN TANIMLAMALARI ---
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7
FRONT_SCAN_MOTOR_IN1, FRONT_SCAN_MOTOR_IN2, FRONT_SCAN_MOTOR_IN3, FRONT_SCAN_MOTOR_IN4 = 26, 19, 13, 6
REAR_MIRROR_MOTOR_IN1, REAR_MIRROR_MOTOR_IN2, REAR_MIRROR_MOTOR_IN3, REAR_MIRROR_MOTOR_IN4 = 21, 20, 16, 12
TRIG_PIN_1, ECHO_PIN_1 = 23, 24

# --- PARAMETRELER ---
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
MOVE_DURATION = 1.0  # saniye
TURN_DURATION = 0.5  # saniye
OBSTACLE_DISTANCE_CM = 35
INVERT_REAR_MOTOR_DIRECTION = True

# DÜZELTME: PWM için hız ayarları eklendi (0.0 ile 1.0 arası)
MOVE_SPEED = 0.7  # İleri/geri hareket hızı (%70 güç)
TURN_SPEED = 0.6  # Dönüş hızı (%60 güç)

# --- GLOBAL NESNELER ---
left_motors: Motor = None;
right_motors: Motor = None;
sensor: DistanceSensor = None
rear_mirror_motor_devices: tuple = None;
front_scan_motor_devices: tuple = None
rear_mirror_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
front_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]
stop_event = threading.Event()


# --- SÜREÇ, DONANIM VE HAREKET FONKSİYONLARI ---
def signal_handler(sig, frame): stop_event.set()


def create_pid_file():
    try:
        with open(AUTONOMOUS_SCRIPT_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def cleanup_on_exit():
    logging.info("Program sonlanıyor...");
    stop_event.set()
    try:
        if left_motors: left_motors.stop()
        if right_motors: right_motors.stop()
        stop_step_motors()
    except Exception as e:
        logging.error(f"Donanım durdurulurken hata: {e}")
    finally:
        if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE): os.remove(AUTONOMOUS_SCRIPT_PID_FILE)
        logging.info("Temizleme tamamlandı.")


def setup_hardware():
    global left_motors, right_motors, sensor, rear_mirror_motor_devices, front_scan_motor_devices
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD);
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)
    sensor = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1)
    rear_mirror_motor_devices = (OutputDevice(REAR_MIRROR_MOTOR_IN1), OutputDevice(REAR_MIRROR_MOTOR_IN2),
                                 OutputDevice(REAR_MIRROR_MOTOR_IN3), OutputDevice(REAR_MIRROR_MOTOR_IN4))
    front_scan_motor_devices = (OutputDevice(FRONT_SCAN_MOTOR_IN1), OutputDevice(FRONT_SCAN_MOTOR_IN2),
                                OutputDevice(FRONT_SCAN_MOTOR_IN3), OutputDevice(FRONT_SCAN_MOTOR_IN4))
    logging.info("Tüm donanım nesneleri başarıyla oluşturuldu.")


# DÜZELTME: Hareket fonksiyonları artık hız parametresi alıyor
def move_forward():
    logging.info(f"İleri Gidiliyor (Hız: {MOVE_SPEED})...");
    left_motors.forward(speed=MOVE_SPEED)
    right_motors.forward(speed=MOVE_SPEED)
    time.sleep(MOVE_DURATION)
    stop_motors()


def move_backward():
    logging.info(f"Geri Gidiliyor (Hız: {MOVE_SPEED})...");
    left_motors.backward(speed=MOVE_SPEED)
    right_motors.backward(speed=MOVE_SPEED)
    time.sleep(MOVE_DURATION)
    stop_motors()


def turn_left():
    logging.info(f"Sola Dönülüyor (Hız: {TURN_SPEED})...");
    left_motors.backward(speed=TURN_SPEED)
    right_motors.forward(speed=TURN_SPEED)
    time.sleep(TURN_DURATION)
    stop_motors()


def turn_right():
    logging.info(f"Sağa Dönülüyor (Hız: {TURN_SPEED})...");
    left_motors.forward(speed=TURN_SPEED)
    right_motors.backward(speed=TURN_SPEED)
    time.sleep(TURN_DURATION)
    stop_motors()


def stop_motors(): logging.info("Tekerlek Motorları Durduruldu."); left_motors.stop(); right_motors.stop()


def stop_step_motors():
    if rear_mirror_motor_devices: _set_motor_pins(rear_mirror_motor_devices, 0, 0, 0, 0)
    if front_scan_motor_devices: _set_motor_pins(front_scan_motor_devices, 0, 0, 0, 0)


def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    motor_devices[0].value, motor_devices[1].value, motor_devices[2].value, motor_devices[3].value = bool(s1), bool(
        s2), bool(s3), bool(s4)


def _step_motor(motor_devices, motor_ctx, num_steps, direction_positive, invert_direction=False):
    step_increment = 1 if direction_positive else -1
    if invert_direction: step_increment *= -1
    for _ in range(int(num_steps)):
        if stop_event.is_set(): break
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']]);
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_step_motor_to_angle(motor_devices, motor_ctx, target_angle_deg, invert_direction=False):
    deg_per_step = 360.0 / STEPS_PER_REVOLUTION
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step: return
    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0), invert_direction)
    if not stop_event.is_set(): motor_ctx['current_angle'] = target_angle_deg


def perform_front_scan():
    logging.info("Ön taraf taranıyor...")
    scan_angles = [90, 0, -90]
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


def check_rear():
    logging.info("Arka taraf kontrol ediliyor ('Dikiz Aynası')...")
    move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 180, INVERT_REAR_MOTOR_DIRECTION)
    if stop_event.is_set(): return 0
    time.sleep(0.1)
    distance = sensor.distance * 100 if sensor.distance else float('inf')
    logging.info(f"  Arka Tarama: Mesafe={distance:.1f} cm")
    move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 0, INVERT_REAR_MOTOR_DIRECTION)
    return distance


def analyze_and_decide(front_scan, rear_distance):
    logging.info("Tüm yönler analiz ediliyor...")
    all_options = {
        "TURN_RIGHT": front_scan.get(90, 0),
        "FORWARD": front_scan.get(0, 0),
        "TURN_LEFT": front_scan.get(-90, 0),
        "BACKWARD": rear_distance
    }
    logging.info(f"Tüm Yönler ve Mesafeler: {all_options}")
    safe_options = {direction: dist for direction, dist in all_options.items() if dist > OBSTACLE_DISTANCE_CM}
    if not safe_options:
        logging.warning("Tüm yönler kapalı veya engel mesafesinden yakın. Durulacak.")
        return "STOP"
    best_direction = max(safe_options, key=safe_options.get)
    logging.info(f"Karar: En uygun yol {best_direction} yönünde. Mesafe: {safe_options[best_direction]:.1f} cm")
    return best_direction


# --- ANA ÇALIŞMA DÖNGÜSÜ ---
def main():
    atexit.register(cleanup_on_exit);
    signal.signal(signal.SIGTERM, signal_handler);
    signal.signal(signal.SIGINT, signal_handler);
    create_pid_file()

    try:
        setup_hardware()
        move_step_motor_to_angle(rear_mirror_motor_devices, rear_mirror_motor_ctx, 0)
        move_step_motor_to_angle(front_scan_motor_devices, front_scan_motor_ctx, 0)

        logging.info("Otonom sürüş modu başlatıldı...")

        while not stop_event.is_set():
            logging.info("\n--- YENİ DÖNGÜ: En Uygun Yolu Bul ve İlerle ---")
            stop_motors()
            stop_step_motors()

            front_scan_data = perform_front_scan()
            if stop_event.is_set(): break
            rear_distance = check_rear()
            if stop_event.is_set(): break

            stop_step_motors()

            decision = analyze_and_decide(front_scan_data, rear_distance)

            if decision == "FORWARD":
                move_forward()
            elif decision == "BACKWARD":
                move_backward()
            elif decision == "TURN_LEFT":
                turn_left()
            elif decision == "TURN_RIGHT":
                turn_right()
            elif decision == "STOP":
                logging.error("SIKIŞTI! Hareket edecek güvenli bir yol yok. İşlem durduruluyor.")
                break

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

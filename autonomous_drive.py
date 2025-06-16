# autonomous_drive.py - Otonom Sürüş ve Engel Tespiti Betiği

import os
import sys
import time
import argparse
import logging
import atexit
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
# L298N Motor Sürücü Pinleri
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# Step Motor Pinleri
H_MOTOR_IN1, H_MOTOR_IN2, H_MOTOR_IN3, H_MOTOR_IN4 = 26, 19, 13, 6  # Yatay (Pan/Dikiz Aynası)
V_MOTOR_IN1, V_MOTOR_IN2, V_MOTOR_IN3, V_MOTOR_IN4 = 21, 20, 16, 12  # Dikey (Tilt/Ön Tarama)

# Ultrasonik Sensör Pinleri
TRIG_PIN_1, ECHO_PIN_1 = 23, 24

# --- PARAMETRELER ---
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
MOVE_DURATION = 1.0
TURN_DURATION = 0.5
OBSTACLE_DISTANCE_CM = 30

# --- GLOBAL NESNELER ---
left_motors: Motor = None
right_motors: Motor = None
sensor: DistanceSensor = None
h_motor_devices: tuple = None
v_motor_devices: tuple = None
h_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
v_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]


# --- PID YÖNETİMİ VE DONANIM KURULUMU ---
def create_pid_file():
    try:
        with open(AUTONOMOUS_SCRIPT_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logging.info(f"Otonom sürüş PID dosyası oluşturuldu: {os.getpid()}")
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def remove_pid_file():
    if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE):
        os.remove(AUTONOMOUS_SCRIPT_PID_FILE)
        logging.info("Otonom sürüş PID dosyası temizlendi.")


def setup_hardware():
    global left_motors, right_motors, sensor, h_motor_devices, v_motor_devices
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)
    sensor = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1)
    h_motor_devices = (OutputDevice(H_MOTOR_IN1), OutputDevice(H_MOTOR_IN2), OutputDevice(H_MOTOR_IN3),
                       OutputDevice(H_MOTOR_IN4))
    v_motor_devices = (OutputDevice(V_MOTOR_IN1), OutputDevice(V_MOTOR_IN2), OutputDevice(V_MOTOR_IN3),
                       OutputDevice(V_MOTOR_IN4))
    logging.info("Tüm donanım nesneleri başarıyla oluşturuldu.")


# --- DC MOTOR HAREKET FONKSİYONLARI ---
def move_forward():
    logging.info("İleri Gidiliyor...")
    left_motors.forward();
    right_motors.forward()
    time.sleep(MOVE_DURATION);
    stop_motors()


def move_backward():
    logging.info("Geri Gidiliyor...")
    left_motors.backward();
    right_motors.backward()
    time.sleep(MOVE_DURATION);
    stop_motors()


def turn_left():
    logging.info("Sola Dönülüyor...")
    left_motors.backward();
    right_motors.forward()
    time.sleep(TURN_DURATION);
    stop_motors()


def turn_right():
    logging.info("Sağa Dönülüyor...")
    left_motors.forward();
    right_motors.backward()
    time.sleep(TURN_DURATION);
    stop_motors()


def stop_motors():
    logging.info("Tekerlek Motorları Durduruldu.")
    left_motors.stop();
    right_motors.stop()


# --- STEP MOTOR TARAMA VE ANALİZ FONKSİYONLARI ---
def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    motor_devices[0].value, motor_devices[1].value, motor_devices[2].value, motor_devices[3].value = bool(s1), bool(
        s2), bool(s3), bool(s4)


def _step_motor(motor_devices, motor_ctx, num_steps, direction_positive):
    step_increment = 1 if direction_positive else -1
    for _ in range(int(num_steps)):
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_step_motor_to_angle(motor_devices, motor_ctx, target_angle_deg):
    deg_per_step = 360.0 / STEPS_PER_REVOLUTION
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step: return
    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0))
    motor_ctx['current_angle'] = target_angle_deg


def perform_quick_scan(motor_devices, motor_ctx, scan_angles):
    measurements = {}
    for angle in scan_angles:
        move_step_motor_to_angle(motor_devices, motor_ctx, angle)
        time.sleep(0.1)
        distance = sensor.distance * 100 if sensor.distance else float('inf')
        measurements[angle] = distance
        logging.info(f"  Tarama: Açı={angle}°, Mesafe={distance:.1f} cm")
    return measurements


def analyze_and_decide(front_scan, rear_scan):
    logging.info("Karar veriliyor...")
    front_left = front_scan.get(-45, 0);
    front_center = front_scan.get(0, 0);
    front_right = front_scan.get(45, 0)

    # DÜZELTME: Arka tarama verisi de artık karar sürecine dahil ediliyor.
    # Arka tarama açıları: 180 (tam arka)
    rear_center = rear_scan.get(180, 0)

    # Öncelik her zaman ileridir
    if front_center > OBSTACLE_DISTANCE_CM and front_center >= max(front_left, front_right):
        logging.info("Karar: En açık yol ÖNDE. İleri gidilecek.")
        return "FORWARD"
    elif front_right > OBSTACLE_DISTANCE_CM and front_right > front_left:
        logging.info("Karar: En açık yol SAĞDA. Sağa dönülecek.")
        return "TURN_RIGHT"
    elif front_left > OBSTACLE_DISTANCE_CM:
        logging.info("Karar: En açık yol SOLDA. Sola dönülecek.")
        return "TURN_LEFT"
    # Eğer ön taraf tamamen kapalıysa, arkaya bak
    elif rear_center > OBSTACLE_DISTANCE_CM:
        logging.info("Karar: Ön taraf kapalı, ARKA AÇIK. Geri gidilecek.")
        return "BACKWARD"
    else:
        logging.info("Karar: Tüm yönler kapalı. Durulacak.")
        return "STOP"


# --- ANA ÇALIŞMA DÖNGÜSÜ ---
def main():
    atexit.register(remove_pid_file)
    create_pid_file()

    setup_hardware()
    # Başlangıçta step motorları sıfırla
    move_step_motor_to_angle(h_motor_devices, h_motor_ctx, 0)
    move_step_motor_to_angle(v_motor_devices, v_motor_ctx, 0)

    try:
        while True:
            logging.info("\n--- YENİ DÖNGÜ: DUR-DÜŞÜN-HAREKET ET ---")
            stop_motors()

            # DÜŞÜN: Önü ve arkayı tara
            logging.info("1. Ön Taraf Taranıyor...")
            front_scan_data = perform_quick_scan(v_motor_devices, v_motor_ctx, [0, -45, 45, 0])

            logging.info("2. Arka Taraf Taranıyor ('Dikiz Aynası')...")
            # DÜZELTME: Arka tarama aktif hale getirildi (180 dereceye bakıp geri döner)
            rear_scan_data = perform_quick_scan(h_motor_devices, h_motor_ctx, [0, 180, 0])

            # Karar ver
            decision = analyze_and_decide(front_scan_data, rear_scan_data)

            # Kararı uygula
            if decision == "FORWARD":
                move_forward()
            elif decision == "BACKWARD":
                move_backward()  # Yeni hareket eklendi
            elif decision == "TURN_LEFT":
                turn_left()
            elif decision == "TURN_RIGHT":
                turn_right()
            elif decision == "STOP":
                logging.warning("Engel tespit edildi! Yardım bekleniyor...")
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nProgram kullanıcı tarafından sonlandırıldı.")
    finally:
        stop_motors()
        move_step_motor_to_angle(h_motor_devices, h_motor_ctx, 0)
        move_step_motor_to_angle(v_motor_devices, v_motor_ctx, 0)
        logging.info("Tüm işlemler durduruldu.")


if __name__ == '__main__':
    main()

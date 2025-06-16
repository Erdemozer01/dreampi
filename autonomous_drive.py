# autonomous_drive.py - Otonom Sürüş ve Engel Tespiti Betiği

import os
import sys
import time
import argparse
import logging
from gpiozero import Motor, DistanceSensor, OutputDevice
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device

# --- TEMEL YAPILANDIRMA ---
# Gerekirse pigpio'yu etkinleştir
try:
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- DONANIM PIN TANIMLAMALARI ---
# L298N Motor Sürücü Pinleri (4 Motor için 2 adet L298N veya paralel bağlantı varsayımı)
# Sol Motorlar
MOTOR_LEFT_FORWARD = 10  # IN1
MOTOR_LEFT_BACKWARD = 9  # IN2
# Sağ Motorlar
MOTOR_RIGHT_FORWARD = 8  # IN3
MOTOR_RIGHT_BACKWARD = 7  # IN4

# Step Motor Pinleri (Mevcut Tarayıcıdan)
H_MOTOR_IN1, H_MOTOR_IN2, H_MOTOR_IN3, H_MOTOR_IN4 = 26, 19, 13, 6  # Yatay (Pan)
V_MOTOR_IN1, V_MOTOR_IN2, V_MOTOR_IN3, V_MOTOR_IN4 = 21, 20, 16, 12  # Dikey (Tilt)

# Ultrasonik Sensör Pinleri
TRIG_PIN_1, ECHO_PIN_1 = 23, 24

# --- PARAMETRELER ---
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015  # Hızlı tarama için daha düşük gecikme
MOVE_DURATION = 1.0  # Her hareket döngüsünde ne kadar süre ileri gidileceği (saniye)
TURN_DURATION = 0.5  # Dönüşlerin ne kadar süreceği (saniye)
OBSTACLE_DISTANCE_CM = 30  # Engel olarak kabul edilecek minimum mesafe

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


# --- HAREKET FONKSİYONLARI ---
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


def move_forward():
    logging.info("İleri Gidiliyor...")
    left_motors.forward()
    right_motors.forward()
    time.sleep(MOVE_DURATION)
    stop_motors()


def turn_left():
    logging.info("Sola Dönülüyor...")
    left_motors.backward()
    right_motors.forward()
    time.sleep(TURN_DURATION)
    stop_motors()


def turn_right():
    logging.info("Sağa Dönülüyor...")
    left_motors.forward()
    right_motors.backward()
    time.sleep(TURN_DURATION)
    stop_motors()


def stop_motors():
    logging.info("Motorlar Durduruldu.")
    left_motors.stop()
    right_motors.stop()


# --- TARAMA VE ANALİZ FONKSİYONLARI ---
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
    """
    Belirtilen motoru, verilen açılara hızla hareket ettirir ve her açıda ölçüm yapar.
    """
    measurements = {}
    for angle in scan_angles:
        move_step_motor_to_angle(motor_devices, motor_ctx, angle)
        time.sleep(0.1)  # Sensörün okuma yapması için kısa bir bekleme
        distance = sensor.distance * 100 if sensor.distance else float('inf')
        measurements[angle] = distance
        logging.info(f"  Tarama: Açı={angle}°, Mesafe={distance:.1f} cm")
    return measurements


def analyze_and_decide(front_scan, rear_scan):
    """
    Tarama verilerini analiz eder ve bir sonraki harekete karar verir.
    """
    logging.info("Karar veriliyor...")
    # Ön tarama açıları: -45 (sol-ön), 0 (tam ön), 45 (sağ-ön)
    front_left = front_scan.get(-45, 0)
    front_center = front_scan.get(0, 0)
    front_right = front_scan.get(45, 0)

    # Eğer tam önümüzde engel yoksa ve en açık yol orasıysa, ileri git
    if front_center > OBSTACLE_DISTANCE_CM and front_center >= front_left and front_center >= front_right:
        logging.info("Karar: En açık yol ÖNDE. İleri gidilecek.")
        return "FORWARD"
    # Eğer en açık yol sağ öndeyse, sağa dön
    elif front_right > OBSTACLE_DISTANCE_CM and front_right > front_left:
        logging.info("Karar: En açık yol SAĞDA. Sağa dönülecek.")
        return "TURN_RIGHT"
    # Eğer en açık yol sol öndeyse, sola dön
    elif front_left > OBSTACLE_DISTANCE_CM:
        logging.info("Karar: En açık yol SOLDA. Sola dönülecek.")
        return "TURN_LEFT"
    # Eğer her yer kapalıysa, dur
    else:
        logging.info("Karar: Tüm yönler kapalı. Durulacak.")
        return "STOP"


# --- ANA ÇALIŞMA DÖNGÜSÜ ---
def main():
    setup_hardware()
    # Başlangıçta motorları ortaya al
    move_step_motor_to_angle(h_motor_devices, h_motor_ctx, 0)
    move_step_motor_to_angle(v_motor_devices, v_motor_ctx, 0)

    try:
        while True:
            logging.info("\n--- YENİ DÖNGÜ: DUR-DÜŞÜN-HAREKET ET ---")
            stop_motors()  # Önce dur

            # DÜŞÜN: Etrafı tara
            logging.info("1. Ön Taraf Taranıyor...")
            front_scan_data = perform_quick_scan(v_motor_devices, v_motor_ctx,
                                                 [0, -45, 45, 0])  # Sol-Orta-Sağ yapıp ortaya döner

            # (Şimdilik arka tarama verisini kullanmıyoruz, ama gelecekte eklenebilir)
            # logging.info("2. Arka Taraf Taranıyor ('Dikiz Aynası')...")
            # rear_scan_data = perform_quick_scan(h_motor_devices, h_motor_ctx, [0, 90, -90, 0])
            rear_scan_data = {}

            # DÜŞÜN: Karar ver
            decision = analyze_and_decide(front_scan_data, rear_scan_data)

            # HAREKET ET: Kararı uygula
            if decision == "FORWARD":
                move_forward()
            elif decision == "TURN_LEFT":
                turn_left()
            elif decision == "TURN_RIGHT":
                turn_right()
            elif decision == "STOP":
                logging.warning("Engel tespit edildi! Yardım bekleniyor...")
                break  # Döngüden çık

            time.sleep(1)  # Her döngü arasında 1 saniye bekle

    except KeyboardInterrupt:
        print("\nProgram kullanıcı tarafından sonlandırıldı.")
    finally:
        stop_motors()
        logging.info("Tüm işlemler durduruldu.")


if __name__ == '__main__':
    main()

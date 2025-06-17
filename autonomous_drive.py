# autonomous_drive.py - Tepkisel ve Akıllı Navigasyon Betiği

import os
import sys
import time
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

# --- DONANIM PIN TANIMLAMALARI (Fiziksel duruma göre ayarlandı) ---
# L298N Motor Sürücü Pinleri
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# Dikey olarak monte edilmiş motor (Ön tarama yapar)
V_MOTOR_IN1, V_MOTOR_IN2, V_MOTOR_IN3, V_MOTOR_IN4 = 26, 19, 13, 6
# Yatay olarak monte edilmiş motor (Dikiz aynası görevi görür)
H_MOTOR_IN1, H_MOTOR_IN2, H_MOTOR_IN3, H_MOTOR_IN4 = 21, 20, 16, 12

# Ultrasonik Sensör Pinleri
TRIG_PIN_1, ECHO_PIN_1 = 23, 24

# --- PARAMETRELER ---
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
MOVE_DURATION = 1.0
TURN_DURATION = 0.4
OBSTACLE_DISTANCE_CM = 35  # Öndeki engel mesafesi
REAR_TRIGGER_DISTANCE_CM = 20  # Arkadaki tetikleyici nesne mesafesi

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


# --- SÜREÇ, DONANIM VE HAREKET FONKSİYONLARI ---
# (Bu fonksiyonlar bir önceki versiyonla aynı olduğu için kısaltılmıştır)
def create_pid_file():
    # ...
    pass


def cleanup_on_exit():
    # ...
    pass


def setup_hardware():
    global left_motors, right_motors, sensor, h_motor_devices, v_motor_devices
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD);
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)
    sensor = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1);
    h_motor_devices = (OutputDevice(H_MOTOR_IN1), OutputDevice(H_MOTOR_IN2), OutputDevice(H_MOTOR_IN3),
                       OutputDevice(H_MOTOR_IN4))
    v_motor_devices = (OutputDevice(V_MOTOR_IN1), OutputDevice(V_MOTOR_IN2), OutputDevice(V_MOTOR_IN3),
                       OutputDevice(V_MOTOR_IN4));
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
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']]);
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_step_motor_to_angle(motor_devices, motor_ctx, target_angle_deg):
    deg_per_step = 360.0 / STEPS_PER_REVOLUTION
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step: return
    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0))
    motor_ctx['current_angle'] = target_angle_deg


# --- YENİ MANTIĞA GÖRE GÜNCELLENMİŞ FONKSİYONLAR ---
def check_rear_trigger():
    """
    Yatay motoru arkaya çevirir ve 20cm'den yakın bir nesne olup olmadığını kontrol eder.
    """
    # Dikiz aynası (Yatay motor) arkaya bakar
    move_step_motor_to_angle(h_motor_devices, h_motor_ctx, 180)
    time.sleep(0.1)
    distance = sensor.distance * 100 if sensor.distance else float('inf')
    logging.info(f"Arka kontrol: Mesafe={distance:.1f} cm")

    # Motoru tekrar ileri pozisyonuna al
    move_step_motor_to_angle(h_motor_devices, h_motor_ctx, 0)

    return distance < REAR_TRIGGER_DISTANCE_CM


def perform_front_scan():
    """
    Dikey motoru kullanarak ön tarafı -60 ve +60 derece arasında tarar.
    """
    logging.info("Ön taraf taranıyor...")
    scan_angles = [-60, -30, 0, 30, 60]
    measurements = {}
    for angle in scan_angles:
        move_step_motor_to_angle(v_motor_devices, v_motor_ctx, angle)
        time.sleep(0.1)
        distance = sensor.distance * 100 if sensor.distance else float('inf')
        measurements[angle] = distance
        logging.info(f"  Ön Tarama: Açı={angle}°, Mesafe={distance:.1f} cm")

    # Tarama bittikten sonra motoru tekrar merkeze al
    move_step_motor_to_angle(v_motor_devices, v_motor_ctx, 0)
    return measurements


def find_best_path(front_scan):
    """
    Ön tarama verilerinden en açık yolu (en uzun mesafeyi) bulur.
    """
    # Sadece engel mesafesinden daha uzak olan güvenli yolları değerlendir
    safe_options = {angle: dist for angle, dist in front_scan.items() if dist > OBSTACLE_DISTANCE_CM}

    if not safe_options:
        logging.warning("Önde hareket edecek güvenli bir yol bulunamadı.")
        return None  # Güvenli yol yoksa None döndür

    # En uzun mesafeye sahip olan en iyi açıyı seç
    best_angle = max(safe_options, key=safe_options.get)
    logging.info(f"Karar: En uygun yol {best_angle}° yönünde. Mesafe: {safe_options[best_angle]:.1f} cm")
    return best_angle


# --- ANA ÇALIŞMA DÖNGÜSÜ (YENİ MANTIKLA) ---
def main():
    atexit.register(cleanup_on_exit)
    create_pid_file()

    try:
        setup_hardware()
        # Başlangıçta step motorları sıfırla
        move_step_motor_to_angle(h_motor_devices, h_motor_ctx, 0)
        move_step_motor_to_angle(v_motor_devices, v_motor_ctx, 0)

        logging.info("Otonom sürüş modu başlatıldı. Arkadan bir nesne yaklaştırılması bekleniyor...")

        while True:
            # 1. TETİKLEYİCİYİ KONTROL ET
            if check_rear_trigger():
                logging.info("Tetikleyici algılandı! Hareket döngüsü başlıyor...")

                # 2. DÜŞÜN: Önü Tara ve Karar Ver
                front_scan_data = perform_front_scan()
                best_path_angle = find_best_path(front_scan_data)

                # 3. HAREKET ET: Kararı Uygula
                if best_path_angle is not None:
                    # En uygun yola doğru dön
                    if best_path_angle < -15:  # Sola dön
                        turn_left()
                    elif best_path_angle > 15:  # Sağa dön
                        turn_right()

                    # Ve ileri git
                    move_forward()
                else:
                    # Eğer ön taraf tamamen kapalıysa, dur ve bekle
                    logging.warning("Ön taraf kapalı, hareket edilemiyor.")
                    stop_motors()
                    time.sleep(2)  # Tekrar denemeden önce bekle
            else:
                # Tetikleyici yoksa bekle
                stop_motors()
                logging.info("Arkada tetikleyici bekleniyor...")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nProgram kullanıcı tarafından sonlandırıldı.")
    except Exception as e:
        logging.error(f"KRİTİK BİR HATA OLUŞTU: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    main()

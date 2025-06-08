import os, sys, time, fcntl, atexit, math, traceback, random

try:
    from gpiozero import Motor, Servo, DistanceSensor, OutputDevice
except ImportError as e:
    print(f"Hata: Gerekli kütüphane bulunamadı: {e}"); sys.exit(1)

# --- Sabitler ve Pinler ---
LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/autonomous_drive.lock', '/tmp/autonomous_drive.pid'

# DC Motor Pinleri (Kullanıcının Orijinal Pinleri)
DC_MOTOR_SOL_ILERI, DC_MOTOR_SOL_GERI, DC_MOTOR_SOL_HIZ = 4, 17, 27
DC_MOTOR_SAG_ILERI, DC_MOTOR_SAG_GERI, DC_MOTOR_SAG_HIZ = 22, 10, 9

IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
TRIG_PIN, ECHO_PIN, SERVO_PIN = 23, 24, 12

# Çalışma Parametreleri
HIZ_ILERI, HIZ_DONUS = 0.7, 0.6
SURE_ILERI_GIT, SURE_MANEVRA_DONUS = 1.2, 0.6
ENGEL_ESIK_MESAFESI = 35
TARAMA_ACISI_YATAY, TARAMA_ADIMI_YATAY = 240, 40
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY, STEP_MOTOR_SETTLE_TIME = 0.0015, 0.05

# --- Global Değişkenler ve Donanım ---
lock_file_handle, sol_motor, sag_motor, sensor, servo = None, None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
DEG_PER_STEP = 0.0
current_motor_angle_global, current_step_sequence_index = 0.0, 0
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]


# --- Fonksiyonlar (Önceki cevaplardaki gibi) ---
# acquire_lock_and_pid, release_resources_on_exit, init_hardware,
# _set_step_pins, _step_motor_4in, move_motor_to_angle,
# ileri, dur, sola_don, saga_don, cevreyi_hizli_tara, en_iyi_yolu_bul
# fonksiyonları buraya eklenecek.

def acquire_lock_and_pid():
    global lock_file_handle
    try:
        lock_file_handle = open(LOCK_FILE_PATH, 'w')
        fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(PID_FILE_PATH, 'w') as pf:
            pf.write(str(os.getpid()))
        return True
    except IOError:
        return False


def release_resources_on_exit():
    print("Otonom sürüş sonlanıyor...")
    dur()
    if servo: servo.detach()
    _set_step_pins(0, 0, 0, 0)
    # Diğer temizleme işlemleri


def init_hardware():
    global sol_motor, sag_motor, sensor, servo, DEG_PER_STEP, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        sol_motor = Motor(forward=DC_MOTOR_SOL_ILERI, backward=DC_MOTOR_SOL_GERI, enable=DC_MOTOR_SOL_HIZ)
        sag_motor = Motor(forward=DC_MOTOR_SAG_ILERI, backward=DC_MOTOR_SAG_GERI, enable=DC_MOTOR_SAG_HIZ)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)
        servo = Servo(SERVO_PIN)
        in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(IN2_GPIO_PIN), OutputDevice(
            IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION
        return True
    except Exception as e:
        print(f"Donanım Hatası: {e}"); return False


# ... (Diğer tüm yardımcı fonksiyonlar)

# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)

    try:
        # Ana sürüş döngüsü (önceki cevaplardaki gibi)
        while True:
            # ...
            pass
    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.")
    finally:
        print("Program sonlandırılıyor.")


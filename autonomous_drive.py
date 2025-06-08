import os
import sys
import time
import fcntl
import atexit
import math
import traceback
import random


from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device

Device.pin_factory = PiGPIOFactory()


# --- DONANIM KÜTÜPHANELERİ ---
try:
    from gpiozero import Motor, Servo, DistanceSensor, OutputDevice

    print("AutonomousDrive: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    print(f"AutonomousDrive: Gerekli kütüphane bulunamadı: {e}")
    sys.exit(1)

# --- SABİTLER VE PINLER ---
LOCK_FILE_PATH = '/tmp/autonomous_drive.lock'
PID_FILE_PATH = '/tmp/autonomous_drive.pid'

# DC Motor Pinleri (Kullanıcının Orijinal Pinleri)
DC_MOTOR_SOL_ILERI, DC_MOTOR_SOL_GERI, DC_MOTOR_SOL_HIZ = 4, 5, 8
DC_MOTOR_SAG_ILERI, DC_MOTOR_SAG_GERI, DC_MOTOR_SAG_HIZ = 22, 10, 16

# Step Motor Pinleri
IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
TRIG_PIN, ECHO_PIN, SERVO_PIN = 23, 24, 12

# --- ÇALIŞMA PARAMETRELERİ ---
HIZ_ILERI, HIZ_DONUS = 0.7, 0.6
SURE_ILERI_GIT, SURE_MANEVRA_DONUS = 1.2, 0.6
ENGEL_ESIK_MESAFESI = 35
TARAMA_ACISI_YATAY, TARAMA_ADIMI_YATAY = 240, 40
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY, STEP_MOTOR_SETTLE_TIME = 0.0015, 0.05

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, sol_motor, sag_motor, sensor, servo = None, None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION
current_motor_angle_global, current_step_sequence_index = 0.0, 0
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]


# --- SÜREÇ YÖNETİMİ VE KAYNAK KONTROLÜ ---
def acquire_lock_and_pid():
    global lock_file_handle
    try:
        lock_file_handle = open(LOCK_FILE_PATH, 'w')
        fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(PID_FILE_PATH, 'w') as pf:
            pf.write(str(os.getpid()))
        return True
    except IOError:
        print("Otonom Sürüş: Kilit dosyası oluşturulamadı. Başka bir script çalışıyor olabilir.")
        return False


def release_resources_on_exit():
    """ DÜZELTME: Bu fonksiyon, donanım nesneleri None ise hata vermeyecek şekilde güncellendi. """
    print("Otonom sürüş sonlanıyor, kaynaklar temizleniyor...")
    if sol_motor is not None and sag_motor is not None:
        dur()  # Sadece motorlar başarıyla oluşturulduysa durdur.
    if servo is not None:
        try:
            servo.detach()
        except:
            pass
    _set_step_pins(0, 0, 0, 0)
    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN); lock_file_handle.close()
        except:
            pass
    for fp in [PID_FILE_PATH, LOCK_FILE_PATH]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except:
                pass
    print("Temizleme tamamlandı.")


# --- DONANIM VE HAREKET FONKSİYONLARI ---
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
        print("Otonom Sürüş: Donanımlar başarıyla başlatıldı.")
        return True
    except Exception as e:
        print(f"KRİTİK HATA: Donanım başlatılamadı: {e}")
        return False


def _set_step_pins(s1, s2, s3, s4):
    if in1_dev: in1_dev.value = bool(s1)
    if in2_dev: in2_dev.value = bool(s2)
    if in3_dev: in3_dev.value = bool(s3)
    if in4_dev: in4_dev.value = bool(s4)


def _step_motor_4in(num_steps, direction_positive):
    global current_step_sequence_index
    for _ in range(int(num_steps)):
        step_increment = 1 if direction_positive else -1
        current_step_sequence_index = (current_step_sequence_index + step_increment) % len(step_sequence)
        _set_step_pins(*step_sequence[current_step_sequence_index])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_motor_to_angle(target_angle_deg):
    global current_motor_angle_global
    angle_diff = target_angle_deg - current_motor_angle_global
    if abs(angle_diff) < DEG_PER_STEP: return
    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    _step_motor_4in(num_steps, angle_diff > 0)
    current_motor_angle_global = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME)


def ileri(hiz=HIZ_ILERI): sol_motor.forward(hiz); sag_motor.forward(hiz)


def dur(): sol_motor.stop(); sag_motor.stop()


def sola_don(hiz=HIZ_DONUS): sol_motor.backward(hiz); sag_motor.forward(hiz)


def saga_don(hiz=HIZ_DONUS): sol_motor.forward(hiz); sag_motor.backward(hiz)


def cevreyi_hizli_tara():
    print("Çevre taranıyor...")
    mesafeler = {}
    baslangic_acisi = - (TARAMA_ACISI_YATAY / 2.0)
    adim_sayisi = int(TARAMA_ACISI_YATAY / TARAMA_ADIMI_YATAY)
    for i in range(adim_sayisi + 1):
        hedef_aci = baslangic_acisi + (i * TARAMA_ADIMI_YATAY)
        move_motor_to_angle(hedef_aci)
        time.sleep(0.1)
        mesafe = sensor.distance * 100
        mesafeler[hedef_aci] = mesafe
        print(f"  -> Açı: {hedef_aci:.0f}°, Mesafe: {mesafe:.1f} cm")
    move_motor_to_angle(0)
    return mesafeler


def en_iyi_yolu_bul(mesafeler):
    if not mesafeler: return None
    gecerli_yollar = {aci: mesafe for aci, mesafe in mesafeler.items() if mesafe > ENGEL_ESIK_MESAFESI}
    if not gecerli_yollar: print("!!! Tüm yönler kapalı !!!"); return 'geri_don'
    en_iyi_yon_aci = max(gecerli_yollar, key=gecerli_yollar.get)
    print(f">>> En iyi yol bulundu: {en_iyi_yon_aci:.0f}° yönü.")
    return en_iyi_yon_aci


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid(): sys.exit(1)
    if not init_hardware(): sys.exit(1)  # Eğer donanım başlamazsa, script burada durur.

    servo.min();
    time.sleep(1);
    servo.max();
    time.sleep(1);
    servo.mid();
    time.sleep(1)

    try:
        while True:
            dur();
            olcumler = cevreyi_hizli_tara();
            secilen_yon = en_iyi_yolu_bul(olcumler)
            if secilen_yon is None: time.sleep(1); continue
            if secilen_yon == 'geri_don':
                print("SIKIŞTI! Geri manevra yapılıyor...")
                (saga_don if random.choice([True, False]) else sola_don)();
                time.sleep(SURE_MANEVRA_DONUS)
            elif abs(secilen_yon) < (TARAMA_ADIMI_YATAY / 2):
                print("YOL AÇIK: İleri gidiliyor...");
                ileri();
                time.sleep(SURE_ILERI_GIT)
            else:
                print(f"HEDEF: {secilen_yon:.0f}° yönüne dönülüyor...")
                (saga_don if secilen_yon > 0 else sola_don)();
                time.sleep(SURE_MANEVRA_DONUS * 0.5)
            dur();
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"KRİTİK HATA: Ana döngüde bir hata oluştu: {e}"); traceback.print_exc()

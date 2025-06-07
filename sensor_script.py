# BU KODUN TAMAMINI KOPYALAYIP BOŞ SENSOR_SCRIPT.PY DOSYASINA YAPIŞTIRIN

import os
import sys
import time
import argparse
import fcntl
import atexit
import math
import traceback

# ==============================================================================
# --- DJANGO ENTEGRASYONU ---
# ==============================================================================
try:
    sys.path.append(os.getcwd())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dreampi.settings')
    import django

    django.setup()
    from django.utils import timezone
    from scanner.models import Scan, ScanPoint

    print("SensorScript: Django entegrasyonu başarılı.")
except Exception as e:
    print(f"SensorScript: Django entegrasyonu BAŞARISIZ: {e}")
    sys.exit(1)

# ==============================================================================
# --- DONANIM KÜTÜPHANELERİ ---
# ==============================================================================
from gpiozero import DistanceSensor, LED, Buzzer, OutputDevice, Servo
from RPLCD.i2c import CharLCD

# ==============================================================================
# --- KONTROL DEĞİŞKENLERİ VE PINLER ---
# ==============================================================================
MOTOR_BAGLI = True
# Pinler
TRIG_PIN, ECHO_PIN = 23, 24
TRIG2_PIN, ECHO2_PIN = 20, 21
SERVO_PIN = 12
IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
YELLOW_LED_PIN, BUZZER_PIN = 27, 17
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

# ==============================================================================
# --- VARSAYILAN DEĞERLER ---
# ==============================================================================
DEFAULT_HORIZONTAL_SCAN_ANGLE = 270.0
DEFAULT_HORIZONTAL_STEP_ANGLE = 10.0
DEFAULT_SERVO_SCAN_ANGLE = 180.0  # Servo için toplam tarama açısı
DEFAULT_BUZZER_DISTANCE = 10
DEFAULT_INVERT_MOTOR_DIRECTION = False
DEFAULT_STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY, STEP_MOTOR_SETTLE_TIME, LOOP_TARGET_INTERVAL_S = 0.0015, 0.05, 0.2

# ==============================================================================
# --- GLOBAL DEĞİŞKENLER ---
# ==============================================================================
LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'
sensor, sensor2, servo, yellow_led, buzzer, lcd = None, None, None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
lock_file_handle = None
current_scan_object_global = None
script_exit_status_global = Scan.Status.ERROR
DEG_PER_STEP = 0.0
current_motor_angle_global = 0.0
current_step_sequence_index = 0
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]


# ==============================================================================
# --- YARDIMCI FONKSİYONLAR ---
# ==============================================================================
def degree_to_servo_value(angle_deg):
    clamped_angle = max(0, min(180, angle_deg))
    return (clamped_angle / 90.0) - 1.0


def init_hardware():
    global sensor, sensor2, servo, yellow_led, buzzer, lcd, current_motor_angle_global, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        if MOTOR_BAGLI:
            in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(IN2_GPIO_PIN), OutputDevice(
                IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=2.5)
        sensor2 = DistanceSensor(echo=ECHO2_PIN, trigger=TRIG2_PIN, max_distance=2.5)
        servo = Servo(SERVO_PIN)
        yellow_led, buzzer = LED(YELLOW_LED_PIN), Buzzer(BUZZER_PIN)
        lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                      rows=LCD_ROWS, dotsize=8, charmap='A02', auto_linebreaks=True)
        lcd.clear()
        lcd.write_string("Dream Pi Hazir".ljust(LCD_COLS))
        print("Tüm donanımlar başarıyla başlatıldı.")
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
        current_step_sequence_index = (current_step_sequence_index + (1 if direction_positive else -1) + len(
            step_sequence)) % len(step_sequence)
        _set_step_pins(*step_sequence[current_step_sequence_index])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)
    time.sleep(STEP_MOTOR_SETTLE_TIME)


def move_motor_to_angle(target_angle_deg, invert_direction):
    global current_motor_angle_global
    if not MOTOR_BAGLI or DEG_PER_STEP <= 0: return

    angle_diff = target_angle_deg - current_motor_angle_global
    if abs(angle_diff) < (DEG_PER_STEP / 2.0): return

    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    if num_steps == 0: return

    logical_dir_positive = (angle_diff > 0)
    physical_dir_positive = not logical_dir_positive if invert_direction else logical_dir_positive

    _step_motor_4in(num_steps, physical_dir_positive)
    current_motor_angle_global = target_angle_deg


def create_scan_entry(h_angle, h_step, v_angle, buzzer_dist, invert_dir):
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR)
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=h_angle,
            step_angle_setting=h_step,
            end_angle_setting=v_angle,  # Dikey açıyı end_angle'a kaydedelim
            buzzer_distance_setting=buzzer_dist,
            invert_motor_direction_setting=invert_dir,
            status=Scan.Status.RUNNING
        )
        print(f"Yeni tarama kaydı veritabanında oluşturuldu: ID #{current_scan_object_global.id}")
        return True
    except Exception as e:
        print(f"DB Hatası (create_scan_entry): {e}");
        return False


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
    pid = os.getpid()
    print(f"[{pid}] Kaynaklar serbest bırakılıyor... Durum: {script_exit_status_global}")
    if current_scan_object_global:
        try:
            scan_to_update = Scan.objects.get(id=current_scan_object_global.id)
            if scan_to_update.status == Scan.Status.RUNNING:
                scan_to_update.status = script_exit_status_global
                scan_to_update.save()
        except Exception as e:
            print(f"DB çıkış HATA: {e}")
    if MOTOR_BAGLI: _set_step_pins(0, 0, 0, 0)
    if lcd:
        try:
            lcd.clear()
        except:
            pass
    for dev in [sensor, sensor2, servo, yellow_led, buzzer, in1_dev, in2_dev, in3_dev, in4_dev, lcd]:
        if dev and hasattr(dev, 'close'):
            try:
                dev.close()
            except:
                pass
    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN)
            lock_file_handle.close()
        except:
            pass
    for fp in [PID_FILE_PATH, LOCK_FILE_PATH]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except:
                pass
    print(f"[{pid}] Temizleme tamamlandı.")


# ==============================================================================
# --- ANA ÇALIŞMA BLOĞU ---
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Senkronize Yatay ve Dikey Tarama Scripti")
    parser.add_argument("--scan_duration_angle", type=float, default=DEFAULT_HORIZONTAL_SCAN_ANGLE)
    parser.add_argument("--step_angle", type=float, default=DEFAULT_HORIZONTAL_STEP_ANGLE)
    parser.add_argument("--servo_scan_angle", type=float, default=DEFAULT_SERVO_SCAN_ANGLE)
    parser.add_argument("--buzzer_distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    parser.add_argument("--invert_motor_direction", type=lambda x: str(x).lower() == 'true',
                        default=DEFAULT_INVERT_MOTOR_DIRECTION)
    parser.add_argument("--steps_per_rev", type=int, default=DEFAULT_STEPS_PER_REVOLUTION)
    args = parser.parse_args()

    pid = os.getpid()
    atexit.register(release_resources_on_exit)

    if not acquire_lock_and_pid():
        print(f"[{pid}] Başka bir betik çalışıyor. Çıkılıyor.");
        sys.exit(1)

    if not init_hardware():
        print(f"[{pid}] Donanım başlatılamadı. Çıkılıyor.");
        sys.exit(1)

    # Parametreleri al
    HORIZONTAL_TOTAL_ANGLE = args.scan_duration_angle
    HORIZONTAL_STEP_ANGLE = args.step_angle
    SERVO_TOTAL_ANGLE = args.servo_scan_angle
    INVERT_MOTOR = args.invert_motor_direction
    STEPS_PER_REVOLUTION = args.steps_per_rev
    BUZZER_DISTANCE = args.buzzer_distance

    DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION

    if not create_scan_entry(HORIZONTAL_TOTAL_ANGLE, HORIZONTAL_STEP_ANGLE, SERVO_TOTAL_ANGLE, BUZZER_DISTANCE,
                             INVERT_MOTOR):
        print(f"[{pid}] Veritabanı oturumu oluşturulamadı. Çıkılıyor.");
        sys.exit(1)

    print(f"[{pid}] Yeni Senkronize Tarama Başlatılıyor (ID: #{current_scan_object_global.id})...")
    print(f"  Yatay: {HORIZONTAL_TOTAL_ANGLE}° ({HORIZONTAL_STEP_ANGLE}° adımlarla)")
    print(f"  Dikey: {SERVO_TOTAL_ANGLE}° (Yatay tarama ile senkronize)")

    try:
        # Başlangıç pozisyonlarına git
        print("[ADIM 0] Başlangıç pozisyonuna gidiliyor (0 yatay, 0 dikey)...")
        move_motor_to_angle(0, INVERT_MOTOR)
        servo.value = degree_to_servo_value(0)
        time.sleep(1.5)

        # Adım sayılarını ve artış miktarlarını hesapla
        if HORIZONTAL_STEP_ANGLE == 0: raise ValueError("Yatay adım açısı 0 olamaz!")

        num_horizontal_steps = int(HORIZONTAL_TOTAL_ANGLE / HORIZONTAL_STEP_ANGLE)

        # Ana döngü her zaman daha fazla adıma sahip olan motora göre döner.
        # Bu örnekte step motor (27 adım) > servo (18 adım, eğer adımı 10 olsaydı)
        master_step_count = num_horizontal_steps

        print(f"Tarama {master_step_count} adımda tamamlanacak.")

        # Her bir ana adımda motorların ne kadar ilerleyeceğini hesapla
        h_increment_per_step = HORIZONTAL_TOTAL_ANGLE / master_step_count
        v_increment_per_step = SERVO_TOTAL_ANGLE / master_step_count

        # --- YENİ TARAMA DÖNGÜSÜ ---
        for i in range(master_step_count + 1):  # 0'dan 27'ye (dahil)
            current_h_angle = i * h_increment_per_step
            current_v_angle = i * v_increment_per_step

            # Motorları hedeflenen yeni açılara taşı
            move_motor_to_angle(current_h_angle, INVERT_MOTOR)
            servo.value = degree_to_servo_value(current_v_angle)

            # Motorların pozisyon alması için kısa bir bekleme
            time.sleep(LOOP_TARGET_INTERVAL_S)

            # Sensörleri oku
            dist_cm = sensor.distance * 100
            dist_cm_2 = sensor2.distance * 100

            print(
                f"  Adım {i}/{master_step_count} -> Y:{current_h_angle:.1f}° V:{current_v_angle:.1f}° -> S1:{dist_cm:.1f}cm S2:{dist_cm_2:.1f}cm")

            if buzzer.is_active != (dist_cm < BUZZER_DISTANCE or dist_cm_2 < BUZZER_DISTANCE):
                buzzer.toggle()

            # 3D koordinatları hesapla
            angle_pan_rad = math.radians(current_h_angle)
            angle_tilt_rad = math.radians(current_v_angle)
            horizontal_radius = dist_cm * math.cos(angle_tilt_rad)
            z_cm_val = dist_cm * math.sin(angle_tilt_rad)
            x_cm_val = horizontal_radius * math.cos(angle_pan_rad)
            y_cm_val = horizontal_radius * math.sin(angle_pan_rad)

            # Veritabanına kaydet
            ScanPoint.objects.create(
                scan=current_scan_object_global,
                derece=current_h_angle,
                dikey_aci=current_v_angle,
                mesafe_cm=dist_cm,
                x_cm=x_cm_val,
                y_cm=y_cm_val,
                z_cm=z_cm_val,
                mesafe_cm_2=dist_cm_2,
                timestamp=timezone.now()
            )

        print(f"[{pid}] Tarama bitti.")
        script_exit_status_global = Scan.Status.COMPLETED

    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        print(f"\n[{pid}] Ctrl+C ile kesildi.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        print(f"[{pid}] KRİTİK HATA: Ana döngüde: {e}")
        traceback.print_exc()
    finally:
        print(f"[{pid}] ADIM SON: Başlangıç konumuna (0,0) dönülüyor...")
        move_motor_to_angle(0, INVERT_MOTOR)
        servo.value = degree_to_servo_value(0)
        print(f"[{pid}] Başlangıç konumuna dönüldü.")

        # script_exit_status_global'i burada ayarla ve kaydet
        if current_scan_object_global:
            current_scan_object_global.status = script_exit_status_global
            current_scan_object_global.save()

        # Kaynakları serbest bırakma atexit tarafından zaten çağrılacak.
        print(f"[{pid}] Betik sonlanıyor.")
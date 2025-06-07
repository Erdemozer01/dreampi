# YENİ DOSYA: servo_scan_script.py

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

    print("ServoScanScript: Django entegrasyonu başarılı.")
except Exception as e:
    print(f"ServoScanScript: Django entegrasyonu BAŞARISIZ: {e}")
    sys.exit(1)

# ==============================================================================
# --- DONANIM KÜTÜPHANELERİ ---
# ==============================================================================
from gpiozero import DistanceSensor, LED, Buzzer, Servo
from RPLCD.i2c import CharLCD

# ==============================================================================
# --- PIN TANIMLAMALARI ---
# ==============================================================================
TRIG_PIN, ECHO_PIN = 23, 24
TRIG2_PIN, ECHO2_PIN = 20, 21
SERVO_PIN = 12
YELLOW_LED_PIN, BUZZER_PIN = 27, 17
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

# ==============================================================================
# --- VARSAYILAN DEĞERLER ---
# ==============================================================================
DEFAULT_BUZZER_DISTANCE = 15
LOOP_INTERVAL_S = 0.4  # Her adım arası bekleme süresi

# ==============================================================================
# --- GLOBAL DEĞİŞKENLER ---
# ==============================================================================
LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/servo_scan_script.lock', '/tmp/servo_scan_script.pid'
sensor, sensor2, servo, yellow_led, buzzer, lcd = None, None, None, None, None, None
lock_file_handle = None
current_scan_object_global = None
script_exit_status_global = Scan.Status.ERROR


# ==============================================================================
# --- YARDIMCI FONKSİYONLAR ---
# ==============================================================================
def degree_to_servo_value(angle_deg):
    clamped_angle = max(0, min(180, angle_deg))
    return (clamped_angle / 90.0) - 1.0


def init_hardware():
    global sensor, sensor2, servo, yellow_led, buzzer, lcd
    try:
        # Sadece gerekli donanımları başlatıyoruz (step motor yok)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=2.5)
        sensor2 = DistanceSensor(echo=ECHO2_PIN, trigger=TRIG2_PIN, max_distance=2.5)
        servo = Servo(SERVO_PIN)
        yellow_led, buzzer = LED(YELLOW_LED_PIN), Buzzer(BUZZER_PIN)
        lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                      rows=LCD_ROWS, dotsize=8, charmap='A02', auto_linebreaks=True)
        lcd.clear()
        lcd.write_string("Dikey Tarama...".ljust(LCD_COLS))
        print("Dikey tarama için donanımlar başarıyla başlatıldı.")
        return True
    except Exception as e:
        print(f"KRİTİK HATA: Donanım başlatılamadı: {e}")
        return False


def create_scan_entry(buzzer_dist):
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR)
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=0,  # Dikey başlangıç
            step_angle_setting=10,  # Dikey adım
            end_angle_setting=180,  # Dikey bitiş
            buzzer_distance_setting=buzzer_dist,
            status=Scan.Status.RUNNING
        )
        print(f"Yeni dikey tarama kaydı veritabanında oluşturuldu: ID #{current_scan_object_global.id}")
        return True
    except Exception as e:
        print(f"DB Hatası (create_scan_entry): {e}");
        return False


def acquire_lock_and_pid():
    global lock_file_handle
    try:
        lock_file_handle = open(LOCK_FILE_PATH, 'w');
        fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(PID_FILE_PATH, 'w') as pf:
            pf.write(str(os.getpid()))
        return True
    except IOError:
        return False


def release_resources_on_exit():
    pid = os.getpid()
    print(f"[{pid}] Kaynaklar serbest bırakılıyor... Durum: {script_exit_status_global}")
    if current_scan_object_global and current_scan_object_global.status == Scan.Status.RUNNING:
        try:
            scan_to_update = Scan.objects.get(id=current_scan_object_global.id)
            scan_to_update.status = script_exit_status_global
            scan_to_update.save()
        except:
            pass
    if lcd:
        try:
            lcd.clear()
        except:
            pass
    for dev in [sensor, sensor2, servo, yellow_led, buzzer, lcd]:
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
    parser = argparse.ArgumentParser(description="Sadece Dikey Eksenli Tarama Scripti")
    parser.add_argument("--buzzer_distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    args = parser.parse_args()

    pid = os.getpid()
    atexit.register(release_resources_on_exit)

    if not acquire_lock_and_pid():
        print(f"[{pid}] Başka bir betik çalışıyor. Çıkılıyor.");
        sys.exit(1)

    if not init_hardware():
        print(f"[{pid}] Donanım başlatılamadı. Çıkılıyor.");
        sys.exit(1)

    if not create_scan_entry(args.buzzer_distance):
        print(f"[{pid}] Veritabanı oturumu oluşturulamadı. Çıkılıyor.");
        sys.exit(1)

    print(f"[{pid}] Yeni Dikey Tarama Başlatılıyor (0° -> 180°)...")

    try:
        # Tarama döngüsü: 0'dan 180'e 10'ar derecelik adımlarla
        for angle in range(0, 181, 10):
            # 1. Servoyu hareket ettir
            servo.value = degree_to_servo_value(angle)
            time.sleep(LOOP_INTERVAL_S)  # Motorun pozisyon almasını bekle

            # 2. Sensörleri oku
            dist_cm = sensor.distance * 100

            print(f"  Açı: {angle}° -> Mesafe: {dist_cm:.1f} cm")
            lcd.cursor_pos = (1, 0)
            lcd.write_string(f"A:{angle:<3} D:{dist_cm:<5.1f}".ljust(LCD_COLS))

            # 3. 3D Koordinatları hesapla (Yatay açı 0 varsayılarak)
            # Bu, dikey bir düzlemde (Y-Z düzlemi) bir kesit oluşturur
            angle_tilt_rad = math.radians(angle)
            z_cm_val = dist_cm * math.sin(angle_tilt_rad)  # Yükseklik
            y_cm_val = dist_cm * math.cos(angle_tilt_rad)  # Derinlik
            x_cm_val = 0  # Yatay sapma yok

            # 4. Veritabanına kaydet
            ScanPoint.objects.create(
                scan=current_scan_object_global,
                derece=0,  # Yatay açı sabit
                dikey_aci=angle,
                mesafe_cm=dist_cm,
                x_cm=x_cm_val,
                y_cm=y_cm_val,
                z_cm=z_cm_val,
                timestamp=timezone.now()
            )

        print(f"[{pid}] Dikey tarama tamamlandı.")
        script_exit_status_global = Scan.Status.COMPLETED

    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        print(f"\n[{pid}] Ctrl+C ile kesildi.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        print(f"[{pid}] KRİTİK HATA: Ana döngüde: {e}")
        traceback.print_exc()
    finally:
        # Tarama bitince servoyu ortaya al ve serbest bırak
        print(f"[{pid}] Servo ortaya alınıp serbest bırakılıyor...")
        servo.value = degree_to_servo_value(90)
        time.sleep(1)
        servo.detach()

        if current_scan_object_global:
            current_scan_object_global.status = script_exit_status_global
            current_scan_object_global.save()

        print(f"[{pid}] Betik sonlanıyor.")
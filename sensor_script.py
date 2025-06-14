# sensor_script.py

import os
import sys
import time
import argparse
import fcntl
import atexit
import math
import traceback
import logging

# Logger konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensor_script.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- DJANGO ENTEGRASYONU ---
try:
    sys.path.append(os.getcwd())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dreampi.settings')
    import django

    django.setup()
    from django.utils import timezone
    from scanner.models import Scan, ScanPoint

    logger.info("SensorScript: Django entegrasyonu başarılı.")
except Exception as e:
    logger.error(f"SensorScript: Django entegrasyonu BAŞARISIZ: {e}", exc_info=True)
    sys.exit(1)

# --- DONANIM KÜTÜPHANELERİ ---
try:
    from gpiozero import DistanceSensor, LED, Buzzer, OutputDevice
    from RPLCD.i2c import CharLCD
    from gpiozero import Device

    logger.info("SensorScript: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    logger.error(f"SensorScript: Gerekli donanım kütüphanesi bulunamadı: {e}")
    sys.exit(1)

# --- PIGPIO KURULUMU ---
try:
    from gpiozero.pins.pigpio import PiGPIOFactory

    Device.pin_factory = PiGPIOFactory()
    logger.info("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    logger.warning(f"pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

# --- SABİTLER VE PINLER ---
MOTOR_BAGLI = True
# TEK BİR MOTOR SETİ KULLANILACAK (Paralel bağlantı varsayımı)
MOTOR_IN1, MOTOR_IN2, MOTOR_IN3, MOTOR_IN4 = 26, 19, 13, 6

TRIG_PIN_1, ECHO_PIN_1 = 23, 24
TRIG_PIN_2, ECHO_PIN_2 = 17, 18
BUZZER_PIN, LED_PIN = 25, 27
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'

# Varsayılan değerler
DEFAULT_SCAN_ANGLE = 270.0
DEFAULT_STEP_ANGLE = 10.0
DEFAULT_FIXED_TILT = 45.0
DEFAULT_BUZZER_DISTANCE = 10
DEFAULT_STEPS_PER_REV = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
STEP_MOTOR_SETTLE_TIME = 0.05

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, current_scan_object_global = None, None
sensor_1, sensor_2, buzzer, lcd, led = None, None, None, None, None
motor_devices = None  # Tek motor cihaz listesi
script_exit_status_global = Scan.Status.ERROR
motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]
INVERT_MOTOR_DIRECTION = False


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
        logger.error("Kilit dosyası oluşturulamadı. Başka bir script çalışıyor olabilir.")
        return False


def _stop_motor():
    """Tüm motor pinlerini kapatır"""
    if motor_devices:
        for dev in motor_devices:
            if dev: dev.off()
    logger.info("Motorlar durduruldu.")


def release_resources_on_exit():
    pid = os.getpid()
    logger.info(f"[{pid}] Kaynaklar serbest bırakılıyor... Son durum: {script_exit_status_global}")
    if current_scan_object_global and current_scan_object_global.status == Scan.Status.RUNNING:
        try:
            scan_to_update = Scan.objects.get(id=current_scan_object_global.id)
            scan_to_update.status = script_exit_status_global
            scan_to_update.end_time = timezone.now()
            scan_to_update.save()
        except Exception as e:
            logger.error(f"DB çıkış hatası: {e}")

    _stop_motor()
    if buzzer and buzzer.is_active: buzzer.off()
    if lcd:
        try:
            lcd.clear()
        except:
            pass
    if led and led.is_active: led.off()

    all_devices = [sensor_1, sensor_2, buzzer, lcd, led] + list(motor_devices or [])
    for dev in all_devices:
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
            except OSError as e:
                logger.error(f"Hata: {fp} dosyası silinemedi: {e}")
    logger.info(f"[{pid}] Temizleme tamamlandı.")


def init_hardware():
    global sensor_1, sensor_2, buzzer, lcd, led, motor_devices
    try:
        if MOTOR_BAGLI:
            motor_devices = (OutputDevice(MOTOR_IN1), OutputDevice(MOTOR_IN2), OutputDevice(MOTOR_IN3),
                             OutputDevice(MOTOR_IN4))

        sensor_1 = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1, max_distance=3.0, queue_len=5)
        sensor_2 = DistanceSensor(echo=ECHO_PIN_2, trigger=TRIG_PIN_2, max_distance=3.0, queue_len=5)
        buzzer = Buzzer(BUZZER_PIN)
        led = LED(LED_PIN)

        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS, auto_linebreaks=True)
            lcd.clear()
            lcd.write_string("Parallel Scan")
        except Exception as e:
            logger.warning(f"LCD başlatılamadı, LCD olmadan devam edilecek. Hata: {e}")
            lcd = None
        return True
    except Exception as e:
        logger.critical(f"Donanım başlatılamadı: {e}", exc_info=True)
        return False


# --- MOTOR KONTROL FONKSİYONLARI (BASİTLEŞTİRİLDİ) ---
def _set_motor_pins(s1, s2, s3, s4):
    motor_devices[0].value, motor_devices[1].value, motor_devices[2].value, motor_devices[3].value = bool(s1), bool(
        s2), bool(s3), bool(s4)


def _step_motor(num_steps, direction_positive):
    global motor_ctx
    step_increment = 1 if direction_positive else -1
    if INVERT_MOTOR_DIRECTION:
        step_increment *= -1

    for _ in range(int(num_steps)):
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(*step_sequence[motor_ctx['sequence_index']])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_motor_to_angle(target_angle_deg, total_steps_per_rev):
    global motor_ctx
    if not MOTOR_BAGLI or total_steps_per_rev <= 0: return

    deg_per_step = 360.0 / total_steps_per_rev
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step / 2: return

    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(num_steps, (angle_diff > 0))
    motor_ctx['current_angle'] = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME)


# --- VERİTABANI İŞLEMLERİ ---
def create_scan_entry(scan_angle, step_angle, buzzer_dist, steps_per_rev, fixed_tilt):
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=scan_angle,
            step_angle_setting=step_angle,
            end_angle_setting=fixed_tilt,  # Bu alanı sabit dikey açıyı saklamak için kullanıyoruz
            buzzer_distance_setting=buzzer_dist,
            steps_per_revolution_setting=steps_per_rev,
            status=Scan.Status.RUNNING)
        return True
    except Exception as e:
        logger.error(f"DB Hatası (create_scan_entry): {e}", exc_info=True)
        return False


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paralel Step Motorlu 3D Haritalama Scripti")
    parser.add_argument("--scan-angle", type=float, default=DEFAULT_SCAN_ANGLE)
    parser.add_argument("--step-angle", type=float, default=DEFAULT_STEP_ANGLE)
    parser.add_argument("--fixed-tilt", type=float, default=DEFAULT_FIXED_TILT,
                        help="Tarayıcının sabit dikey eğim açısı.")
    parser.add_argument("--buzzer-distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    parser.add_argument("--steps-per-rev", type=int, default=DEFAULT_STEPS_PER_REV)
    parser.add_argument("--invert-motor", action='store_true')
    args = parser.parse_args()

    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware():
        sys.exit(1)

    SCAN_ANGLE = args.scan_angle
    STEP_ANGLE = args.step_angle
    FIXED_TILT_ANGLE = args.fixed_tilt
    BUZZER_DISTANCE = args.buzzer_distance
    STEPS_PER_REVOLUTION = args.steps_per_rev
    INVERT_MOTOR_DIRECTION = args.invert_motor

    if not create_scan_entry(SCAN_ANGLE, STEP_ANGLE, BUZZER_DISTANCE, STEPS_PER_REVOLUTION, FIXED_TILT_ANGLE):
        sys.exit(1)

    try:
        initial_angle = -SCAN_ANGLE / 2.0
        logger.info(f"Motorlar başlangıç pozisyonuna gidiyor: {initial_angle:.1f}°")
        move_motor_to_angle(initial_angle, STEPS_PER_REVOLUTION)
        _stop_motor()

        num_scan_steps = int(SCAN_ANGLE / STEP_ANGLE) if STEP_ANGLE > 0 else 0

        for i in range(num_scan_steps + 1):
            target_pan_angle = initial_angle + (i * STEP_ANGLE)

            logger.info(
                f"\nAdım {i + 1}/{num_scan_steps + 1} | Tarama Açısı: {target_pan_angle:.1f}° | Sabit Eğim: {FIXED_TILT_ANGLE}°")
            move_motor_to_angle(target_pan_angle, STEPS_PER_REVOLUTION)
            _stop_motor()

            # Sensör okuma
            raw_dist_1 = sensor_1.distance
            raw_dist_2 = sensor_2.distance
            dist_cm_1 = (raw_dist_1 * 100) if raw_dist_1 is not None else sensor_1.max_distance * 100
            dist_cm_2 = (raw_dist_2 * 100) if raw_dist_2 is not None else sensor_2.max_distance * 100
            dist_for_xyz = dist_cm_2
            dist_for_alert = min(dist_cm_1, dist_cm_2)
            logger.info(f"  -> S1: {dist_cm_1:.1f}cm, S2: {dist_cm_2:.1f}cm")

            # LCD, Buzzer, LED Kontrolü
            if lcd:
                try:
                    lcd.cursor_pos = (0, 0);
                    lcd.write_string(f"P:{target_pan_angle:<5.1f} T:{FIXED_TILT_ANGLE:<5.1f}")
                    lcd.cursor_pos = (1, 0);
                    lcd.write_string(f"D:{dist_for_xyz:<5.1f} cm      ")
                except OSError as e:
                    logger.warning(f"LCD YAZMA HATASI: {e}")

            if buzzer.is_active != (0 < dist_for_alert < BUZZER_DISTANCE): buzzer.toggle()
            if led: led.value = (0 < dist_for_alert < 50)

            # 3D koordinat hesaplama
            angle_pan_rad = math.radians(target_pan_angle)
            angle_tilt_rad = math.radians(FIXED_TILT_ANGLE)  # SABİT AÇI KULLANILIYOR
            h_radius = dist_for_xyz * math.cos(angle_tilt_rad)
            z = dist_for_xyz * math.sin(angle_tilt_rad)
            x = h_radius * math.cos(angle_pan_rad)
            y = h_radius * math.sin(angle_pan_rad)

            # Veritabanı kaydı
            ScanPoint.objects.create(
                scan=current_scan_object_global,
                derece=target_pan_angle,
                dikey_aci=FIXED_TILT_ANGLE,  # Veritabanına sabit dikey açı kaydedilir
                mesafe_cm=dist_for_xyz,
                x_cm=x, y_cm=y, z_cm=z,
                timestamp=timezone.now()
            )

        script_exit_status_global = Scan.Status.COMPLETED

    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        logger.warning("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        logger.critical("KRİTİK HATA OLUŞTU!", exc_info=True)
    finally:
        logger.info("İşlem sonlanıyor. Motorlar sıfır pozisyonuna getiriliyor...")
        if MOTOR_BAGLI:
            move_motor_to_angle(0.0, STEPS_PER_REVOLUTION)
        _stop_motor()
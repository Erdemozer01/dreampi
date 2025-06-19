# sensor_script.py - Çift Step Motorlu Bağımsız Raster Tarama için

# Standart ve Django'ya bağımlı olmayan kütüphaneler
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
H_MOTOR_IN1, H_MOTOR_IN2, H_MOTOR_IN3, H_MOTOR_IN4 = 26, 19, 13, 6
V_MOTOR_IN1, V_MOTOR_IN2, V_MOTOR_IN3, V_MOTOR_IN4 = 21, 20, 16, 12

TRIG_PIN_1, ECHO_PIN_1 = 23, 24
TRIG_PIN_2, ECHO_PIN_2 = 17, 27
BUZZER_PIN, LED_PIN = 22, 25
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'

DEFAULT_H_SCAN_ANGLE = 360.0
DEFAULT_H_STEP_ANGLE = 20.0
DEFAULT_V_SCAN_ANGLE = 360.0
DEFAULT_V_STEP_ANGLE = 20.0
DEFAULT_BUZZER_DISTANCE = 15
DEFAULT_STEPS_PER_REV = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.002
STEP_MOTOR_SETTLE_TIME = 0.05

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, current_scan_object_global = None, None
sensor_1, sensor_2, buzzer, lcd, led = None, None, None, None, None
h_motor_devices, v_motor_devices = None, None
h_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
v_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]
INVERT_H_MOTOR_DIRECTION = False
INVERT_V_MOTOR_DIRECTION = False
script_exit_status_global = Scan.Status.ERROR


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


def _stop_all_motors():
    if not MOTOR_BAGLI: return
    for dev in (h_motor_devices or []) + (v_motor_devices or []):
        if dev: dev.off()
    logger.info("Tüm motorlar durduruldu.")


def release_resources_on_exit():
    """
    Program sonlandığında tüm donanım kaynaklarını güvenli bir şekilde kapatır,
    gerekirse analizi tetikler ve kilit dosyalarını temizler.
    atexit tarafından otomatik olarak çağrılır.
    """
    # Fonksiyon içinde kullanılacak global değişkenler
    global current_scan_object_global, lock_file_handle, sensor_1, sensor_2, script_exit_status_global

    pid = os.getpid()
    logger.info(f"[{pid}] Kaynaklar serbest bırakılıyor... Betiğin son durumu: {script_exit_status_global}")

    # --- 1. Veritabanı İşlemleri ---
    if current_scan_object_global:
        try:
            # Nesnenin en güncel halini veritabanından al
            scan_to_finalize = Scan.objects.get(id=current_scan_object_global.id)

            # Eğer betik, taramayı başarıyla tamamladığı için çıkıyorsa...
            if script_exit_status_global == Scan.Status.COMPLETED:
                logger.info("Tarama tamamlandı. Analiz metodu çağrılıyor...")
                scan_to_finalize.status = Scan.Status.COMPLETED
                scan_to_finalize.end_time = timezone.now()
                # Önce durumu ve bitiş zamanını kaydet
                scan_to_finalize.save(update_fields=['status', 'end_time'])
                # Sonra analizi çalıştır (bu da kendi içinde bir save yapacak)
                scan_to_finalize.run_analysis_and_update()

            # Eğer betik bir hata veya kesinti ile sonlanıyorsa ve durum hala 'Çalışıyor' ise...
            elif scan_to_finalize.status == Scan.Status.RUNNING:
                scan_to_finalize.status = script_exit_status_global
                scan_to_finalize.end_time = timezone.now()
                scan_to_finalize.save(update_fields=['status', 'end_time'])
                logger.info(f"Scan ID {scan_to_finalize.id} durumu '{script_exit_status_global}' olarak güncellendi.")

        except Scan.DoesNotExist:
            logger.error("Temizleme sırasında veritabanında ilgili Scan nesnesi bulunamadı.")
        except Exception as e:
            logger.error(f"Veritabanı sonlandırma işlemleri sırasında hata: {e}", exc_info=True)

    # --- 2. Donanım Kapatma İşlemleri ---
    logger.info("Donanım cihazları kapatılıyor...")

    # Arka plan hatasını önlemek için ÖNCE sensörleri kapat
    if sensor_1:
        try:
            sensor_1.close()
        except Exception as e:
            logger.error(f"Sensor 1 kapatılırken hata: {e}")
    if sensor_2:
        try:
            sensor_2.close()
        except Exception as e:
            logger.error(f"Sensor 2 kapatılırken hata: {e}")

    time.sleep(0.1)  # Arka plan işlemlerinin durması için kısa bir an bekle

    # Motorları ve diğer çevre birimlerini kapat
    _stop_all_motors()

    if buzzer and buzzer.is_active: buzzer.off()
    if lcd:
        try:
            lcd.clear()
        except Exception:
            pass
    if led and led.is_active: led.off()

    # --- 3. Dosya Kilitlerini Temizleme ---
    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN)
            lock_file_handle.close()
        except Exception as e:
            logger.error(f"Kilit dosyası serbest bırakılırken hata: {e}")

    for fp in [PID_FILE_PATH, LOCK_FILE_PATH]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError as e:
                logger.error(f"Temizleme hatası: {fp} dosyası silinemedi: {e}")

    logger.info(f"[{pid}] Temizleme tamamlandı.")


def init_hardware():
    global sensor_1, sensor_2, buzzer, lcd, led, h_motor_devices, v_motor_devices
    try:
        if MOTOR_BAGLI:
            h_motor_devices = (OutputDevice(H_MOTOR_IN1), OutputDevice(H_MOTOR_IN2), OutputDevice(H_MOTOR_IN3),
                               OutputDevice(H_MOTOR_IN4))
            v_motor_devices = (OutputDevice(V_MOTOR_IN1), OutputDevice(V_MOTOR_IN2), OutputDevice(V_MOTOR_IN3),
                               OutputDevice(V_MOTOR_IN4))
        sensor_1 = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1, max_distance=3.0, queue_len=5)
        sensor_2 = DistanceSensor(echo=ECHO_PIN_2, trigger=TRIG_PIN_2, max_distance=3.0, queue_len=5)
        buzzer = Buzzer(BUZZER_PIN);
        led = LED(LED_PIN)
        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS, auto_linebreaks=True)
            lcd.clear();
            lcd.write_string("Raster Scan")
        except Exception as e:
            logger.warning(f"LCD başlatılamadı, LCD olmadan devam edilecek. Hata: {e}");
            lcd = None
        return True
    except Exception as e:
        logger.critical(f"Donanım başlatılamadı: {e}", exc_info=True)
        return False


def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    motor_devices[0].value, motor_devices[1].value, motor_devices[2].value, motor_devices[3].value = bool(s1), bool(
        s2), bool(s3), bool(s4)


def _step_motor(motor_devices, motor_ctx, num_steps, direction_positive, invert_direction=False):
    step_increment = 1 if direction_positive else -1
    if invert_direction: step_increment *= -1
    for _ in range(int(num_steps)):
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_motor_to_angle(motor_devices, motor_ctx, target_angle_deg, total_steps_per_rev, invert_direction=False):
    if not MOTOR_BAGLI: return
    deg_per_step = 360.0 / total_steps_per_rev
    angle_diff = target_angle_deg - motor_ctx['current_angle']
    if abs(angle_diff) < deg_per_step / 2: return
    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0), invert_direction)
    motor_ctx['current_angle'] = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME)


def create_scan_entry(h_angle, h_step, v_angle, v_step, buzzer_dist, steps_per_rev):
    global current_scan_object_global
    try:
        # Eski ve çalışan taramaları hata durumuyla kapat
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())

        # DÜZELTME: Modeldeki yeni alan adları kullanılıyor
        current_scan_object_global = Scan.objects.create(
            h_scan_angle_setting=h_angle,
            h_step_angle_setting=h_step,
            v_scan_angle_setting=v_angle,
            v_step_angle_setting=v_step,
            # buzzer_distance_setting alanı modelinizde yok, bu yüzden kaldırıldı veya eklenmeli
            steps_per_revolution_setting=steps_per_rev,
            status=Scan.Status.RUNNING
        )
        logger.info(f"Veritabanında yeni tarama kaydı oluşturuldu: ID {current_scan_object_global.id}")
        return True
    except Exception as e:
        logger.error(f"DB Hatası (create_scan_entry): {e}", exc_info=True)
        return False


# --- ANA ÇALIŞMA BLOĞU
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Çift Step Motorlu Raster Tarama Scripti")

    # Argümanlar, arayüz (dashboard.py) tarafından gönderilenlerle tam uyumlu hale getirildi
    parser.add_argument("--h-angle", type=float, default=DEFAULT_H_SCAN_ANGLE)
    parser.add_argument("--h-step", type=float, default=DEFAULT_H_STEP_ANGLE)
    parser.add_argument("--v-angle", type=float, default=DEFAULT_V_SCAN_ANGLE)
    parser.add_argument("--v-step", type=float, default=DEFAULT_V_STEP_ANGLE)
    parser.add_argument("--buzzer-distance", type=int, default=DEFAULT_BUZZER_DISTANCE)  # Buzzer argümanı eklendi
    parser.add_argument("--steps-per-rev", type=int, default=DEFAULT_STEPS_PER_REV)

    args = parser.parse_args()

    # --- Başlangıç Kontrolleri (Sadece bir kez çalıştırılır) ---
    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware():
        sys.exit(1)

    # Veritabanı kaydı oluşturulur
    if not create_scan_entry(args.h_angle, args.h_step, args.v_angle, args.v_step, args.buzzer_distance,
                             args.steps_per_rev):
        sys.exit(1)

    # Ana tarama mantığı
    try:
        h_initial_angle = -args.h_angle / 2.0
        v_initial_angle = 0.0
        logger.info("Motorlar başlangıç pozisyonlarına getiriliyor...")
        move_motor_to_angle(h_motor_devices, h_motor_ctx, h_initial_angle, args.steps_per_rev, INVERT_H_MOTOR_DIRECTION)
        move_motor_to_angle(v_motor_devices, v_motor_ctx, v_initial_angle, args.steps_per_rev, INVERT_V_MOTOR_DIRECTION)

        num_h_steps = int(args.h_angle / args.h_step) if args.h_step > 0 else 0
        num_v_steps = int(args.v_angle / args.v_step) if args.v_step > 0 else 0

        logger.info("Raster Tarama Başlatılıyor...")
        for i in range(num_h_steps + 1):
            target_h_angle = h_initial_angle + (i * args.h_step)
            move_motor_to_angle(h_motor_devices, h_motor_ctx, target_h_angle, args.steps_per_rev,
                                INVERT_H_MOTOR_DIRECTION)
            logger.info(f"\nYatay Açı: {h_motor_ctx['current_angle']:.1f}° ({i + 1}/{num_h_steps + 1})")

            for j in range(num_v_steps + 1):
                # "Ping-pong" tarama mantığı
                if i % 2 == 0:
                    target_v_angle = v_initial_angle + (j * args.v_step)
                else:
                    target_v_angle = args.v_angle - (j * args.v_step)

                move_motor_to_angle(v_motor_devices, v_motor_ctx, target_v_angle, args.steps_per_rev,
                                    INVERT_V_MOTOR_DIRECTION)

                # Sensör okuması ve veritabanına kayıt
                dist_cm = (sensor_1.distance * 100) if sensor_1.distance is not None else -1.0
                logger.info(f"  -> Dikey: {v_motor_ctx['current_angle']:.1f}°, Mesafe: {dist_cm:.1f}cm")

                # Buzzer kontrolü
                if dist_cm > 0 and args.buzzer_distance > 0:
                    if dist_cm < args.buzzer_distance:
                        buzzer.on()
                    else:
                        buzzer.off()

                if dist_cm > 0:
                    angle_pan_rad = math.radians(h_motor_ctx['current_angle'])
                    angle_tilt_rad = math.radians(v_motor_ctx['current_angle'])
                    h_radius = dist_cm * math.cos(angle_tilt_rad)
                    z = dist_cm * math.sin(angle_tilt_rad)
                    x = h_radius * math.cos(angle_pan_rad)
                    y = h_radius * math.sin(angle_pan_rad)

                    ScanPoint.objects.create(
                        scan=current_scan_object_global,
                        derece=h_motor_ctx['current_angle'], dikey_aci=v_motor_ctx['current_angle'],
                        mesafe_cm=dist_cm, x_cm=x, y_cm=y, z_cm=z, timestamp=timezone.now()
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
            move_motor_to_angle(h_motor_devices, h_motor_ctx, 0.0, args.steps_per_rev)
            move_motor_to_angle(v_motor_devices, v_motor_ctx, 0.0, args.steps_per_rev)
        _stop_all_motors()
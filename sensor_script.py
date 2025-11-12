# sensor_script.py - Çift Step Motorlu + Çift Sensörlü Bağımsız Raster Tarama


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
    from gpiozero import DistanceSensor, OutputDevice, Device
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

# --- SABİTLER VE PİNLER ---
MOTOR_BAGLI = True

# Motor Pinleri
H_MOTOR_IN1, H_MOTOR_IN2, H_MOTOR_IN3, H_MOTOR_IN4 = 26, 19, 13, 6  # Yatay Motor (Pan)
V_MOTOR_IN1, V_MOTOR_IN2, V_MOTOR_IN3, V_MOTOR_IN4 = 21, 20, 16, 12  # Dikey Motor (Tilt)

# Sensör Pinleri - İKİ BAĞIMSIZ SENSÖR
H_TRIG, H_ECHO = 23, 24  # H-Sensör (Yatay motor üzerinde)
V_TRIG, V_ECHO = 17, 27  # V-Sensör (Dikey motor üzerinde)

# Kilit Dosyaları
LOCK_FILE_PATH = '/tmp/sensor_scan_script.lock'
PID_FILE_PATH = '/tmp/sensor_scan_script.pid'

# Varsayılan Parametreler
DEFAULT_H_SCAN_ANGLE = 360.0
DEFAULT_H_STEP_ANGLE = 20.0
DEFAULT_V_SCAN_ANGLE = 360.0
DEFAULT_V_STEP_ANGLE = 20.0
DEFAULT_STEPS_PER_REV = 4096

# Motor Ayarları
STEP_MOTOR_INTER_STEP_DELAY = 0.004  # Adım arası gecikme (saniye)
STEP_MOTOR_SETTLE_TIME = 0.1  # Motor durduktan sonra bekleme (saniye)
MEASUREMENT_PAUSE_SECONDS = 1.0  # Ölçüm öncesi stabilizasyon süresi

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle = None
current_scan_object_global = None

# İKİ BAĞIMSIZ SENSÖR
h_sensor = None  # Yatay motor sensörü
v_sensor = None  # Dikey motor sensörü

# Motor cihazları ve kontekstleri
h_motor_devices = None
v_motor_devices = None
h_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
v_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}

# Step motor sekansı (28BYJ-48 için)
step_sequence = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]

# Motor yön inversiyonu (gerekirse True yapın)
INVERT_H_MOTOR_DIRECTION = False
INVERT_V_MOTOR_DIRECTION = False

# Script çıkış durumu
script_exit_status_global = Scan.Status.ERROR


# --- SÜREÇ YÖNETİMİ VE KAYNAK KONTROLÜ ---
def acquire_lock_and_pid():
    """PID ve kilit dosyası oluştur"""
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
    """Tüm motorları durdur"""
    if not MOTOR_BAGLI:
        return
    for dev in (h_motor_devices or []) + (v_motor_devices or []):
        if dev:
            dev.off()
    logger.info("Tüm motorlar durduruldu.")


def release_resources_on_exit():
    """Program sonlandığında tüm kaynakları temizle"""
    global current_scan_object_global, lock_file_handle, h_sensor, v_sensor, script_exit_status_global

    pid = os.getpid()
    logger.info(f"[{pid}] Kaynaklar serbest bırakılıyor... Betiğin son durumu: {script_exit_status_global}")

    # --- 1. Veritabanı İşlemleri ---
    if current_scan_object_global:
        try:
            scan_to_finalize = Scan.objects.get(id=current_scan_object_global.id)

            if script_exit_status_global == Scan.Status.COMPLETED:
                logger.info("Tarama tamamlandı. Analiz metodu çağrılıyor...")
                scan_to_finalize.status = Scan.Status.COMPLETED
                scan_to_finalize.end_time = timezone.now()
                scan_to_finalize.save(update_fields=['status', 'end_time'])
                scan_to_finalize.run_analysis_and_update()

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

    # İKİ SENSÖRÜ KAPAT
    if h_sensor:
        try:
            h_sensor.close()
            logger.info("✓ H-Sensör güvenli şekilde kapatıldı")
        except Exception as e:
            logger.error(f"H-Sensör kapatılırken hata: {e}")

    if v_sensor:
        try:
            v_sensor.close()
            logger.info("✓ V-Sensör güvenli şekilde kapatıldı")
        except Exception as e:
            logger.error(f"V-Sensör kapatılırken hata: {e}")

    time.sleep(0.1)
    _stop_all_motors()

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

    logger.info(f"[{pid}] ✓ Temizleme tamamlandı.")


def init_hardware():
    """Donanım bileşenlerini başlat (sadece motorlar ve sensörler)"""
    global h_sensor, v_sensor, h_motor_devices, v_motor_devices
    try:
        # Motorları başlat
        if MOTOR_BAGLI:
            h_motor_devices = (
                OutputDevice(H_MOTOR_IN1), OutputDevice(H_MOTOR_IN2),
                OutputDevice(H_MOTOR_IN3), OutputDevice(H_MOTOR_IN4)
            )
            v_motor_devices = (
                OutputDevice(V_MOTOR_IN1), OutputDevice(V_MOTOR_IN2),
                OutputDevice(V_MOTOR_IN3), OutputDevice(V_MOTOR_IN4)
            )
            logger.info("✓ Step motorlar başlatıldı")

        # İKİ BAĞIMSIZ SENSÖR
        h_sensor = DistanceSensor(
            echo=H_ECHO,
            trigger=H_TRIG,
            max_distance=3.0,
            queue_len=5
        )
        logger.info(f"✓ H-Sensör başlatıldı (TRIG:GPIO{H_TRIG}, ECHO:GPIO{H_ECHO})")

        v_sensor = DistanceSensor(
            echo=V_ECHO,
            trigger=V_TRIG,
            max_distance=3.0,
            queue_len=5
        )
        logger.info(f"✓ V-Sensör başlatıldı (TRIG:GPIO{V_TRIG}, ECHO:GPIO{V_ECHO})")

        return True

    except Exception as e:
        logger.critical(f"❌ Donanım başlatılamadı: {e}", exc_info=True)
        return False


def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    """Motor pinlerini ayarla"""
    motor_devices[0].value = bool(s1)
    motor_devices[1].value = bool(s2)
    motor_devices[2].value = bool(s3)
    motor_devices[3].value = bool(s4)


def _step_motor(motor_devices, motor_ctx, num_steps, direction_positive, invert_direction=False):
    """Motoru belirtilen adım sayısı kadar hareket ettir"""
    step_increment = 1 if direction_positive else -1
    if invert_direction:
        step_increment *= -1

    for _ in range(int(num_steps)):
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_motor_to_angle(motor_devices, motor_ctx, target_angle_deg, total_steps_per_rev, invert_direction=False):
    """Motoru hedef açıya getir"""
    if not MOTOR_BAGLI:
        return

    deg_per_step = 360.0 / total_steps_per_rev
    angle_diff = target_angle_deg - motor_ctx['current_angle']

    if abs(angle_diff) < deg_per_step / 2:
        return

    logger.info(f"Motor {target_angle_deg:.1f}° hedefine getiriliyor (Fark: {angle_diff:.1f}°)")

    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor(motor_devices, motor_ctx, num_steps, (angle_diff > 0), invert_direction)
    motor_ctx['current_angle'] = target_angle_deg

    time.sleep(STEP_MOTOR_SETTLE_TIME)


def create_scan_entry(h_angle, h_step, v_angle, v_step, steps_per_rev):
    """Veritabanında yeni tarama kaydı oluştur"""
    global current_scan_object_global
    try:
        # Çalışan taramaları hata olarak işaretle
        Scan.objects.filter(status=Scan.Status.RUNNING).update(
            status=Scan.Status.ERROR,
            end_time=timezone.now()
        )

        current_scan_object_global = Scan.objects.create(
            h_scan_angle_setting=h_angle,
            h_step_angle_setting=h_step,
            v_scan_angle_setting=v_angle,
            v_step_angle_setting=v_step,
            steps_per_revolution_setting=steps_per_rev,
            status=Scan.Status.RUNNING,
            scan_type=Scan.ScanType.MANUAL
        )
        logger.info(f"✓ Veritabanında yeni tarama kaydı oluşturuldu: ID {current_scan_object_global.id}")
        return True
    except Exception as e:
        logger.error(f"DB Hatası (create_scan_entry): {e}", exc_info=True)
        return False


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Çift Step Motorlu + Çift Sensörlü Raster Tarama")

    parser.add_argument("--h-angle", type=float, default=DEFAULT_H_SCAN_ANGLE)
    parser.add_argument("--h-step", type=float, default=DEFAULT_H_STEP_ANGLE)
    parser.add_argument("--v-angle", type=float, default=DEFAULT_V_SCAN_ANGLE)
    parser.add_argument("--v-step", type=float, default=DEFAULT_V_STEP_ANGLE)
    parser.add_argument("--steps-per-rev", type=int, default=DEFAULT_STEPS_PER_REV)

    args = parser.parse_args()

    # Başlangıç kontrolleri
    atexit.register(release_resources_on_exit)

    if not acquire_lock_and_pid() or not init_hardware():
        sys.exit(1)

    if not create_scan_entry(args.h_angle, args.h_step, args.v_angle, args.v_step, args.steps_per_rev):
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

        logger.info("="*60)
        logger.info("RASTER TARAMA BAŞLATILIYOR")
        logger.info(f"Yatay: {num_h_steps + 1} adım, Dikey: {num_v_steps + 1} adım")
        logger.info(f"Toplam Nokta: {(num_h_steps + 1) * (num_v_steps + 1)}")
        logger.info("="*60)

        for i in range(num_h_steps + 1):
            target_h_angle = h_initial_angle + (i * args.h_step)
            move_motor_to_angle(
                h_motor_devices,
                h_motor_ctx,
                target_h_angle,
                args.steps_per_rev,
                INVERT_H_MOTOR_DIRECTION
            )
            logger.info(f"\n{'='*60}")
            logger.info(f"YATAY AÇI: {h_motor_ctx['current_angle']:.1f}° ({i + 1}/{num_h_steps + 1})")
            logger.info(f"{'='*60}")

            for j in range(num_v_steps + 1):
                # Raster tarama: Tek satırlarda ileri, çift satırlarda geri
                if i % 2 == 0:
                    target_v_angle = v_initial_angle + (j * args.v_step)
                else:
                    target_v_angle = args.v_angle - (j * args.v_step)

                move_motor_to_angle(
                    v_motor_devices,
                    v_motor_ctx,
                    target_v_angle,
                    args.steps_per_rev,
                    INVERT_V_MOTOR_DIRECTION
                )

                logger.info(f"  -> Dikey: {v_motor_ctx['current_angle']:.1f}° ({j+1}/{num_v_steps+1})")
                logger.info(f"  -> Stabilizasyon için {MEASUREMENT_PAUSE_SECONDS}sn bekleniyor...")
                time.sleep(MEASUREMENT_PAUSE_SECONDS)

                # === İKİ SENSÖRDEN BAĞIMSIZ ÖLÇÜM AL ===
                h_raw = h_sensor.distance
                v_raw = v_sensor.distance

                h_dist_cm = (h_raw * 100) if h_raw is not None else -1.0
                v_dist_cm = (v_raw * 100) if v_raw is not None else -1.0

                logger.info(f"  -> H-Sensör: {h_dist_cm:.1f}cm")
                logger.info(f"  -> V-Sensör: {v_dist_cm:.1f}cm")

                # Koordinat hesaplama (her iki sensör için ayrı ayrı)
                angle_pan_rad = math.radians(h_motor_ctx['current_angle'])
                angle_tilt_rad = math.radians(v_motor_ctx['current_angle'])

                # H-Sensör için koordinatlar
                if h_dist_cm > 0:
                    h_radius = h_dist_cm * math.cos(angle_tilt_rad)
                    h_z = h_dist_cm * math.sin(angle_tilt_rad)
                    h_x = h_radius * math.cos(angle_pan_rad)
                    h_y = h_radius * math.sin(angle_pan_rad)
                else:
                    h_x = h_y = h_z = None

                # V-Sensör için koordinatlar
                if v_dist_cm > 0:
                    v_radius = v_dist_cm * math.cos(angle_tilt_rad)
                    v_z = v_dist_cm * math.sin(angle_tilt_rad)
                    v_x = v_radius * math.cos(angle_pan_rad)
                    v_y = v_radius * math.sin(angle_pan_rad)
                else:
                    v_x = v_y = v_z = None

                # Ana mesafe: İki sensörden geçerli olanı kullan (öncelik H-Sensör)
                if h_dist_cm > 0:
                    main_dist = h_dist_cm
                    main_x, main_y, main_z = h_x, h_y, h_z
                elif v_dist_cm > 0:
                    main_dist = v_dist_cm
                    main_x, main_y, main_z = v_x, v_y, v_z
                else:
                    main_dist = -1.0
                    main_x = main_y = main_z = None

                # Veritabanına kaydet (her iki sensör verisi de)
                if main_dist > 0:
                    ScanPoint.objects.create(
                        scan=current_scan_object_global,
                        derece=h_motor_ctx['current_angle'],
                        dikey_aci=v_motor_ctx['current_angle'],
                        mesafe_cm=main_dist,
                        h_sensor_distance=h_dist_cm,
                        v_sensor_distance=v_dist_cm,
                        x_cm=main_x,
                        y_cm=main_y,
                        z_cm=main_z,
                        timestamp=timezone.now()
                    )
                    logger.info(f"  -> ✓ Nokta kaydedildi (Ana:{main_dist:.1f}cm)")
                else:
                    logger.warning(f"  -> ⚠ Her iki sensör de geçersiz okuma yaptı, nokta atlandı")

        script_exit_status_global = Scan.Status.COMPLETED
        logger.info("\n" + "="*60)
        logger.info("TARAMA TAMAMLANDI!")
        logger.info("="*60)

    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        logger.warning("\n❌ Kullanıcı tarafından durduruldu.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        logger.critical("❌ KRİTİK HATA OLUŞTU!", exc_info=True)
    finally:
        logger.info("İşlem sonlanıyor. Motorlar sıfır pozisyonuna getiriliyor...")
        if MOTOR_BAGLI:
            move_motor_to_angle(h_motor_devices, h_motor_ctx, 0.0, args.steps_per_rev)
            move_motor_to_angle(v_motor_devices, v_motor_ctx, 0.0, args.steps_per_rev)
        _stop_all_motors()

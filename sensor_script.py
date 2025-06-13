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

# Config dosyası oluşturulması önerilir
class Config:
    # Hardware pins
    MOTOR_PINS = {
        'IN1': 26, 'IN2': 19, 'IN3': 13, 'IN4': 6
    }
    SENSOR_PINS = {
        'TRIG_1': 23, 'ECHO_1': 24,
        'TRIG_2': 17, 'ECHO_2': 18
    }
    # Scan settings
    DEFAULT_SCAN_SETTINGS = {
        'horizontal_angle': 270.0,
        'horizontal_step': 10.0,
        'vertical_angle': 180.0,
        'vertical_step': 15.0
    }

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
    logger.error(f"SensorScript: Django entegrasyonu BAŞARISIZ: {e}")
    sys.exit(1)

# --- DONANIM KÜTÜPHANELERİ ---
try:
    from gpiozero import DistanceSensor, LED, Buzzer, OutputDevice, Servo
    from RPLCD.i2c import CharLCD
    from gpiozero import Device

    print("SensorScript: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    print(f"SensorScript: Gerekli donanım kütüphanesi bulunamadı: {e}")
    sys.exit(1)

# --- PIGPIO KURULUMU (DAHA İYİ PERFORMANS İÇİN) ---
try:
    from gpiozero.pins.pigpio import PiGPIOFactory
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}")
    print("Varsayılan pin factory kullanılıyor...")
    # pigpio olmadan da servo çalışabilir

# --- SABİTLER VE PINLER ---
MOTOR_BAGLI = True
STEP_MOTOR_IN1, STEP_MOTOR_IN2, STEP_MOTOR_IN3, STEP_MOTOR_IN4 = 26, 19, 13, 6
TRIG_PIN_1, ECHO_PIN_1 = 23, 24
TRIG_PIN_2, ECHO_PIN_2 = 17, 18
SERVO_PIN, BUZZER_PIN, LED_PIN = 4, 25, 27
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1
LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'

DEFAULT_HORIZONTAL_SCAN_ANGLE = 270.0
DEFAULT_HORIZONTAL_STEP_ANGLE = 10.0
DEFAULT_VERTICAL_SCAN_ANGLE = 180.0
DEFAULT_VERTICAL_STEP_ANGLE = 15.0
DEFAULT_BUZZER_DISTANCE = 10
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
STEP_MOTOR_SETTLE_TIME = 0.05
LOOP_TARGET_INTERVAL_S = 0.2

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, current_scan_object_global = None, None
sensor_1, sensor_2, servo, buzzer, lcd, led = None, None, None, None, None, None
in1_dev_step, in2_dev_step, in3_dev_step, in4_dev_step = None, None, None, None
script_exit_status_global = Scan.Status.ERROR
current_motor_angle_global = 0.0
current_step_sequence_index = 0
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]
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
        print("Kilit dosyası oluşturulamadı. Başka bir script çalışıyor olabilir.")
        return False


def _stop_step_motor_pins():
    """Step motor pinlerini tamamen devre dışı bırakır"""
    if in1_dev_step: in1_dev_step.off()
    if in2_dev_step: in2_dev_step.off()
    if in3_dev_step: in3_dev_step.off()
    if in4_dev_step: in4_dev_step.off()


def release_resources_on_exit():
    pid = os.getpid()
    print(f"[{pid}] Kaynaklar serbest bırakılıyor... Son durum: {script_exit_status_global}")
    if current_scan_object_global and current_scan_object_global.status == Scan.Status.RUNNING:
        try:
            scan_to_update = Scan.objects.get(id=current_scan_object_global.id)
            scan_to_update.status = script_exit_status_global
            scan_to_update.end_time = timezone.now()
            scan_to_update.save()
        except Exception as e:
            print(f"DB çıkış hatası: {e}")

    _stop_step_motor_pins()
    if buzzer and buzzer.is_active: 
        buzzer.off()
    if lcd:
        try:
            lcd.clear()
        except Exception:
            pass
    if led and led.is_active: 
        led.off()

    for dev in [sensor_1, sensor_2, servo, buzzer, lcd, led, in1_dev_step, in2_dev_step, in3_dev_step, in4_dev_step]:
        if dev and hasattr(dev, 'close'):
            try:
                dev.close()
            except:
                pass

    if lock_file_handle:
        try:
            # Bu satırda noktalı virgül var, Python'da gereksiz
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN)  # ; kaldırılmalı
            lock_file_handle.close()
        except:
            pass
    for fp in [PID_FILE_PATH, LOCK_FILE_PATH]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError as e:
                print(f"Hata: {fp} dosyası silinemedi: {e}")
    print(f"[{pid}] Temizleme tamamlandı.")


def init_hardware():
    global sensor_1, sensor_2, servo, buzzer, lcd, led
    global in1_dev_step, in2_dev_step, in3_dev_step, in4_dev_step
    try:
        if MOTOR_BAGLI:
            in1_dev_step, in2_dev_step, in3_dev_step, in4_dev_step = OutputDevice(STEP_MOTOR_IN1), OutputDevice(
                STEP_MOTOR_IN2), OutputDevice(STEP_MOTOR_IN3), OutputDevice(STEP_MOTOR_IN4)
        
        sensor_1 = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1, max_distance=3.0, queue_len=5)
        sensor_2 = DistanceSensor(echo=ECHO_PIN_2, trigger=TRIG_PIN_2, max_distance=3.0, queue_len=5)
        
        # SG90 Mini Servo özel konfigürasyonu
        servo = Servo(SERVO_PIN, 
                     min_pulse_width=0.0005,    # 0.5ms - SG90 minimum
                     max_pulse_width=0.0025,    # 2.5ms - SG90 maksimum  
                     frame_width=0.02)          # 20ms - SG90 frame
        
        buzzer = Buzzer(BUZZER_PIN)
        led = LED(LED_PIN)
        
        # Servo başlangıç testi - SG90 için
        print("SG90 Servo test başlıyor...")
        servo.value = 0.0  # Orta pozisyon (90°)
        time.sleep(1)
        servo.value = -1.0  # Sol uç (0°)
        time.sleep(1) 
        servo.value = 1.0   # Sağ uç (180°)
        time.sleep(1)
        servo.value = 0.0   # Tekrar orta
        time.sleep(1)
        print("✓ SG90 Servo test tamamlandı")
        
        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS, auto_linebreaks=True)
            lcd.clear()
            lcd.write_string("Haritalama Modu")
        except Exception as e:
            print(f"UYARI: LCD başlatılamadı, LCD olmadan devam edilecek. Hata: {e}")
            lcd = None
        return True
    except Exception as e:
        print(f"KRİTİK HATA: Donanım başlatılamadı: {e}")
        traceback.print_exc()
        return False


def _set_step_motor_pins(s1, s2, s3, s4):
    """Step motor pinlerini ayarlar"""
    if in1_dev_step: in1_dev_step.value = bool(s1)
    if in2_dev_step: in2_dev_step.value = bool(s2)  
    if in3_dev_step: in3_dev_step.value = bool(s3)
    if in4_dev_step: in4_dev_step.value = bool(s4)

def _stop_step_motor_pins():
    """Step motor pinlerini tamamen kapatır"""
    _set_step_motor_pins(0, 0, 0, 0)

def _step_motor_4in(num_steps, direction_positive):
    global current_step_sequence_index

    if INVERT_MOTOR_DIRECTION:
        step_increment = -1 if direction_positive else 1
    else:
        step_increment = 1 if direction_positive else -1

    for _ in range(int(num_steps)):
        current_step_sequence_index = (current_step_sequence_index + step_increment) % len(step_sequence)
        _set_step_motor_pins(*step_sequence[current_step_sequence_index])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


def move_step_motor_to_angle(target_angle_deg, total_steps_per_rev):
    global current_motor_angle_global
    if not MOTOR_BAGLI or total_steps_per_rev <= 0: 
        return
    
    DEG_PER_STEP = 360.0 / total_steps_per_rev
    angle_diff = target_angle_deg - current_motor_angle_global
    if abs(angle_diff) < DEG_PER_STEP / 2: 
        return
    
    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    _step_motor_4in(num_steps, (angle_diff > 0))
    current_motor_angle_global = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME)
    
    # ÖNEMLİ: Motor hareketi bitince pinleri temizle
    _stop_step_motor_pins()


def create_scan_entry(h_angle, h_step, v_angle, buzzer_dist, steps_per_rev, invert_motor):
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=h_angle,
            step_angle_setting=h_step,
            end_angle_setting=v_angle,
            buzzer_distance_setting=buzzer_dist,
            steps_per_revolution_setting=steps_per_rev,
            invert_motor_direction_setting=invert_motor,
            status=Scan.Status.RUNNING)
        return True
    except Exception as e:
        print(f"DB Hatası (create_scan_entry): {e}");
        traceback.print_exc();
        return False


# MEVCUT SORUN:
def degree_to_servo_value(angle):
    """SG90 için 0-180 derece aralığını -1.0 ile 1.0 arasına dönüştürür"""
    # SG90: 0° = -1.0, 90° = 0.0, 180° = 1.0
    angle = max(0, min(180, angle))  # 0-180 aralığında sınırla
    return (angle / 90.0) - 1.0

def set_servo_angle(angle, delay=0.5):
    """SG90 servo açısını güvenli şekilde ayarlar"""
    if servo is None:
        print("HATA: Servo tanımlanmamış!")
        return
    
    try:
        servo_value = degree_to_servo_value(angle)
        print(f"Servo: {angle}° → {servo_value:.3f}")
        servo.value = servo_value
        time.sleep(delay)  # SG90'ın pozisyona ulaşması için bekleme
    except Exception as e:
        print(f"Servo hareket hatası: {e}")

# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gelişmiş 3D Haritalama Scripti")
    parser.add_argument("--h-angle", type=float, default=DEFAULT_HORIZONTAL_SCAN_ANGLE)
    parser.add_argument("--h-step", type=float, default=DEFAULT_HORIZONTAL_STEP_ANGLE)
    parser.add_argument("--buzzer-distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    parser.add_argument("--steps-per-rev", type=int, default=4096, help="Motorun bir tam devirdeki adım sayısı.")
    parser.add_argument("--invert-motor", action='store_true', help="Bu bayrak varsa motor yönü ters çevrilir.")
    args = parser.parse_args()

    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware(): 
        sys.exit(1)

    TOTAL_H_ANGLE = args.h_angle
    H_STEP = args.h_step
    BUZZER_DISTANCE = args.buzzer_distance
    STEPS_PER_REVOLUTION = args.steps_per_rev
    INVERT_MOTOR_DIRECTION = args.invert_motor

    if not create_scan_entry(TOTAL_H_ANGLE, H_STEP, DEFAULT_VERTICAL_SCAN_ANGLE, BUZZER_DISTANCE, STEPS_PER_REVOLUTION,
                             INVERT_MOTOR_DIRECTION):
        sys.exit(1)

    try:
        initial_horizontal_angle = - (TOTAL_H_ANGLE / 2.0)
        print(f"Step motor başlangıç pozisyonuna gidiliyor: {initial_horizontal_angle:.1f}°...")
        move_step_motor_to_angle(initial_horizontal_angle, STEPS_PER_REVOLUTION)
        _stop_step_motor_pins()

        # SG90 servo başlangıç pozisyonu
        print("SG90 servo başlangıç pozisyonuna ayarlanıyor...")
        set_servo_angle(0, delay=1.5)  # 0° pozisyonu, 1.5s bekle

        num_horizontal_steps = int(TOTAL_H_ANGLE / H_STEP)
        for i in range(num_horizontal_steps + 1):
            target_h_angle_abs = initial_horizontal_angle + (i * H_STEP)
            target_h_angle_rel = i * H_STEP

            # Step motor hareketi
            move_step_motor_to_angle(target_h_angle_abs, STEPS_PER_REVOLUTION)
            print(f"\nYatay Açı: {target_h_angle_rel:.1f}° (Mutlak: {target_h_angle_abs:.1f}°)")

            num_vertical_steps = int(DEFAULT_VERTICAL_SCAN_ANGLE / DEFAULT_VERTICAL_STEP_ANGLE)
            for j in range(num_vertical_steps + 1):
                target_v_angle = j * DEFAULT_VERTICAL_STEP_ANGLE
                
                # SG90 servo hareketi - güvenli şekilde
                set_servo_angle(target_v_angle, delay=0.4)  # SG90 için 400ms yeterli
                
                # Ölçüm işlemleri...
                raw_dist_1 = sensor_1.distance
                raw_dist_2 = sensor_2.distance
                dist_cm_1 = (raw_dist_1 * 100) if raw_dist_1 is not None else sensor_1.max_distance * 100
                dist_cm_2 = (raw_dist_2 * 100) if raw_dist_2 is not None else sensor_2.max_distance * 100

                dist_for_xyz = dist_cm_2
                dist_for_alert = min(dist_cm_1, dist_cm_2)

                print(f"  -> Dikey: {target_v_angle:.1f}°, S1: {dist_cm_1:.1f}cm, S2: {dist_cm_2:.1f}cm")

                # LCD ve buzzer işlemleri...
                if lcd:
                    try:
                        lcd.cursor_pos = (0, 0)
                        lcd.write_string(f"Y:{target_h_angle_rel:<4.0f} V:{target_v_angle:<4.0f}  ")
                        lcd.cursor_pos = (1, 0)
                        lcd.write_string(f"S1:{dist_cm_1:<4.0f} S2:{dist_cm_2:<4.0f} ")
                    except OSError as e:
                        print(f"LCD YAZMA HATASI: {e}")

                if buzzer.is_active != (0 < dist_for_alert < BUZZER_DISTANCE): 
                    buzzer.toggle()

                # LED kontrolü...
                if led:
                    if 0 < dist_for_alert < BUZZER_DISTANCE:
                        if not led.is_active:
                            led.on()
                    else:
                        if led.is_active:
                            led.off()
                        led.on()
                        time.sleep(0.05)
                        led.off()

                # 3D koordinat hesaplama...
                angle_pan_rad, angle_tilt_rad = math.radians(target_h_angle_abs), math.radians(target_v_angle)
                h_radius = dist_for_xyz * math.cos(angle_tilt_rad)
                z = dist_for_xyz * math.sin(angle_tilt_rad)
                x = h_radius * math.cos(angle_pan_rad)
                y = h_radius * math.sin(angle_pan_rad)

                # Database kayıt
                ScanPoint.objects.create(
                    scan=current_scan_object_global,
                    derece=target_h_angle_rel,
                    dikey_aci=target_v_angle,
                    mesafe_cm=dist_for_xyz,
                    x_cm=x, y_cm=y, z_cm=z,
                    timestamp=timezone.now()
                )

        script_exit_status_global = Scan.Status.COMPLETED
        
    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        print(f"KRİTİK HATA: {e}")
        traceback.print_exc()
    finally:
        print("İşlem sonlanıyor. Motorlar durduruluyor ve servo merkeze getiriliyor...")
        _stop_step_motor_pins()
        if servo: 
            set_servo_angle(90, delay=1.0)  # Orta pozisyon (90°)
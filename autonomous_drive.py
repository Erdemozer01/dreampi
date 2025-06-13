import os
import sys
import time
import argparse
import fcntl
import atexit
import math
import traceback

# --- DJANGO ENTEGRASYONU ---
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

# --- DONANIM KÜTÜPHANELERİ ---
try:
    from gpiozero import DistanceSensor, LED, Buzzer, OutputDevice, Servo
    from RPLCD.i2c import CharLCD
    from gpiozero.pins.pigpio import PiGPIOFactory
    from gpiozero import Device

    print("SensorScript: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    print(f"SensorScript: Gerekli donanım kütüphanesi bulunamadı: {e}")
    sys.exit(1)

# --- PIGPIO KURULUMU (DAHA İYİ PERFORMANS İÇİN) ---
# DÜZELTME: pigpio daemon'a bağlanmaya çalış, başarısız olursa çökme, uyarı ver ve devam et.
try:
    Device.pin_factory = PiGPIOFactory()
    print("SensorScript: pigpio pin factory başarıyla ayarlandı.")
except (IOError, OSError):
    print("UYARI: pigpio daemon'a bağlanılamadı. Servo ve PWM daha az kararlı çalışabilir.")
    print("Çözüm için terminale 'sudo systemctl start pigpiod' yazmayı deneyin.")
    # Scriptin çökmesini engellemek için varsayılan factory'e geri dönmesine izin ver.
    pass

# --- SABİTLER VE PINLER ---
MOTOR_BAGLI = True
TRIG_PIN, ECHO_PIN = 23, 24
SERVO_PIN = 12
IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
BUZZER_PIN = 17
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'

# Varsayılan Değerler
DEFAULT_HORIZONTAL_SCAN_ANGLE = 270.0
DEFAULT_HORIZONTAL_STEP_ANGLE = 10.0
DEFAULT_VERTICAL_SCAN_ANGLE = 180.0
DEFAULT_VERTICAL_STEP_ANGLE = 15.0
DEFAULT_BUZZER_DISTANCE = 10
DEFAULT_INVERT_MOTOR_DIRECTION = False
DEFAULT_STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY, STEP_MOTOR_SETTLE_TIME, LOOP_TARGET_INTERVAL_S = 0.0015, 0.05, 0.2

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, current_scan_object_global = None, None
sensor, servo, buzzer, lcd = None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
script_exit_status_global = Scan.Status.ERROR
DEG_PER_STEP = 0.0
current_motor_angle_global = 0.0
current_step_sequence_index = 0
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
        print("Kilit dosyası oluşturulamadı. Başka bir script çalışıyor olabilir.")
        return False


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

    _set_step_pins(0, 0, 0, 0)
    if buzzer and buzzer.is_active: buzzer.off()
    if lcd:
        try:
            lcd.clear()
        except Exception as e:
            print(f"LCD temizlenemedi: {e}")

    for dev in [sensor, servo, buzzer, lcd, in1_dev, in2_dev, in3_dev, in4_dev]:
        if dev and hasattr(dev, 'close'):
            try:
                dev.close()
            except:
                pass

    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN); lock_file_handle.close()
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
    global sensor, servo, buzzer, lcd, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        if MOTOR_BAGLI: 
            in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(
                IN2_GPIO_PIN), OutputDevice(IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)
        
        # Servo konfigürasyonu iyileştirildi
        servo = Servo(SERVO_PIN, min_pulse_width=0.0005, max_pulse_width=0.0025)
        
        buzzer = Buzzer(BUZZER_PIN)
        
        # Servo test
        print("Servo test ediliyor...")
        servo.value = 0.0  # Orta pozisyon
        time.sleep(1)
        print(f"Servo pozisyonu: {servo.value}")
        
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


def _set_step_pins(s1, s2, s3, s4):
    if in1_dev: in1_dev.value = bool(s1)
    if in2_dev: in2_dev.value = bool(s2)
    if in3_dev: in3_dev.value = bool(s3)
    if in4_dev: in4_dev.value = bool(s4)

def _stop_step_motor():
    """Step motor pinlerini tamamen kapatır"""
    _set_step_pins(0, 0, 0, 0)

def _step_motor_4in(num_steps, direction_positive):
    global current_step_sequence_index
    
    # INVERT_MOTOR_DIRECTION desteği eklendi
    if 'INVERT_MOTOR' in globals() and INVERT_MOTOR:
        direction_positive = not direction_positive
    
    for _ in range(int(num_steps)):
        step_increment = 1 if direction_positive else -1
        current_step_sequence_index = (current_step_sequence_index + step_increment) % len(step_sequence)
        _set_step_pins(*step_sequence[current_step_sequence_index])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)

def move_motor_to_angle(target_angle_deg, invert_direction):
    global current_motor_angle_global
    if not MOTOR_BAGLI or DEG_PER_STEP <= 0: 
        return
    
    angle_diff = target_angle_deg - current_motor_angle_global
    if abs(angle_diff) < DEG_PER_STEP: 
        return
    
    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    logical_dir = (angle_diff > 0)
    physical_dir = not logical_dir if invert_direction else logical_dir
    _step_motor_4in(num_steps, physical_dir)
    current_motor_angle_global = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME)
    
    # Motor hareketi bitince pinleri temizle
    _stop_step_motor()


def create_scan_entry(h_angle, h_step, v_angle, buzzer_dist, invert_dir, steps_rev):
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=h_angle, step_angle_setting=h_step, end_angle_setting=v_angle,
            buzzer_distance_setting=buzzer_dist, invert_motor_direction_setting=invert_dir,
            status=Scan.Status.RUNNING)
        return True
    except Exception as e:
        print(f"DB Hatası (create_scan_entry): {e}");
        traceback.print_exc();
        return False


def degree_to_servo_value(angle):
    """0-180 derece aralığını -1.0 ile 1.0 arasına dönüştürür"""
    angle = max(0, min(180, angle))
    return (angle / 90.0) - 1.0


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gelişmiş 3D Haritalama Scripti")
    parser.add_argument("--h-angle", type=float, default=DEFAULT_HORIZONTAL_SCAN_ANGLE)
    parser.add_argument("--h-step", type=float, default=DEFAULT_HORIZONTAL_STEP_ANGLE)
    parser.add_argument("--buzzer-distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    parser.add_argument("--invert-motor-direction", type=lambda x: str(x).lower() == 'true',
                        default=DEFAULT_INVERT_MOTOR_DIRECTION)
    parser.add_argument("--steps-per-rev", type=int, default=DEFAULT_STEPS_PER_REVOLUTION)
    args = parser.parse_args()

    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)

    TOTAL_H_ANGLE, H_STEP, INVERT_MOTOR, STEPS_PER_REVOLUTION, BUZZER_DISTANCE = args.h_angle, args.h_step, args.invert_motor_direction, args.steps_per_rev, args.buzzer_distance
    DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION

    if not create_scan_entry(TOTAL_H_ANGLE, H_STEP, DEFAULT_VERTICAL_SCAN_ANGLE, BUZZER_DISTANCE, INVERT_MOTOR,
                             STEPS_PER_REVOLUTION): sys.exit(1)

    try:
        initial_turn_angle = - (TOTAL_H_ANGLE / 2.0)
        print(f"Başlangıç pozisyonuna gidiliyor: {initial_turn_angle:.1f}°...")
        move_motor_to_angle(initial_turn_angle, INVERT_MOTOR)
        
        # Servo başlangıç testi
        print("Servo başlangıç testı...")
        servo.value = degree_to_servo_value(0)   # 0°
        time.sleep(1)
        servo.value = degree_to_servo_value(90)  # 90°
        time.sleep(1)
        servo.value = degree_to_servo_value(0)   # Tekrar 0°
        time.sleep(1.5)

# Ana döngüde:
        num_horizontal_steps = int(TOTAL_H_ANGLE / H_STEP)
        for i in range(num_horizontal_steps + 1):
            target_h_angle_abs = initial_turn_angle + (i * H_STEP)
            target_h_angle_rel = i * H_STEP
            
            # Step motor hareketi
            move_motor_to_angle(target_h_angle_abs, INVERT_MOTOR)
            print(f"\nYatay Açı: {target_h_angle_rel:.1f}°")

            num_vertical_steps = int(DEFAULT_VERTICAL_SCAN_ANGLE / DEFAULT_VERTICAL_STEP_ANGLE)
            for j in range(num_vertical_steps + 1):
                target_v_angle = j * DEFAULT_VERTICAL_STEP_ANGLE
                
                # Servo hareketi
                servo.value = degree_to_servo_value(target_v_angle)
                
                # Yeterli bekleme süresi
                time.sleep(max(LOOP_TARGET_INTERVAL_S, 0.3))
                
                # Ölçüm işlemleri...
                dist_cm = sensor.distance * 100
                print(f"  -> Dikey: {target_v_angle:.1f}°, Mesafe: {dist_cm:.1f} cm")

                if lcd:
                    try:
                        lcd.cursor_pos = (0, 0);
                        lcd.write_string(f"Y:{target_h_angle_rel:<4.0f} V:{target_v_angle:<4.0f}  ")
                        lcd.cursor_pos = (1, 0);
                        lcd.write_string(f"Mesafe: {dist_cm:<5.1f}cm ")
                    except OSError as e:
                        print(f"LCD YAZMA HATASI: {e}")

                if buzzer.is_active != (0 < dist_cm < BUZZER_DISTANCE): buzzer.toggle()

                angle_pan_rad, angle_tilt_rad = math.radians(target_h_angle_abs), math.radians(target_v_angle)
                h_radius = dist_cm * math.cos(angle_tilt_rad)
                z, x, y = dist_cm * math.sin(angle_tilt_rad), h_radius * math.cos(angle_pan_rad), h_radius * math.sin(
                    angle_pan_rad)
                ScanPoint.objects.create(scan=current_scan_object_global, derece=target_h_angle_rel,
                                         dikey_aci=target_v_angle, mesafe_cm=dist_cm, x_cm=x, y_cm=y, z_cm=z,
                                         timestamp=timezone.now())

        script_exit_status_global = Scan.Status.COMPLETED
    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        print(f"KRİTİK HATA: {e}");
        traceback.print_exc()
    finally:
        print("İşlem sonlanıyor. Motor merkez konuma getiriliyor...")
        move_motor_to_angle(0, INVERT_MOTOR)
        _stop_step_motor()  # Pinleri temizle
        if servo: 
            servo.value = degree_to_servo_value(90)
            time.sleep(0.5)
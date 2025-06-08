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
try:
    from gpiozero import DistanceSensor, LED, Buzzer, OutputDevice, Servo
    from RPLCD.i2c import CharLCD
except ImportError as e:
    print(f"SensorScript: Gerekli donanım kütüphanesi bulunamadı: {e}")
    print("Lütfen 'sudo pip3 install gpiozero RPLCD-i2c' komutlarıyla yükleyin.")
    sys.exit(1)

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
DEFAULT_VERTICAL_SCAN_ANGLE = 180.0
DEFAULT_VERTICAL_STEP_ANGLE = 10.0
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
    """Verilen dereceyi -1.0 ile 1.0 aralığındaki servo değerine çevirir."""
    clamped_angle = max(0, min(180, angle_deg))
    return (clamped_angle / 90.0) - 1.0


def init_hardware():
    """Tüm donanım bileşenlerini başlatır ve kullanıma hazırlar."""
    global sensor, sensor2, servo, yellow_led, buzzer, lcd, in1_dev, in2_dev, in3_dev, in4_dev
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
        traceback.print_exc()
        return False


def _set_step_pins(s1, s2, s3, s4):
    """Step motor pinlerinin durumunu ayarlar."""
    if in1_dev: in1_dev.value = bool(s1)
    if in2_dev: in2_dev.value = bool(s2)
    if in3_dev: in3_dev.value = bool(s3)
    if in4_dev: in4_dev.value = bool(s4)


def _step_motor_4in(num_steps, direction_positive):
    """Step motoru belirtilen adım sayısı kadar döndürür."""
    global current_step_sequence_index
    for _ in range(int(num_steps)):
        current_step_sequence_index = (current_step_sequence_index + (1 if direction_positive else -1) + len(
            step_sequence)) % len(step_sequence)
        _set_step_pins(*step_sequence[current_step_sequence_index])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)
    time.sleep(STEP_MOTOR_SETTLE_TIME)


def move_motor_to_angle(target_angle_deg, invert_direction):
    """Step motoru hedef açıya hareket ettirir."""
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


def shoelace_formula(points):
    """Verilen 2D noktalarla çevrili alanın yaklaşık değerini hesaplar."""
    if len(points) < 3: return 0.0
    return 0.5 * abs(sum(
        points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in
        range(len(points))))


def calculate_perimeter(points):
    """Verilen 2D noktaların oluşturduğu şeklin çevresini hesaplar."""
    if not points: return 0.0
    # Orijinden ilk noktaya olan uzaklıkla başla
    perimeter = math.hypot(points[0][0], points[0][1])
    # Noktalar arasındaki mesafeleri ekle
    for i in range(len(points) - 1):
        perimeter += math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
    # Son noktadan orijine olan uzaklığı ekle
    perimeter += math.hypot(points[-1][0], points[-1][1])
    return perimeter


def create_scan_entry(h_angle, h_step, v_angle, buzzer_dist, invert_dir):
    """Veritabanında yeni bir tarama kaydı oluşturur."""
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR)
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=h_angle,
            step_angle_setting=h_step,
            end_angle_setting=v_angle,  # Dikey tarama açısını bu alana kaydediyoruz
            buzzer_distance_setting=buzzer_dist,
            invert_motor_direction_setting=invert_dir,
            status=Scan.Status.RUNNING
        )
        print(f"Yeni tarama kaydı veritabanında oluşturuldu: ID #{current_scan_object_global.id}")
        return True
    except Exception as e:
        print(f"DB Hatası (create_scan_entry): {e}")
        return False


def acquire_lock_and_pid():
    """Script'in başka bir kopyasının çalışmasını engellemek için kilit dosyası oluşturur."""
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
    """Script sonlandığında tüm kaynakları güvenli bir şekilde serbest bırakır."""
    pid = os.getpid()
    print(f"[{pid}] Kaynaklar serbest bırakılıyor... Durum: {script_exit_status_global}")
    if current_scan_object_global and current_scan_object_global.status == Scan.Status.RUNNING:
        try:
            # Django ORM'nin zaman aşımlarını önlemek için objeyi yeniden al
            scan_to_update = Scan.objects.get(id=current_scan_object_global.id)
            scan_to_update.status = script_exit_status_global
            scan_to_update.save()
            print(f"Scan #{scan_to_update.id} durumu güncellendi: {scan_to_update.status}")
        except Exception as e:
            print(f"DB çıkış HATA: {e}")

    if MOTOR_BAGLI: _set_step_pins(0, 0, 0, 0)
    if lcd:
        try:
            lcd.clear()
        except Exception:
            pass

    for dev in [sensor, sensor2, servo, yellow_led, buzzer, in1_dev, in2_dev, in3_dev, in4_dev, lcd]:
        if dev and hasattr(dev, 'close'):
            try:
                dev.close()
            except Exception:
                pass

    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN)
            lock_file_handle.close()
        except Exception:
            pass

    for fp in [PID_FILE_PATH, LOCK_FILE_PATH]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError as e:
                print(f"Hata: {fp} dosyası silinemedi: {e}")

    print(f"[{pid}] Temizleme tamamlandı.")


# ==============================================================================
# --- ANA ÇALIŞMA BLOĞU ---
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pozitif Açılı, İç İçe Döngülü Tarama Scripti")
    # Yatay Tarama Argümanları
    parser.add_argument("--horizontal_scan_angle", type=float, default=DEFAULT_HORIZONTAL_SCAN_ANGLE,
                        help="Toplam yatay tarama açısı (derece). Tarama 0'dan başlar.")
    parser.add_argument("--horizontal_step_angle", type=float, default=DEFAULT_HORIZONTAL_STEP_ANGLE,
                        help="Yatay tarama için adım açısı.")

    # Dikey Tarama Argümanları
    parser.add_argument("--vertical_scan_angle", type=float, default=DEFAULT_VERTICAL_SCAN_ANGLE,
                        help="Toplam dikey tarama açısı (derece).")
    parser.add_argument("--vertical_step_angle", type=float, default=DEFAULT_VERTICAL_STEP_ANGLE,
                        help="Dikey tarama için adım açısı.")

    parser.add_argument("--buzzer_distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    parser.add_argument("--invert_motor_direction", type=lambda x: str(x).lower() == 'true',
                        default=DEFAULT_INVERT_MOTOR_DIRECTION)
    parser.add_argument("--steps_per_rev", type=int, default=DEFAULT_STEPS_PER_REVOLUTION)
    args = parser.parse_args()

    pid = os.getpid()
    atexit.register(release_resources_on_exit)

    if not acquire_lock_and_pid():
        sys.exit(1)
    if not init_hardware():
        sys.exit(1)

    # Parametreleri al
    HORIZONTAL_TOTAL_ANGLE = args.horizontal_scan_angle
    HORIZONTAL_STEP_ANGLE = args.horizontal_step_angle
    VERTICAL_TOTAL_ANGLE = args.vertical_scan_angle
    VERTICAL_STEP_ANGLE = args.vertical_step_angle
    INVERT_MOTOR = args.invert_motor_direction
    STEPS_PER_REVOLUTION = args.steps_per_rev
    BUZZER_DISTANCE = args.buzzer_distance
    DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION

    if not create_scan_entry(HORIZONTAL_TOTAL_ANGLE, HORIZONTAL_STEP_ANGLE, VERTICAL_TOTAL_ANGLE, BUZZER_DISTANCE,
                             INVERT_MOTOR):
        sys.exit(1)

    print(f"[{pid}] Yeni Pozitif Açılı Tarama Başlatılıyor (ID: #{current_scan_object_global.id})...")

    try:
        print(f"[ADIM 0] Başlangıç pozisyonuna gidiliyor (0° Yatay, 0° Dikey)...")
        move_motor_to_angle(0, INVERT_MOTOR)
        servo.value = degree_to_servo_value(0)
        time.sleep(1.5)

        if HORIZONTAL_STEP_ANGLE <= 0 or VERTICAL_STEP_ANGLE <= 0:
            raise ValueError("Adım açıları 0'dan büyük olmalıdır!")

        collected_points_for_analysis = []

        # DIŞ DÖNGÜ: Yatay Hareket (Step Motor)
        num_horizontal_steps = int(HORIZONTAL_TOTAL_ANGLE / HORIZONTAL_STEP_ANGLE)
        for h_step in range(num_horizontal_steps + 1):
            current_h_angle = h_step * HORIZONTAL_STEP_ANGLE
            if current_h_angle > HORIZONTAL_TOTAL_ANGLE:
                current_h_angle = HORIZONTAL_TOTAL_ANGLE

            move_motor_to_angle(current_h_angle, INVERT_MOTOR)
            print(f"\nYatay Açıya Geçildi: {current_h_angle:.1f}°")

            # İÇ DÖNGÜ: Dikey Hareket (Servo Motor)
            num_vertical_steps = int(VERTICAL_TOTAL_ANGLE / VERTICAL_STEP_ANGLE)
            for v_step in range(num_vertical_steps + 1):
                current_v_angle = v_step * VERTICAL_STEP_ANGLE
                if current_v_angle > VERTICAL_TOTAL_ANGLE:
                    current_v_angle = VERTICAL_TOTAL_ANGLE

                servo.value = degree_to_servo_value(current_v_angle)
                time.sleep(LOOP_TARGET_INTERVAL_S)

                dist_cm = sensor.distance * 100
                dist_cm_2 = sensor2.distance * 100

                print(
                    f"  -> Y:{current_h_angle:.1f}° V:{current_v_angle:.1f}° -> S1:{dist_cm:.1f}cm S2:{dist_cm_2:.1f}cm")

                if buzzer.is_active != (dist_cm < BUZZER_DISTANCE or dist_cm_2 < BUZZER_DISTANCE):
                    buzzer.toggle()

                # Koordinatları hesapla ve veritabanına kaydet
                angle_pan_rad = math.radians(current_h_angle)
                angle_tilt_rad = math.radians(current_v_angle)
                horizontal_radius = dist_cm * math.cos(angle_tilt_rad)
                z_cm_val = dist_cm * math.sin(angle_tilt_rad)
                x_cm_val = horizontal_radius * math.cos(angle_pan_rad)
                y_cm_val = horizontal_radius * math.sin(angle_pan_rad)

                if 0 < dist_cm < (sensor.max_distance * 100 - 1):
                    collected_points_for_analysis.append((x_cm_val, y_cm_val))

                ScanPoint.objects.create(
                    scan=current_scan_object_global,
                    derece=current_h_angle,
                    dikey_aci=current_v_angle,
                    mesafe_cm=dist_cm,
                    x_cm=x_cm_val, y_cm=y_cm_val, z_cm=z_cm_val,
                    mesafe_cm_2=dist_cm_2,
                    timestamp=timezone.now()
                )

            # Bir sonraki yatay adıma geçmeden servoyu sıfırla
            servo.value = degree_to_servo_value(0)
            time.sleep(0.2)

        print(f"[{pid}] Tarama bitti.")

        if len(collected_points_for_analysis) >= 3:
            print("Analiz metrikleri hesaplanıyor...")
            polygon_for_area = [(0, 0)] + collected_points_for_analysis
            area = shoelace_formula(polygon_for_area)
            perimeter = calculate_perimeter(collected_points_for_analysis)
            x_coords = [p[0] for p in collected_points_for_analysis]
            y_coords = [p[1] for p in collected_points_for_analysis]
            width = (max(y_coords) - min(y_coords)) if y_coords else 0.0
            depth = max(x_coords) if x_coords else 0.0

            current_scan_object_global.calculated_area_cm2 = area
            current_scan_object_global.perimeter_cm = perimeter
            current_scan_object_global.max_width_cm = width
            current_scan_object_global.max_depth_cm = depth
            print("Metrikler veritabanına kaydedildi.")

        script_exit_status_global = Scan.Status.COMPLETED

    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED
        print(f"\n[{pid}] Ctrl+C ile kesildi.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR
        print(f"[{pid}] KRİTİK HATA: Ana döngüde bir hata oluştu: {e}")
        traceback.print_exc()
    finally:
        print(f"[{pid}] ADIM SON: Başlangıç konumuna (0,0) dönülüyor...")
        move_motor_to_angle(0, INVERT_MOTOR)
        if servo: servo.value = degree_to_servo_value(0)
        print(f"[{pid}] Başlangıç konumuna dönüldü.")
        # `release_resources_on_exit` atexit tarafından otomatik olarak çağrılacak.
        # Ancak script'in sonlandığını belirtmek için durumu burada güncelleyebiliriz.
        if current_scan_object_global:
            current_scan_object_global.status = script_exit_status_global
            current_scan_object_global.save()
        print(f"[{pid}] Betik sonlanıyor.")
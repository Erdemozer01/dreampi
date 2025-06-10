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
    # from gpiozero.pins.pigpio import PiGPIOFactory # Bu satır kaldırıldı
    from gpiozero import Device

    print("SensorScript: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    print(f"SensorScript: Gerekli donanım kütüphanesi bulunamadı: {e}")
    sys.exit(1)

# --- PIGPIO KURULUMU (DAHA İYİ PERFORMANS İÇİN) ---
# pigpio factory ayarı kaldırıldı, gpiozero varsayılan pin factory'yi kullanacak.
try:
    # Device.pin_factory = PiGPIOFactory() # Bu satır kaldırıldı
    print("SensorScript: pigpio pin factory ayarı devre dışı, varsayılan kullanılıyor.")
except (IOError, OSError):
    print("UYARI: pigpio daemon'a bağlanılamadı. Servo ve PWM daha az kararlı çalışabilir. Varsayılan pin factory kullanılıyor.")
    pass

# --- SABİTLER VE PINLER ---
MOTOR_BAGLI = True

# Step Motor için L298N pinleri (Lütfen bu pinleri kendi bağlantılarınıza göre kontrol edin ve ayarlayın!)
STEP_MOTOR_IN1 = 6
STEP_MOTOR_IN2 = 13
STEP_MOTOR_IN3 = 19
STEP_MOTOR_IN4 = 26

# Ultrasonik Mesafe Sensörleri (GPIO20 kullanıldı)
TRIG_PIN_1, ECHO_PIN_1 = 23, 24   # Birinci ultrasonik sensör (Step motor üzerinde)
TRIG_PIN_2, ECHO_PIN_2 = 16, 5   # İkinci ultrasonik sensör (Servo üzerinde)

SERVO_PIN = 12
BUZZER_PIN = 17
LED_PIN = 27 # LED pini

LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'

# Varsayılan Değerler
DEFAULT_HORIZONTAL_SCAN_ANGLE = 270.0
DEFAULT_HORIZONTAL_STEP_ANGLE = 10.0
DEFAULT_VERTICAL_SCAN_ANGLE = 180.0
DEFAULT_VERTICAL_STEP_ANGLE = 15.0
DEFAULT_BUZZER_DISTANCE = 10

# Step Motor Gecikmeleri ve Ayarları
DEFAULT_STEPS_PER_REVOLUTION = 4096 # Motorunuzun bir turdaki adım sayısı (örn: 28BYJ-48 için 2048 veya 4096)
STEP_MOTOR_INTER_STEP_DELAY = 0.0015 # Adımlar arası gecikme (motor hızını etkiler)
STEP_MOTOR_SETTLE_TIME = 0.05 # Motorun konumuna geldikten sonra bekleme süresi

LOOP_TARGET_INTERVAL_S = 0.2 # Sensör okumaları arası genel bekleme süresi (Motor ve servo hareketini de içerir)

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, current_scan_object_global = None, None
sensor_1, sensor_2, servo, buzzer, lcd, led = None, None, None, None, None, None

# Step motor pin objeleri
in1_dev_step, in2_dev_step, in3_dev_step, in4_dev_step = None, None, None, None

script_exit_status_global = Scan.Status.ERROR
current_motor_angle_global = 0.0 # Step motor için yatay açı takibi
current_step_sequence_index = 0 # Step motor adım sırası takip
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]] # Tam adım veya yarım adım dizisi (L298N için)


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
    """Step motor pinlerini sıfırlar."""
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

    _stop_step_motor_pins() # Step motor pinlerini sıfırla
    if buzzer and buzzer.is_active: buzzer.off()
    if lcd:
        try:
            lcd.clear()
        except Exception as e:
            print(f"LCD temizlenemedi: {e}")
    if led and led.is_active: led.off() # LED'i kapatma

    for dev in [sensor_1, sensor_2, servo, buzzer, lcd, led,
                in1_dev_step, in2_dev_step, in3_dev_step, in4_dev_step]:
        if dev and hasattr(dev, 'pin') and dev.pin: # 'pin' özniteliği ve varlığı kontrolü
            try:
                dev.close()
            except:
                pass
        elif dev and hasattr(dev, 'close'): # Sadece 'close' özniteliği olanlar için (örn: lcd)
            try:
                dev.close()
            except:
                pass


    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN);
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
        if MOTOR_BAGLI: # Step motor kullanılıyorsa
            # Step motor pinleri
            in1_dev_step = OutputDevice(STEP_MOTOR_IN1)
            in2_dev_step = OutputDevice(STEP_MOTOR_IN2)
            in3_dev_step = OutputDevice(STEP_MOTOR_IN3)
            in4_dev_step = OutputDevice(STEP_MOTOR_IN4)

        # Ultrasonik mesafe sensörleri
        # queue_len parametresi eklendi
        sensor_1 = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1, max_distance=3.0, queue_len=5)
        sensor_2 = DistanceSensor(echo=ECHO_PIN_2, trigger=TRIG_PIN_2, max_distance=3.0, queue_len=5)

        # Servo motor: Darbe genişlikleri ile başlatılıyor
        MIN_PULSE = 0.0005
        MAX_PULSE = 0.0025
        servo = Servo(SERVO_PIN, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE)

        # Buzzer
        buzzer = Buzzer(BUZZER_PIN)

        # LED başlatma
        led = LED(LED_PIN)

        # LCD Ekran (isteğe bağlı, hata durumunda script durmaz)
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
    """Step motor pinlerine değerleri ayarlar."""
    if in1_dev_step: in1_dev_step.value = bool(s1)
    if in2_dev_step: in2_dev_step.value = bool(s2)
    if in3_dev_step: in3_dev_step.value = bool(s3)
    if in4_dev_step: in4_dev_step.value = bool(s4)

def _step_motor_4in(num_steps, direction_positive):
    """
    4 pinli step motoru belirli sayıda adım döndürür.
    :param num_steps: Atılacak adım sayısı.
    :param direction_positive: True ise ileri, False ise geri.
    """
    global current_step_sequence_index
    for _ in range(int(num_steps)):
        step_increment = 1 if direction_positive else -1
        current_step_sequence_index = (current_step_sequence_index + step_increment) % len(step_sequence)
        _set_step_motor_pins(*step_sequence[current_step_sequence_index])
        time.sleep(STEP_MOTOR_INTER_STEP_DELAY)

def move_step_motor_to_angle(target_angle_deg, total_steps_per_rev):
    """
    Step motoru belirli bir mutlak açıya döndürür.
    :param target_angle_deg: Gidilecek hedef açı (derece).
    :param total_steps_per_rev: Motorun bir turdaki toplam adım sayısı.
    """
    global current_motor_angle_global
    if not MOTOR_BAGLI or total_steps_per_rev <= 0: return

    DEG_PER_STEP = 360.0 / total_steps_per_rev
    angle_diff = target_angle_deg - current_motor_angle_global

    # Eğer açı farkı çok küçükse veya zaten hedefe ulaşıldıysa hareket etme
    if abs(angle_diff) < DEG_PER_STEP / 2: # Yarım adımdan küçükse hareket etme
        return

    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    direction_positive = (angle_diff > 0) # Pozitif açı farkı için ileri

    _step_motor_4in(num_steps, direction_positive)
    current_motor_angle_global = target_angle_deg # Hedef açıyı mevcut açı olarak ayarla
    time.sleep(STEP_MOTOR_SETTLE_TIME) # Motorun yerine oturması için bekleme

def create_scan_entry(h_angle, h_step, v_angle, buzzer_dist):
    global current_scan_object_global
    try:
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())
        current_scan_object_global = Scan.objects.create(
            start_angle_setting=h_angle, step_angle_setting=h_step, end_angle_setting=v_angle,
            buzzer_distance_setting=buzzer_dist,
            invert_motor_direction_setting=False, # Step motor için bu ayar doğrudan kullanılmaz
            status=Scan.Status.RUNNING)
        return True
    except Exception as e:
        print(f"DB Hatası (create_scan_entry): {e}");
        traceback.print_exc();
        return False


def degree_to_servo_value(angle):
    # Bu fonksiyon, gpiozero Servo nesnesinin beklediği -1.0 ile 1.0 aralığına dönüştürür.
    return max(-1.0, min(1.0, (angle / 90.0) - 1.0))


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gelişmiş 3D Haritalama Scripti")
    parser.add_argument("--h-angle", type=float, default=DEFAULT_HORIZONTAL_SCAN_ANGLE)
    parser.add_argument("--h-step", type=float, default=DEFAULT_HORIZONTAL_STEP_ANGLE)
    parser.add_argument("--buzzer-distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    args = parser.parse_args()

    atexit.register(release_resources_on_exit)  # Çıkışta kaynakları serbest bırakma fonksiyonunu kaydet
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)  # Kilit al ve donanımı başlat

    TOTAL_H_ANGLE, H_STEP, BUZZER_DISTANCE = args.h_angle, args.h_step, args.buzzer_distance
    if not create_scan_entry(TOTAL_H_ANGLE, H_STEP, DEFAULT_VERTICAL_SCAN_ANGLE, BUZZER_DISTANCE): sys.exit(1)

    try:
        # Step motor başlangıç pozisyonuna ayarlanıyor: Tarama açısının yarısı kadar geriye dön
        # Bu, motoru taramanın en sol başlangıç noktasına getirir (örn: 270 derece tarama için -135 dereceye)
        initial_horizontal_angle = - (TOTAL_H_ANGLE / 2.0)
        print(f"Step motor başlangıç pozisyonuna gidiliyor: {initial_horizontal_angle:.1f}°...")
        move_step_motor_to_angle(initial_horizontal_angle, DEFAULT_STEPS_PER_REVOLUTION)
        _stop_step_motor_pins() # Hareket bitince motor pinlerini sıfırla

        # Servo başlangıç pozisyonu: Fiziksel 0 dereceye getir
        servo.value = degree_to_servo_value(0)
        time.sleep(1.5) # Motorların yerine oturması için bekleme süresi

        # current_motor_angle_global zaten initial_horizontal_angle olarak ayarlandı

        # Yatay tarama döngüsü (step motor ile)
        num_horizontal_steps = int(TOTAL_H_ANGLE / H_STEP)
        for i in range(num_horizontal_steps + 1):
            # Hedef yatay açı: Başlangıçtan itibaren H_STEP artışlarla ilerle
            target_h_angle_abs = initial_horizontal_angle + (i * H_STEP)
            target_h_angle_rel = i * H_STEP # Göreceli tarama açısı (0'dan itibaren)

            move_step_motor_to_angle(target_h_angle_abs, DEFAULT_STEPS_PER_REVOLUTION)
            _stop_step_motor_pins() # Her hareket sonrası motor pinlerini sıfırla
            print(f"\nYatay Açı: {target_h_angle_rel:.1f}° (Mutlak: {target_h_angle_abs:.1f}°)")

            # Dikey tarama döngüsü (servo ile)
            num_vertical_steps = int(DEFAULT_VERTICAL_SCAN_ANGLE / DEFAULT_VERTICAL_STEP_ANGLE)
            for j in range(num_vertical_steps + 1):
                target_v_angle = j * DEFAULT_VERTICAL_STEP_ANGLE # Servo'ya gönderilecek fiziksel açı

                servo.value = degree_to_servo_value(target_v_angle)
                time.sleep(LOOP_TARGET_INTERVAL_S) # Ölçüm için bekleme

                # Sensör okumaları
                dist_cm_1 = sensor_1.distance * 100 # Step motor üzerindeki sensör
                dist_cm_2 = sensor_2.distance * 100 # Servo üzerindeki sensör

                # Koordinat hesaplamaları ve kaydı için servo üzerindeki sensörün mesafesini kullan
                # Buzzer ve LED için her iki sensörden gelen en yakın mesafeyi kullan
                dist_for_xyz = dist_cm_2 # 3D koordinatlar için servo sensörünün mesafesi
                dist_for_alert = min(dist_cm_1, dist_cm_2) # Uyarılar için en yakın mesafe


                print(f"  -> Dikey: {target_v_angle:.1f}°, S1 Mesafe: {dist_cm_1:.1f} cm, S2 Mesafe: {dist_cm_2:.1f} cm, XYZ İçin: {dist_for_xyz:.1f} cm")

                if lcd:
                    try:
                        lcd.cursor_pos = (0, 0);
                        lcd.write_string(f"Y:{target_h_angle_rel:<4.0f} V:{target_v_angle:<4.0f}  ")
                        lcd.cursor_pos = (1, 0);
                        lcd.write_string(f"S1:{dist_cm_1:<4.0f} S2:{dist_cm_2:<4.0f} ") # LCD'ye iki mesafeyi de yaz
                    except OSError as e:
                        print(f"LCD YAZMA HATASI: {e}")

                if buzzer.is_active != (0 < dist_for_alert < BUZZER_DISTANCE): buzzer.toggle()

                # *** LED KONTROL MANTIĞI ***
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
                # *** LED KONTROL MANTIĞI SONU ***


                # Koordinat hesaplamaları: Burada step motorun mutlak yatay açısı
                # ve servo üzerindeki sensörün dikey açısı ve mesafesi kullanılacak.
                angle_pan_rad, angle_tilt_rad = math.radians(target_h_angle_abs), math.radians(target_v_angle)
                h_radius = dist_for_xyz * math.cos(angle_tilt_rad)
                z, x, y = dist_for_xyz * math.sin(angle_tilt_rad), h_radius * math.cos(angle_pan_rad), h_radius * math.sin(
                    angle_pan_rad)

                ScanPoint.objects.create(scan=current_scan_object_global, derece=target_h_angle_rel,
                                         dikey_aci=target_v_angle, mesafe_cm=dist_for_xyz, x_cm=x, y_cm=y, z_cm=z,
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
        print("İşlem sonlanıyor. Motorlar durduruluyor ve servo merkeze getiriliyor...")
        # Step motoru tarama başlangıç pozisyonuna geri getir
        move_step_motor_to_angle(initial_horizontal_angle, DEFAULT_STEPS_PER_REVOLUTION)
        _stop_step_motor_pins() # Pinleri kapat

        if servo: servo.value = degree_to_servo_value(90) # Servo motoru merkeze getir (fiziksel 90 derece)
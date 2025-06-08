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
DEFAULT_VERTICAL_SCAN_ANGLE = 180.0  # Servo'nun fiziksel tarama açısı (örn: 0-180 derece)
DEFAULT_VERTICAL_STEP_ANGLE = 15.0
DEFAULT_BUZZER_DISTANCE = 10
DEFAULT_INVERT_MOTOR_DIRECTION = False
DEFAULT_STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY, STEP_MOTOR_SETTLE_TIME, LOOP_TARGET_INTERVAL_S = 0.0015, 0.05, 0.6

# Servo'nun başlangıç açısını kaydırmak için yeni sabit
# Bu değer, servo'nun fiziksel 0 derecesine karşılık gelen mantıksal açıyı belirtir.
SERVO_VERTICAL_OFFSET_DEG = -30.0

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
    global sensor, servo, buzzer, lcd, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        if MOTOR_BAGLI:
            # Step motor pinleri
            in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(
                IN2_GPIO_PIN), OutputDevice(IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)

        # Ultrasonik mesafe sensörü
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)

        # Servo motor: Darbe genişlikleri ile başlatılıyor
        # Bu değerleri kendi servo motorunuzun modeline göre ayarlamanız KRİTİKTİR.
        # Genellikle veri sayfasında bulunur veya deneme yanılma ile bulunur.
        # Örnek değerler (SG90 gibi yaygın servolar için):
        # 500 µs = 0.0005 s
        # 2500 µs = 0.0025 s
        MIN_PULSE = 0.0005  # Genellikle 0 dereceye karşılık gelen minimum darbe genişliği (saniye cinsinden)
        MAX_PULSE = 0.0027  # Genellikle 180 dereceye karşılık gelen maksimum darbe genişliği (saniye cinsinden)

        # Eğer bu değerlerle tam 180 derece dönmüyorsa veya 0'a ulaşmıyorsa, küçük adımlarla ayarlama yapın.
        # Örneğin: MIN_PULSE = 0.00048, MAX_PULSE = 0.00252
        servo = Servo(SERVO_PIN, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE)

        # Buzzer
        buzzer = Buzzer(BUZZER_PIN)

        # LCD Ekran (isteğe bağlı, hata durumunda script durmaz)
        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS, auto_linebreaks=True)
            lcd.clear()
            lcd.write_string("Haritalama Modu")
        except Exception as e:
            print(f"UYARI: LCD başlatılamadı, LCD olmadan devam edilecek. Hata: {e}")
            lcd = None  # LCD başlatılamazsa None olarak ayarla
        return True
    except Exception as e:
        print(f"KRİTİK HATA: Donanım başlatılamadı: {e}")
        traceback.print_exc()  # Hata detaylarını yazdır
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


def move_motor_to_angle(target_angle_deg, invert_direction):
    global current_motor_angle_global
    if not MOTOR_BAGLI or DEG_PER_STEP <= 0: return
    angle_diff = target_angle_deg - current_motor_angle_global
    if abs(angle_diff) < DEG_PER_STEP: return
    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    logical_dir = (angle_diff > 0)
    physical_dir = not logical_dir if invert_direction else logical_dir
    _step_motor_4in(num_steps, physical_dir)
    current_motor_angle_global = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME)


def create_scan_entry(h_angle, h_step, v_angle, buzzer_dist, invert_dir, steps_rev):
    global current_scan_object_global
    try:
        # Daha önceki RUNNING durumdaki taramaları ERROR olarak güncelle
        Scan.objects.filter(status=Scan.Status.RUNNING).update(status=Scan.Status.ERROR, end_time=timezone.now())
        # Yeni bir tarama girişi oluştur
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
    # Bu fonksiyon, gpiozero Servo nesnesinin beklediği -1.0 ile 1.0 aralığına dönüştürür.
    # Standart servolar genellikle 0-180 derece aralığına sahiptir.
    # Negatif veya 180'den büyük açılar fiziksel olarak desteklenmez, bu yüzden sıkıştırılır.
    return max(-1.0, min(1.0, (angle / 90.0) - 1.0))


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

    atexit.register(release_resources_on_exit)  # Çıkışta kaynakları serbest bırakma fonksiyonunu kaydet
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)  # Kilit al ve donanımı başlat

    TOTAL_H_ANGLE, H_STEP, INVERT_MOTOR, STEPS_PER_REVOLUTION, BUZZER_DISTANCE = args.h_angle, args.h_step, args.invert_motor_direction, args.steps_per_rev, args.buzzer_distance
    DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION  # Adım motoru için derece/adım hesabı

    if not create_scan_entry(TOTAL_H_ANGLE, H_STEP, DEFAULT_VERTICAL_SCAN_ANGLE, BUZZER_DISTANCE, INVERT_MOTOR,
                             STEPS_PER_REVOLUTION): sys.exit(1)  # Veritabanına yeni tarama kaydı oluştur

    try:
        # Adım motoru: Tarama açısının yarısı kadar sağa dön (-X yönü, yani artı açı değeri)
        # Bu, motoru taramanın en sağ başlangıç noktasına getirir.
        initial_turn_angle = (TOTAL_H_ANGLE / 2.0)
        print(f"Başlangıç pozisyonuna gidiliyor: {initial_turn_angle:.1f}°...")
        move_motor_to_angle(initial_turn_angle, INVERT_MOTOR)

        # Servo başlangıç pozisyonu:
        # Servo'yu fiziksel olarak 0 dereceye getiriyoruz.
        # Bu pozisyon, veritabanına ve görselleştirmelere -30 derece olarak kaydedilecek.
        servo.value = degree_to_servo_value(0)  # Fiziksel 0 dereceye git
        time.sleep(1.5)  # Motorların yerine oturması için bekleme süresi

        num_horizontal_steps = int(TOTAL_H_ANGLE / H_STEP)
        # Yatay tarama döngüsü: En sağdan başlayıp sola doğru ilerle
        for i in range(num_horizontal_steps + 1):
            # Adım motoru: Sağa dönüldükten sonra sola doğru taramak için açıyı azaltırız.
            # target_h_angle_abs: mutlak motor açısı (motorun fiziksel pozisyonu)
            # target_h_angle_rel: tarama başlangıcından itibaren geçen relatif açı (0'dan TOTAL_H_ANGLE'a)
            target_h_angle_abs = (TOTAL_H_ANGLE / 2.0) - (i * H_STEP)
            target_h_angle_rel = i * H_STEP
            move_motor_to_angle(target_h_angle_abs, INVERT_MOTOR)  # Adım motorunu hareket ettir
            print(f"\nYatay Açı: {target_h_angle_rel:.1f}°")

            num_vertical_steps = int(DEFAULT_VERTICAL_SCAN_ANGLE / DEFAULT_VERTICAL_STEP_ANGLE)
            # Dikey tarama döngüsü: Servo'nun fiziksel aralığını kullan, ancak mantıksal açıyı kaydet
            for j in range(num_vertical_steps + 1):
                # Servo'ya gönderilecek fiziksel açı (0-180 arasında kalmalı)
                physical_v_angle_to_send = j * DEFAULT_VERTICAL_STEP_ANGLE

                # Raporlama ve koordinat hesaplama için kullanılacak mantıksal açı
                # Bu, fiziksel açıya SERVO_VERTICAL_OFFSET_DEG ofsetini ekleyerek sanal bir aralık oluşturur.
                # Örn: physical_v_angle_to_send=0 iken, logical_v_angle_to_record = 0 + (-30) = -30
                # Örn: physical_v_angle_to_send=180 iken, logical_v_angle_to_record = 180 + (-30) = 150
                logical_v_angle_to_record = physical_v_angle_to_send + SERVO_VERTICAL_OFFSET_DEG

                servo.value = degree_to_servo_value(physical_v_angle_to_send)  # Servo'ya fiziksel açıyı gönder
                time.sleep(LOOP_TARGET_INTERVAL_S)  # Ölçüm için bekle
                dist_cm = sensor.distance * 100  # Mesafe ölçümü (cm cinsinden)
                print(f"  -> Dikey: {logical_v_angle_to_record:.1f}°, Mesafe: {dist_cm:.1f} cm")

                if lcd:
                    try:
                        # LCD'de mantıksal açıyı göster
                        lcd.cursor_pos = (0, 0);
                        lcd.write_string(f"Y:{target_h_angle_rel:<4.0f} V:{logical_v_angle_to_record:<4.0f}  ")
                        lcd.cursor_pos = (1, 0);
                        lcd.write_string(f"Mesafe: {dist_cm:<5.1f}cm ")
                    except OSError as e:
                        print(f"LCD YAZMA HATASI: {e}")

                # Mesafe kritikse (belirli bir mesafeden küçükse) buzzer'ı aç/kapat
                if buzzer.is_active != (0 < dist_cm < BUZZER_DISTANCE): buzzer.toggle()

                # Koordinat hesaplamaları ve veritabanına kaydetme için mantıksal açıları kullan
                # Not: target_h_angle_abs (motorun mutlak pozisyonu) yatay koordinat için kullanılır.
                # logical_v_angle_to_record (ofsetlenmiş dikey açı) dikey koordinat için kullanılır.
                angle_pan_rad, angle_tilt_rad = math.radians(target_h_angle_abs), math.radians(
                    logical_v_angle_to_record)
                h_radius = dist_cm * math.cos(angle_tilt_rad)
                # X, Y, Z koordinatlarını hesapla
                z, x, y = dist_cm * math.sin(angle_tilt_rad), h_radius * math.cos(angle_pan_rad), h_radius * math.sin(
                    angle_pan_rad)
                # ScanPoint veritabanı kaydı
                ScanPoint.objects.create(scan=current_scan_object_global, derece=target_h_angle_rel,
                                         dikey_aci=logical_v_angle_to_record, mesafe_cm=dist_cm, x_cm=x, y_cm=y, z_cm=z,
                                         timestamp=timezone.now())

        script_exit_status_global = Scan.Status.COMPLETED  # Tarama başarılı tamamlandı
    except KeyboardInterrupt:
        script_exit_status_global = Scan.Status.INTERRUPTED  # Kullanıcı tarafından durduruldu
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        script_exit_status_global = Scan.Status.ERROR  # Genel bir hata oluştu
        print(f"KRİTİK HATA: {e}");
        traceback.print_exc()  # Hata detaylarını yazdır
    finally:
        print("İşlem sonlanıyor. Motor merkez konuma getiriliyor...")
        move_motor_to_angle(0, INVERT_MOTOR)  # Adım motorunu merkeze getir (0 derece)
        if servo: servo.value = degree_to_servo_value(90)  # Servo motoru merkeze getir (fiziksel 90 derece)
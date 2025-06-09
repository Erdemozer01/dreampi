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
    from gpiozero import DistanceSensor, LED, Buzzer, OutputDevice, Servo, PWMOutputDevice
    from RPLCD.i2c import CharLCD
    from gpiozero.pins.pigpio import PiGPIOFactory
    from gpiozero import Device

    print("SensorScript: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    print(f"SensorScript: Gerekli donanım kütüphanesi bulunamadı: {e}")
    sys.exit(1)

# --- PIGPIO KURULUMU (DAHA İYİ PERFORMANS İÇİN) ---
try:
    Device.pin_factory = PiGPIOFactory()
    print("SensorScript: pigpio pin factory başarıyla ayarlandı.")
except (IOError, OSError):
    print("UYARI: pigpio daemon'a bağlanılamadı. Servo ve PWM daha az kararlı çalışabilir.")
    print("Çözüm için terminale 'sudo systemctl start pigpiod' yazmayı deneyin.")
    pass

# --- SABİTLER VE PINLER ---
MOTOR_TYPE_DC = True
MOTOR_BAGLI = True

# DC Motor A için pinler (Örnek pinler, projenize göre ayarlayın)
IN1_DC_MOTOR_A = 6
IN2_DC_MOTOR_A = 20 # GPIO 13 yerine 20 kullanıldı
ENA_DC_MOTOR_A = 19 # PWM için uygun bir GPIO pini

# DC Motor B için pinler (L298N'deki IN3, IN4 ve ENB'ye bağlanacak - opsiyonel)
# Eğer ikinci bir DC motor kullanılacaksa bu pinleri tanımlayın.
IN3_DC_MOTOR_B = 26
IN4_DC_MOTOR_B = 21
ENB_DC_MOTOR_B = 16

TRIG_PIN, ECHO_PIN = 23, 24
SERVO_PIN = 12
BUZZER_PIN = 17
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

LED_PIN = 27 # Yeni eklenen LED pini

LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/sensor_scan_script.lock', '/tmp/sensor_scan_script.pid'

# Varsayılan Değerler
DEFAULT_HORIZONTAL_SCAN_ANGLE = 270.0
DEFAULT_HORIZONTAL_STEP_ANGLE = 10.0
DEFAULT_VERTICAL_SCAN_ANGLE = 180.0
DEFAULT_VERTICAL_STEP_ANGLE = 15.0
DEFAULT_BUZZER_DISTANCE = 10

DC_MOTOR_SPEED_PWM_DUTY_CYCLE = 0.6
DC_MOTOR_MOVE_DURATION = 0.5
LOOP_TARGET_INTERVAL_S = 0.2

# Servo'nun başlangıç açısını kaydırmak için yeni sabit
# Bu değer, servo'nun fiziksel 0 derecesine karşılık gelen mantıksal açıyı belirtir.
# Eğer bu kodda kullanılmıyorsa ve görselleştirmede ofset bekleniyorsa, Dash tarafında yönetilmelidir.
# SERVO_VERTICAL_OFFSET_DEG = -30.0 # Eğer kullanılacaksa aktif edin

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, current_scan_object_global = None, None
sensor, servo, buzzer, lcd, led = None, None, None, None, None # led eklendi
# Motor A değişkenleri
in1_dev_A, in2_dev_A, ena_dev_A = None, None, None
# Motor B değişkenleri (opsiyonel)
in3_dev_B, in4_dev_B, enb_dev_B = None, None, None

script_exit_status_global = Scan.Status.ERROR
current_motor_angle_global = 0.0 # DC motorlar için tahmini yatay açı takibi


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

def _stop_all_dc_motors():
    """Tüm DC motorları durdurur."""
    if 'ena_dev_A' in globals() and ena_dev_A: ena_dev_A.off()
    if 'in1_dev_A' in globals() and in1_dev_A: in1_dev_A.off()
    if 'in2_dev_A' in globals() and in2_dev_A: in2_dev_A.off()

    # Eğer Motor B kullanılıyorsa
    if 'enb_dev_B' in globals() and enb_dev_B: enb_dev_B.off()
    if 'in3_dev_B' in globals() and in3_dev_B: in3_dev_B.off()
    if 'in4_dev_B' in globals() and in4_dev_B: in4_dev_B.off()

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

    _stop_all_dc_motors() # Tüm DC motorları durdur
    if buzzer and buzzer.is_active: buzzer.off()
    if lcd:
        try:
            lcd.clear()
        except Exception as e:
            print(f"LCD temizlenemedi: {e}")
    if led and led.is_active: led.off() # LED'i kapatma eklendi

    for dev in [sensor, servo, buzzer, lcd, led, in1_dev_A, in2_dev_A, ena_dev_A, # Diğer motor pinleri de eklenebilir
                getattr(sys.modules[__name__], 'in3_dev_B', None), # Eğer varlarsa
                getattr(sys.modules[__name__], 'in4_dev_B', None),
                getattr(sys.modules[__name__], 'enb_dev_B', None)]:
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
    global sensor, servo, buzzer, lcd, led # led değişkeni eklendi
    # Motor A değişkenleri
    global in1_dev_A, in2_dev_A, ena_dev_A
    # Motor B değişkenleri (opsiyonel)
    global in3_dev_B, in4_dev_B, enb_dev_B

    try:
        if MOTOR_BAGLI and MOTOR_TYPE_DC:
            # DC Motor A için pinler
            in1_dev_A = OutputDevice(IN1_DC_MOTOR_A)
            in2_dev_A = OutputDevice(IN2_DC_MOTOR_A)
            ena_dev_A = PWMOutputDevice(ENA_DC_MOTOR_A)

            # DC Motor B için pinler (Eğer kullanılacaksa yorum satırını kaldırın)
            # in3_dev_B = OutputDevice(IN3_DC_MOTOR_B)
            # in4_dev_B = OutputDevice(IN4_DC_MOTOR_B)
            # enb_dev_B = PWMOutputDevice(ENB_DC_MOTOR_B)

        # Ultrasonik mesafe sensörü
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)

        # Servo motor: Darbe genişlikleri ile başlatılıyor
        MIN_PULSE = 0.0005
        MAX_PULSE = 0.0025
        servo = Servo(SERVO_PIN, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE)

        # Buzzer
        buzzer = Buzzer(BUZZER_PIN)

        # LED başlatma
        led = LED(LED_PIN) # LED objesi oluşturuldu

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


def _move_dc_motor(motor_id, duration, direction_positive, speed_pwm_duty_cycle):
    """
    Belirli bir DC motoru belirli bir yönde belirli bir süre döndürür.
    :param motor_id: 'A' veya 'B' motorunu seçmek için.
    :param duration: Motorun döneceği süre (saniye).
    :param direction_positive: True ise bir yöne, False ise ters yöne döner.
    :param speed_pwm_duty_cycle: Motor hızı (0.0 - 1.0 arası PWM değeri).
    """
    in_pin1, in_pin2, ena_pin = None, None, None

    if motor_id == 'A' and 'in1_dev_A' in globals() and in1_dev_A:
        in_pin1, in_pin2, ena_pin = in1_dev_A, in2_dev_A, ena_dev_A
    elif motor_id == 'B' and 'in3_dev_B' in globals() and in3_dev_B:
        in_pin1, in_pin2, ena_pin = in3_dev_B, in4_dev_B, enb_dev_B
    else:
        print(f"Hata: Motor ID '{motor_id}' için pinler başlatılmamış veya geçersiz.")
        return

    if not (in_pin1 and in_pin2 and ena_pin): return

    # Yön pinlerini ayarla
    if direction_positive:
        in_pin1.on()
        in_pin2.off()
    else:
        in_pin1.off()
        in_pin2.on()

    # Motoru belirtilen hızda etkinleştir
    ena_pin.value = speed_pwm_duty_cycle

    time.sleep(duration) # Motoru belirtilen süre döndür

    # Motoru durdur
    in_pin1.off()
    in_pin2.off()
    ena_pin.off()
    time.sleep(0.05) # Motorun tamamen durması için kısa bir bekleme


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
    return max(-1.0, min(1.0, (angle / 90.0) - 1.0))


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gelişmiş 3D Haritalama Scripti")
    parser.add_argument("--h-angle", type=float, default=DEFAULT_HORIZONTAL_SCAN_ANGLE)
    parser.add_argument("--h-step", type=float, default=DEFAULT_HORIZONTAL_STEP_ANGLE)
    parser.add_argument("--buzzer-distance", type=int, default=DEFAULT_BUZZER_DISTANCE)
    # DC motorlarda 'invert-motor-direction' ve 'steps-per-rev' doğrudan kullanılmaz.
    # parser.add_argument("--invert-motor-direction", type=lambda x: str(x).lower() == 'true', default=False)
    # parser.add_argument("--steps-per-rev", type=int, default=0) # değeri 0 olarak ayarla

    args = parser.parse_args()

    atexit.register(release_resources_on_exit)  # Çıkışta kaynakları serbest bırakma fonksiyonunu kaydet
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)  # Kilit al ve donanımı başlat

    TOTAL_H_ANGLE, H_STEP, BUZZER_DISTANCE = args.h_angle, args.h_step, args.buzzer_distance
    # create_scan_entry çağrısında invert_dir ve steps_rev için varsayılan değerler kullanıldı
    if not create_scan_entry(TOTAL_H_ANGLE, H_STEP, DEFAULT_VERTICAL_SCAN_ANGLE, BUZZER_DISTANCE, False, 0): sys.exit(1)

    try:
        print("Motor başlangıç pozisyonuna ayarlanıyor (manuel veya sensör ile ayarlamanız gerekebilir)...")

        # Servo başlangıç pozisyonu: Fiziksel 0 dereceye getir
        servo.value = degree_to_servo_value(0)
        time.sleep(1.5) # Motorların yerine oturması için bekleme süresi

        num_horizontal_steps = int(TOTAL_H_ANGLE / H_STEP)
        # current_motor_angle_global: Mantıksal olarak 0'dan başlayıp tarama açısına doğru ilerleyen yatay açı.
        # Bu, DC motorun gerçek fiziksel açısını takip etmez, sadece tarama mantığını sürdürür.
        current_motor_angle_global = 0.0

        # Yatay tarama döngüsü: Her adımda DC motoru döndür
        for i in range(num_horizontal_steps + 1):
            target_h_angle_rel = i * H_STEP # Göreceli tarama açısı (0'dan itibaren)

            # DC motoru H_STEP açısı kadar döndürmek için (tahmini)
            _move_dc_motor('A', DC_MOTOR_MOVE_DURATION, True, DC_MOTOR_SPEED_PWM_DUTY_CYCLE)
            current_motor_angle_global = target_h_angle_rel # Göreceli açıyı doğrudan ata

            print(f"\nYatay Açı: {target_h_angle_rel:.1f}°")

            num_vertical_steps = int(DEFAULT_VERTICAL_SCAN_ANGLE / DEFAULT_VERTICAL_STEP_ANGLE)
            for j in range(num_vertical_steps + 1):
                target_v_angle = j * DEFAULT_VERTICAL_STEP_ANGLE # Servo'ya gönderilecek fiziksel açı

                servo.value = degree_to_servo_value(target_v_angle)
                time.sleep(LOOP_TARGET_INTERVAL_S) # Ölçüm için bekleme

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

                # *** LED KONTROL MANTIĞI BAŞLANGICI ***
                if led: # Eğer LED objesi başarılı bir şekilde oluşturulduysa
                    if 0 < dist_cm < BUZZER_DISTANCE: # Eğer mesafe yakınsa (buzzer mesafesinden küçükse)
                        if not led.is_active: # Zaten yanmıyorsa yak
                            led.on()
                    else: # Mesafe uzaksa veya okuma yoksa
                        if led.is_active: # Zaten yanıyorsa söndür
                            led.off()

                        # Normal tarama durumunda kısa yanıp sönme
                        led.on()
                        time.sleep(0.05) # Kısa bir yanıp sönme
                        led.off()
                # *** LED KONTROL MANTIĞI SONU ***


                # Koordinat hesaplamaları: Burada current_motor_angle_global (tahmini mutlak yatay açı)
                # ve target_v_angle (dikey açı) kullanılacak.
                angle_pan_rad, angle_tilt_rad = math.radians(current_motor_angle_global), math.radians(target_v_angle)
                h_radius = dist_cm * math.cos(angle_tilt_rad)
                z, x, y = dist_cm * math.sin(angle_tilt_rad), h_radius * math.cos(angle_pan_rad), h_radius * math.sin(
                    angle_pan_rad)

                ScanPoint.objects.create(scan=current_scan_object_global, derece=target_h_angle_rel,
                                         dikey_aci=target_v_angle, mesafe_cm=dist_cm, x_cm=x, y_cm=y, z_cm=z,
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
        print("İşlem sonlanıyor. Motorlar durduruluyor ve servo merkeze getiriliyor...")
        _stop_all_dc_motors() # Tüm DC motorları durdur
        if servo: servo.value = degree_to_servo_value(90) # Servo motoru merkeze getir (fiziksel 90 derece)
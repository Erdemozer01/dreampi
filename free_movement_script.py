import os
import sys
import time
import fcntl
import atexit
import math
import traceback

# --- DONANIM KÜTÜPHANELERİ ---
try:
    from gpiozero import DistanceSensor, Buzzer, OutputDevice, LED
    from RPLCD.i2c import CharLCD

    print("FreeMovementScript: Donanım kütüphaneleri başarıyla import edildi.")
except ImportError as e:
    print(f"FreeMovementScript: Gerekli kütüphane bulunamadı: {e}")
    sys.exit(1)

# --- SABİTLER VE PINLER ---
TRIG_PIN, ECHO_PIN = 23, 24
IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
BUZZER_PIN = 17
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1

LOCK_FILE_PATH = '/tmp/free_movement_script.lock'
PID_FILE_PATH = '/tmp/free_movement_script.pid'

# Çalışma Parametreleri
SWEEP_ANGLE = 60.0
DETECTION_THRESHOLD_CM = 30.0
PAUSE_ON_DETECTION_S = 3.0
STEPS_PER_REVOLUTION = 4096
# DÜZELTME: Motoru belirgin şekilde hızlandırmak için adımlar arası bekleme süresi düşürüldü.
# Bu değeri daha da düşürmek hızı artırır ancak motorun adım atlamasına neden olabilir.
STEP_MOTOR_INTER_STEP_DELAY = 0.001

# --- GLOBAL DEĞİŞKENLER ---
lock_file_handle, sensor, buzzer, lcd = None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION
current_motor_angle_global, current_step_sequence_index = 0.0, 0
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]
motor_paused, pause_end_time = False, 0


# --- SÜREÇ YÖNETİMİ VE KAYNAK KONTROLÜ ---
def acquire_lock_and_pid():
    global lock_file_handle
    try:
        lock_file_handle = open(LOCK_FILE_PATH, 'w')
        fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(PID_FILE_PATH, 'w') as pf:
            pf.write(str(os.getpid()))
        print(f"Gözcü Modu: PID ({os.getpid()}) ve Kilit dosyaları oluşturuldu.")
        return True
    except IOError:
        print("Gözcü Modu: Kilit dosyası oluşturulamadı. Başka bir script çalışıyor olabilir.")
        return False


def release_resources_on_exit():
    print("\nProgram sonlandırılıyor, kaynaklar serbest bırakılıyor...")
    _set_step_pins(0, 0, 0, 0)
    if lcd:
        try:
            lcd.clear();
            lcd.write_string("Gorusuruz!")
        except Exception as e:
            print(f"LCD temizlenemedi: {e}")
    if buzzer: buzzer.off()
    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN); lock_file_handle.close()
        except:
            pass
    for fp in [PID_FILE_PATH, LOCK_FILE_PATH]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except:
                pass
    print("Temizleme tamamlandı.")


# --- DONANIM FONKSİYONLARI ---
def init_hardware():
    global sensor, buzzer, lcd, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(IN2_GPIO_PIN), OutputDevice(
            IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)
        buzzer = Buzzer(BUZZER_PIN)
        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS, auto_linebreaks=True)
            lcd.clear()
        except Exception as e:
            print(f"UYARI: LCD başlatılamadı, LCD olmadan devam edilecek. Hata: {e}")
            lcd = None
        return True
    except Exception as e:
        print(f"KRİTİK HATA: Donanım başlatılamadı: {e}");
        return False


def _set_step_pins(s1, s2, s3, s4):
    if in1_dev: in1_dev.value = bool(s1)
    if in2_dev: in2_dev.value = bool(s2)
    if in3_dev: in3_dev.value = bool(s3)
    if in4_dev: in4_dev.value = bool(s4)


def _single_step_motor(direction_positive):
    global current_step_sequence_index, current_motor_angle_global
    step_increment = 1 if direction_positive else -1
    current_step_sequence_index = (current_step_sequence_index + step_increment) % len(step_sequence)
    _set_step_pins(*step_sequence[current_step_sequence_index])
    current_motor_angle_global += (DEG_PER_STEP * step_increment)
    time.sleep(STEP_MOTOR_INTER_STEP_DELAY)


# --- ANA GÖZCÜ MANTIĞI ---
def check_environment_and_react():
    global motor_paused, pause_end_time
    mesafe = sensor.distance * 100
    if 0 < mesafe < DETECTION_THRESHOLD_CM:
        if not motor_paused:
            print(f"!!! NESNE ALGILANDI: {mesafe:.1f} cm !!!")
            if lcd:
                try:
                    lcd.clear();
                    lcd.write_string("NESNE ALGILANDI");
                    lcd.cursor_pos = (1, 0);
                    lcd.write_string(f"{mesafe:.1f} cm".center(LCD_COLS))
                except OSError as e:
                    print(f"LCD YAZMA HATASI: {e}")
            buzzer.beep(on_time=0.1, off_time=0.1, n=2, background=True)
            motor_paused = True
            pause_end_time = time.time() + PAUSE_ON_DETECTION_S
    else:
        if motor_paused and time.time() > pause_end_time:
            print("...Alan temiz, taramaya devam ediliyor.")
            motor_paused = False
        if not motor_paused and lcd:
            try:
                lcd.clear();
                lcd.write_string("Gozcu Modu Aktif");
                lcd.cursor_pos = (1, 0);
                lcd.write_string(f"Aci: {current_motor_angle_global:.1f}*".center(LCD_COLS))
            except OSError as e:
                print(f"LCD YAZMA HATASI: {e}")


def move_to_target_with_scan(target_angle):
    """Motoru hedefe götürürken her adımda ortamı kontrol eder."""
    global current_motor_angle_global
    print(f"\n>> Yeni Hedef: {target_angle:.1f} derece. Harekete başlanıyor...")

    direction_is_positive = target_angle > current_motor_angle_global

    while True:
        check_environment_and_react()

        if motor_paused:
            time.sleep(0.1)
            continue

        if direction_is_positive:
            if current_motor_angle_global >= target_angle:
                break
        else:
            if current_motor_angle_global <= target_angle:
                break

        _single_step_motor(direction_is_positive)

    print(f"   Hedefe ulaşıldı. Son Açı: {current_motor_angle_global:.1f}°")
    current_motor_angle_global = target_angle
    check_environment_and_react()
    time.sleep(1)


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)

    print("\n>>> Serbest Hareket (Gözcü) Modu Başlatıldı <<<")

    try:
        while True:
            move_to_target_with_scan(SWEEP_ANGLE)
            move_to_target_with_scan(-SWEEP_ANGLE)
            move_to_target_with_scan(0)
            print("\n>>> Bir tam tur tamamlandı. Yeni tura başlanıyor...")
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"KRİTİK HATA: {e}");
        traceback.print_exc()


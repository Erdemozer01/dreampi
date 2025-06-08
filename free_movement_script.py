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
STATUS_LED_PIN = 27
LCD_I2C_ADDRESS = 0x27
LCD_PORT_EXPANDER = 'PCF8574'
LCD_COLS = 16
LCD_ROWS = 2
I2C_PORT = 1

LOCK_FILE_PATH = '/tmp/free_movement_script.lock'
PID_FILE_PATH = '/tmp/free_movement_script.pid'

# --- ÇALIŞMA PARAMETRELERİ ---
STEPS_PER_REVOLUTION = 4096
# DÜZELTME: Motorun adım atlamasını önlemek ve kararlı çalışmasını sağlamak için
# hız biraz düşürüldü. Bu değer motorunuzun gücüne göre ayarlanabilir.
STEP_MOTOR_INTER_STEP_DELAY = 0.002

SWEEP_TARGET_ANGLE = 45.0
ALGILAMA_ESIGI_CM = 20.0
MOTOR_PAUSE_ON_DETECTION_S = 3.0
CYCLE_END_PAUSE_S = 2.0

# --- GLOBAL DEĞİŞKENLER ---
sensor, buzzer, lcd, status_led = None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
lock_file_handle = None
current_motor_angle_global = 0.0
current_step_sequence_index = 0
DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]
motor_paused = False
pause_end_time = 0


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
            lcd.clear(); lcd.write_string("Gorusuruz!")
        except:
            pass
    if status_led: status_led.off()
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
    print("✓ Temizleme tamamlandı.")


# --- DONANIM VE HAREKET FONKSİYONLARI ---
def init_hardware():
    global sensor, buzzer, lcd, status_led, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(IN2_GPIO_PIN), OutputDevice(
            IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=2.5)
        buzzer = Buzzer(BUZZER_PIN)
        status_led = LED(STATUS_LED_PIN)
        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS)
            lcd.clear()
        except Exception as e:
            print(f"UYARI: LCD başlatılamadı: {e}"); lcd = None
        print("✓ Donanımlar başarıyla başlatıldı.")
        return True
    except Exception as e:
        print(f"HATA: Donanım başlatılamadı! Detay: {e}");
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
    if 0 < mesafe < ALGILAMA_ESIGI_CM:
        if not motor_paused:
            print(f"   >>> UYARI: Nesne {mesafe:.1f} cm! <<<")
            buzzer.beep(on_time=0.1, off_time=0.1, n=2, background=True)
            if lcd:
                try:
                    lcd.clear(); lcd.write_string("NESNE ALGILANDI"); lcd.cursor_pos = (1, 0); lcd.write_string(
                        f"{mesafe:.1f} cm".center(LCD_COLS))
                except:
                    pass
            motor_paused = True
            pause_end_time = time.time() + MOTOR_PAUSE_ON_DETECTION_S
    else:
        if motor_paused and time.time() > pause_end_time:
            print("   <<< UYARI SONA ERDİ. >>>")
            motor_paused = False


def update_display():
    if lcd and not motor_paused:
        try:
            lcd.clear()
            lcd.write_string("Gozcu Modu Aktif")
            lcd.cursor_pos = (1, 0)
            lcd.write_string(f"Aci: {current_motor_angle_global:.1f}*".center(LCD_COLS))
        except:
            pass


# --- ANA ÇALIŞMA BLOĞU (YENİDEN DÜZENLENDİ) ---
def move_to_target(target_angle):
    """Motoru hedefe götürürken her adımda ortamı kontrol eder."""
    global current_motor_angle_global
    print(f"\n>> Yeni Hedef: {target_angle:.1f} derece...")

    direction_is_positive = target_angle > current_motor_angle_global

    # Hedefe ulaşana veya yönü geçene kadar devam et
    while True:
        if direction_is_positive and current_motor_angle_global >= target_angle: break
        if not direction_is_positive and current_motor_angle_global <= target_angle: break

        check_environment_and_react()

        # Duraklatıldıysa, bekleme döngüsüne gir
        if motor_paused:
            status_led.on()  # Duraklatıldığını belirtmek için LED'i yak
            time.sleep(0.1)
            continue

        status_led.off()  # Hareket ederken LED'i söndür
        _single_step_motor(direction_is_positive)
        update_display()

    current_motor_angle_global = target_angle  # Açısal hataları düzelt
    print(f"   Hedefe ulaşıldı. Mevcut Açı: {current_motor_angle_global:.1f}°")
    time.sleep(0.5)


if __name__ == "__main__":
    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)

    print("\n>>> Serbest Hareket (Gözcü) Modu Başlatıldı <<<")

    try:
        move_to_target(0)  # Başlangıçta merkeze git
        while True:
            move_to_target(SWEEP_TARGET_ANGLE)
            move_to_target(-SWEEP_TARGET_ANGLE)
            move_to_target(0)
            print(f"\n>>> Tur tamamlandı. {CYCLE_END_PAUSE_S} saniye bekleniyor...")
            time.sleep(CYCLE_END_PAUSE_S)
    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"KRİTİK HATA: {e}");
        traceback.print_exc()


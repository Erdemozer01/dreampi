import os, sys, time, fcntl, atexit, math, traceback

try:
    from gpiozero import DistanceSensor, Buzzer, OutputDevice, LED
    from RPLCD.i2c import CharLCD
except ImportError as e:
    print(f"Hata: Gerekli kütüphane bulunamadı: {e}"); sys.exit(1)

# --- Sabitler ve Pinler ---
TRIG_PIN, ECHO_PIN = 23, 24
IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
BUZZER_PIN = 17
LCD_I2C_ADDRESS, LCD_PORT_EXPANDER, LCD_COLS, LCD_ROWS, I2C_PORT = 0x27, 'PCF8574', 16, 2, 1
LOCK_FILE_PATH, PID_FILE_PATH = '/tmp/free_movement_script.lock', '/tmp/free_movement_script.pid'

# Çalışma Parametreleri
SWEEP_ANGLE = 90.0
DETECTION_THRESHOLD_CM = 30.0
PAUSE_ON_DETECTION_S = 3.0
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0020

# --- Global Değişkenler ve Fonksiyonlar ---
lock_file_handle, sensor, buzzer, lcd = None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None
DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION
current_motor_angle_global, current_step_sequence_index = 0.0, 0
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1],
                 [1, 0, 0, 1]]
motor_paused, pause_end_time = False, 0


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
        return False


def release_resources_on_exit():
    print("\nGözcü modu sonlanıyor...")
    _set_step_pins(0, 0, 0, 0)
    if lcd:
        try:
            lcd.clear(); lcd.write_string("Gorusuruz!")
        except:
            pass
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


def init_hardware():
    global sensor, buzzer, lcd, in1_dev, in2_dev, in3_dev, in4_dev
    try:
        in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(IN2_GPIO_PIN), OutputDevice(
            IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)
        buzzer = Buzzer(BUZZER_PIN)
        lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                      rows=LCD_ROWS, auto_linebreaks=True)
        lcd.clear();
        lcd.write_string("Gozcu Modu Aktif")
        return True
    except Exception as e:
        print(f"Donanım Hatası: {e}"); return False


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


def check_environment_and_react():
    global motor_paused, pause_end_time
    mesafe = sensor.distance * 100
    if 0 < mesafe < DETECTION_THRESHOLD_CM:
        if not motor_paused:
            print(f"!!! NESNE ALGILANDI: {mesafe:.1f} cm !!!")
            if lcd: lcd.clear(); lcd.write_string("NESNE ALGILANDI"); lcd.cursor_pos = (1, 0); lcd.write_string(
                f"{mesafe:.1f} cm".center(16))
            buzzer.beep(on_time=0.1, off_time=0.1, n=2, background=True)
            motor_paused = True
            pause_end_time = time.time() + PAUSE_ON_DETECTION_S
    else:
        if motor_paused and time.time() > pause_end_time:
            print("...Alan temiz, taramaya devam.")
            motor_paused = False
        if not motor_paused and lcd:
            lcd.clear();
            lcd.write_string("Gozcu Modu Aktif");
            lcd.cursor_pos = (1, 0);
            lcd.write_string(f"Aci: {current_motor_angle_global:.1f}*".center(16))


# --- ANA ÇALIŞMA BLOĞU ---
if __name__ == "__main__":
    atexit.register(release_resources_on_exit)
    if not acquire_lock_and_pid() or not init_hardware(): sys.exit(1)

    target_angle = SWEEP_ANGLE
    try:
        while True:
            while abs(current_motor_angle_global - target_angle) > DEG_PER_STEP:
                check_environment_and_react()
                if motor_paused: time.sleep(0.1); continue
                _single_step_motor(target_angle > current_motor_angle_global)

            check_environment_and_react();
            time.sleep(1)
            target_angle = -target_angle
    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"KRİTİK HATA: {e}"); traceback.print_exc()


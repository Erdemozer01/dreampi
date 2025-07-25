import time, os
import atexit
import sys
import random # DÜZELTME: Rastgele seçim için import edildi

# PID dosyası yönetimi için sabitler (dashboard ile aynı olmalı)
SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'
SENSOR_SCRIPT_LOCK_FILE = '/tmp/sensor_scan_script.lock'

# --- PID ve Lock Dosyası Yönetimi ---
def create_pid_file():
    if os.path.exists(SENSOR_SCRIPT_LOCK_FILE):
        print("HATA: Kilit dosyası zaten var. Başka bir işlem çalışıyor olabilir.")
        sys.exit(1)
    try:
        pid = os.getpid()
        with open(SENSOR_SCRIPT_PID_FILE, 'w') as f:
            f.write(str(pid))
        # Lock dosyasını PID dosyası başarıyla oluşturulduktan sonra yarat
        open(SENSOR_SCRIPT_LOCK_FILE, 'w').close()
        print(f"PID dosyası ({SENSOR_SCRIPT_PID_FILE}) ve kilit dosyası oluşturuldu. PID: {pid}")
    except IOError as e:
        print(f"HATA: PID dosyası oluşturulamadı: {e}")
        sys.exit(1)

def remove_pid_and_lock_files():
    print("PID ve kilit dosyaları temizleniyor...")
    for f in [SENSOR_SCRIPT_PID_FILE, SENSOR_SCRIPT_LOCK_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
# Gerekli GPIO kütüphanelerini import et
try:
    from gpiozero import DistanceSensor, Buzzer, OutputDevice, LED
    from RPLCD.i2c import CharLCD
except ImportError:
    print("HATA: Gerekli kütüphaneler (gpiozero, RPLCD) bulunamadı. Lütfen yükleyin.")
    sys.exit(1)

# ==============================================================================
# --- Pin Tanımlamaları ve Donanım Ayarları ---
# ==============================================================================
TRIG_PIN, ECHO_PIN = 23, 24
IN1_GPIO_PIN, IN2_GPIO_PIN, IN3_GPIO_PIN, IN4_GPIO_PIN = 6, 13, 19, 26
BUZZER_PIN = 25
STATUS_LED_PIN = 27
LCD_I2C_ADDRESS = 0x27
LCD_PORT_EXPANDER = 'PCF8574'
LCD_COLS = 16
LCD_ROWS = 2
I2C_PORT = 1
# ==============================================================================

# ==============================================================================
# --- Parametreler ---
# ==============================================================================
STEPS_PER_REVOLUTION = 4096
STEP_MOTOR_INTER_STEP_DELAY = 0.0015
STEP_MOTOR_SETTLE_TIME = 0.05

SWEEP_TARGET_ANGLE = 60
ALGILAMA_ESIGI_CM = 20
MOTOR_PAUSE_ON_DETECTION_S = 3.0
CYCLE_END_PAUSE_S = 5.0

BUZZER_BIP_SURESI = 0.03
LED_BLINK_ON_SURESI = 0.5
LED_BLINK_OFF_SURESI = 0.5
LCD_TIME_UPDATE_INTERVAL = 1.0
# ==============================================================================

# --- Global Değişkenler ---
# ==============================================================================
sensor, buzzer, lcd, status_led = None, None, None, None
in1_dev, in2_dev, in3_dev, in4_dev = None, None, None, None

current_motor_angle_global = 0.0
current_step_sequence_index = 0
DEG_PER_STEP = 360.0 / STEPS_PER_REVOLUTION
step_sequence = [[1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
                 [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]

current_lcd_message_type = None
last_lcd_time_update = 0
led_is_blinking = False
init_hardware_called_successfully = False
object_alert_active = False

motor_movement_paused = False
motor_pause_end_time = 0

# DÜZELTME: Rastgele selamlama mesajları için bir liste oluşturuldu.
# Her bir eleman, LCD'nin iki satırını temsil eden bir demettir (tuple).
GREETING_MESSAGES = [
    ("Selam!", "Birini gordum :)"),
    ("Hey!", "Orada biri var!"),
    ("Dikkat!", "Engel algilandi."),
    ("Merhaba", "Dream Pi devriyede"),
    ("Merhaba", "Ben Dream Pi"),
    ("Hey", "Dokunma Bana :)"),
    ("Demek", "Buradasin. Yakaladim !!!"),
    ("Ooo, bir misafir", "Hos geldiniz!")
]

# ==============================================================================
# --- Donanım ve Yardımcı Fonksiyonlar ---
# ==============================================================================
def init_hardware():
    global sensor, buzzer, lcd, status_led, in1_dev, in2_dev, in3_dev, in4_dev, led_is_blinking, init_hardware_called_successfully
    print("Donanımlar başlatılıyor...")
    try:
        in1_dev, in2_dev, in3_dev, in4_dev = OutputDevice(IN1_GPIO_PIN), OutputDevice(IN2_GPIO_PIN), OutputDevice(
            IN3_GPIO_PIN), OutputDevice(IN4_GPIO_PIN)
        sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=2.5, queue_len=5)
        buzzer = Buzzer(BUZZER_PIN);
        buzzer.off()
        status_led = LED(STATUS_LED_PIN)
        if not led_is_blinking:
            status_led.blink(on_time=LED_BLINK_ON_SURESI, off_time=LED_BLINK_OFF_SURESI, background=True)
            led_is_blinking = True

        try:
            lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER, address=LCD_I2C_ADDRESS, port=I2C_PORT, cols=LCD_COLS,
                          rows=LCD_ROWS, auto_linebreaks=False)
            lcd.clear()
            print("✓ LCD başarıyla başlatıldı.")
        except Exception as e_lcd:
            print(f"UYARI: LCD başlatılamadı! Hata: {e_lcd}")
            lcd = None
        print("✓ Donanımlar başarıyla başlatıldı.")
        init_hardware_called_successfully = True
        return True
    except Exception as e:
        print(f"HATA: Donanım başlatılamadı! Detay: {e}")
        init_hardware_called_successfully = False
        return False


def release_resources_on_exit():
    print("\nProgram sonlandırılıyor, kaynaklar serbest bırakılıyor...")
    _set_step_pins(0, 0, 0, 0)
    if lcd:
        try:
            lcd.clear()
        except:
            pass
    if status_led:
        try:
            status_led.off()
        except:
            pass
    for dev in [sensor, buzzer, lcd, status_led, in1_dev, in2_dev, in3_dev, in4_dev]:
        if dev and hasattr(dev, 'close'):
            try:
                dev.close()
            except Exception:
                pass
    print("✓ Temizleme tamamlandı.")


def _set_step_pins(s1, s2, s3, s4):
    if in1_dev: in1_dev.value = bool(s1)
    if in2_dev: in2_dev.value = bool(s2)
    if in3_dev: in3_dev.value = bool(s3)
    if in4_dev: in4_dev.value = bool(s4)

def _stop_step_motor():
    """Step motor pinlerini tamamen kapatır"""
    _set_step_pins(0, 0, 0, 0)

def _single_step_motor(direction_positive):
    global current_step_sequence_index, current_motor_angle_global
    current_step_sequence_index = (current_step_sequence_index + (1 if direction_positive else -1) + len(
        step_sequence)) % len(step_sequence)
    _set_step_pins(*step_sequence[current_step_sequence_index])
    current_motor_angle_global += (DEG_PER_STEP * (1 if direction_positive else -1))
    time.sleep(STEP_MOTOR_INTER_STEP_DELAY)

def move_motor_to_absolute_angle(target_angle_deg, speed_factor=1.0):
    global current_motor_angle_global

    angle_diff_raw = target_angle_deg - current_motor_angle_global
    angle_diff = angle_diff_raw

    if abs(angle_diff_raw) > 180:
        angle_diff = angle_diff_raw - (360 if angle_diff_raw > 0 else -360)

    num_steps = round(abs(angle_diff) / DEG_PER_STEP)
    if num_steps == 0:
        time.sleep(STEP_MOTOR_SETTLE_TIME / speed_factor)
        return

    direction_positive = (angle_diff > 0)

    for _ in range(num_steps):
        _single_step_motor(direction_positive)
        if speed_factor != 1.0:
            time.sleep(STEP_MOTOR_INTER_STEP_DELAY * (1 / speed_factor - 1))

    current_motor_angle_global = target_angle_deg
    time.sleep(STEP_MOTOR_SETTLE_TIME / speed_factor)
    
    # Motor hareketi bitince pinleri temizle
    _stop_step_motor()


def kisa_uyari_bip(bip_suresi):
    if buzzer:
        buzzer.on();
        time.sleep(bip_suresi);
        buzzer.off()


def update_lcd_display(message_type):
    global current_lcd_message_type, lcd, last_lcd_time_update
    now = time.time()
    # Sadece mesaj tipi değiştiyse VEYA normal_time ise ve interval dolduysa yaz
    if message_type == current_lcd_message_type and \
            not (message_type == "normal_time" and (now - last_lcd_time_update >= LCD_TIME_UPDATE_INTERVAL)):
        return

    if not lcd: return
    try:
        # normal_time durumunda ve sadece zaman güncelleniyorsa clear() yapma, sadece alt satırı güncelle (titremeyi azaltır)
        if message_type == "normal_time" and current_lcd_message_type == "normal_time":
            lcd.cursor_pos = (1, 0);
            lcd.write_string(time.strftime("%H:%M:%S").ljust(LCD_COLS))
            last_lcd_time_update = now
        else:  # Durum değişti veya ilk yazım
            lcd.clear()
            if message_type == "alert_greeting":
                line1, line2 = random.choice(GREETING_MESSAGES)
                lcd.write_string(line1.ljust(LCD_COLS))
                lcd.cursor_pos = (1, 0);
                lcd.write_string(line2.ljust(LCD_COLS))
            elif message_type == "normal_time":
                lcd.write_string("Dream Pi")
                lcd.cursor_pos = (1, 0);
                lcd.write_string(time.strftime("%H:%M:%S").ljust(LCD_COLS))
                last_lcd_time_update = now
        current_lcd_message_type = message_type
    except Exception as e:
        print(f"LCD Yazma Hatası: {e}");
        current_lcd_message_type = "error"


def perform_measurement_and_react():
    global object_alert_active, led_is_blinking, motor_movement_paused, motor_pause_end_time

    mesafe = sensor.distance * 100
    is_object_currently_close = (mesafe < ALGILAMA_ESIGI_CM)

    newly_detected_for_pause = False

    if is_object_currently_close:
        if not object_alert_active:
            print(f"   >>> UYARI: Nesne {mesafe:.1f} cm! <<<")
            kisa_uyari_bip(BUZZER_BIP_SURESI)
            update_lcd_display("alert_greeting")
            # DÜZELTME: Mesajın ekranda okunabilmesi için 2 saniye bekle.
            time.sleep(2.0)
            if status_led:
                if led_is_blinking:
                    status_led.off(); time.sleep(0.01); status_led.on()
                elif not status_led.is_lit:
                    status_led.on()
            led_is_blinking = False
            object_alert_active = True
            newly_detected_for_pause = True  # Motor duraklatmasını tetiklemek için işaretle
    else:
        if object_alert_active:
            print("   <<< UYARI SONA ERDİ. >>>")
            update_lcd_display("normal_time")
            if status_led:
                if not led_is_blinking: status_led.blink(on_time=LED_BLINK_ON_SURESI, off_time=LED_BLINK_OFF_SURESI,
                                                         background=True)
            led_is_blinking = True
            object_alert_active = False
        else:
            update_lcd_display("normal_time")
            if status_led and not led_is_blinking:
                status_led.blink(on_time=LED_BLINK_ON_SURESI, off_time=LED_BLINK_OFF_SURESI, background=True)
                led_is_blinking = True

    return is_object_currently_close, newly_detected_for_pause


# ==============================================================================
# --- ANA ÇALIŞMA BLOĞU ---
# ==============================================================================
if __name__ == "__main__":
    # PID ve kilit dosyalarını program sonunda temizle
    atexit.register(remove_pid_and_lock_files)

    # Programın başında PID ve kilit dosyalarını oluştur
    create_pid_file()

    atexit.register(release_resources_on_exit)
    if not init_hardware():
        sys.exit(1)

    print("\n>>> Serbest Tarama Modu V6 Başlatıldı (Sürekli Ölçümlü Duraklatma) <<<")
    print(f"Tarama Açıları: -{SWEEP_TARGET_ANGLE}° ile +{SWEEP_TARGET_ANGLE}° arası")

    move_motor_to_absolute_angle(0)
    update_lcd_display("normal_time")

    try:
        while True:
            tur_etaplari = [
                (SWEEP_TARGET_ANGLE, f"Merkezden +{SWEEP_TARGET_ANGLE}° yönüne"),
                (-SWEEP_TARGET_ANGLE, f"+{SWEEP_TARGET_ANGLE}°'den -{SWEEP_TARGET_ANGLE}° yönüne"),
                (0, f"-{SWEEP_TARGET_ANGLE}°'den Merkeze (0°)")
            ]

            for hedef_aci_etap, etap_adi in tur_etaplari:
                if motor_movement_paused and time.time() < motor_pause_end_time:
                    while time.time() < motor_pause_end_time:
                        perform_measurement_and_react()
                        time.sleep(0.05)
                    motor_movement_paused = False
                    print("   Duraklatma bitti, harekete devam ediliyor...")

                print(f"\n>> Etap: {etap_adi} taranıyor...")

                angle_diff_for_direction = hedef_aci_etap - current_motor_angle_global
                if abs(angle_diff_for_direction) > 180:
                    angle_diff_for_direction -= (360 if angle_diff_for_direction > 0 else -360)

                direction_is_positive_etap = angle_diff_for_direction > 0

                while True:
                    if abs(current_motor_angle_global - hedef_aci_etap) < DEG_PER_STEP:
                        current_motor_angle_global = hedef_aci_etap
                        break

                    if (direction_is_positive_etap and current_motor_angle_global > hedef_aci_etap + DEG_PER_STEP) or \
                            (not direction_is_positive_etap and current_motor_angle_global < hedef_aci_etap - DEG_PER_STEP):
                        current_motor_angle_global = hedef_aci_etap
                        break

                    if not motor_movement_paused:
                        _single_step_motor(direction_is_positive_etap)

                    is_close, new_alert = perform_measurement_and_react()

                    if new_alert and not motor_movement_paused:
                        print(f"   Motor {MOTOR_PAUSE_ON_DETECTION_S} saniye duraklatılıyor (tarama sırasında)...")
                        motor_movement_paused = True
                        motor_pause_end_time = time.time() + MOTOR_PAUSE_ON_DETECTION_S

                    if motor_movement_paused and time.time() >= motor_pause_end_time:
                        print("   Motor duraklatma süresi bitti, devam edilecek...")
                        motor_movement_paused = False

                    if motor_movement_paused:
                        time.sleep(0.05)

                print(f"   Etap '{etap_adi}' tamamlandı. Mevcut Açı: {current_motor_angle_global:.1f}°")

            print(f"\n>>> Bir tur tamamlandı. Merkeze dönüldü ({current_motor_angle_global:.1f}°). {CYCLE_END_PAUSE_S} saniye bekleniyor...")

            object_alert_active = False
            perform_measurement_and_react()

            pause_start_time_cycle_end = time.time()
            while time.time() - pause_start_time_cycle_end < CYCLE_END_PAUSE_S:
                is_close_cycle_pause, new_alert_cycle_pause = perform_measurement_and_react()

                if new_alert_cycle_pause and not motor_movement_paused:
                    print(f"   Motor {MOTOR_PAUSE_ON_DETECTION_S} saniye duraklatılıyor (tur sonu beklemede)...")
                    motor_movement_paused = True
                    motor_pause_end_time = time.time() + MOTOR_PAUSE_ON_DETECTION_S

                if motor_movement_paused and time.time() >= motor_pause_end_time:
                    print("   Motor duraklatma süresi bitti (tur sonu beklemede)...")
                    motor_movement_paused = False

                if motor_movement_paused:
                    temp_pause_start = time.time()
                    while time.time() < motor_pause_end_time:
                        perform_measurement_and_react()
                        time.sleep(0.05)
                    motor_movement_paused = False
                    print("   Nesne uyarısı sonrası tur sonu beklemesine devam...")

                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruluyor...")
    finally:
        print("Program sonlanıyor...")
        if init_hardware_called_successfully:
            print("Motor başlangıç pozisyonuna (0°) getiriliyor...")
            move_motor_to_absolute_angle(0, speed_factor=0.5)
        else:
            print("Donanım başlatılamadığı için motor homing atlanıyor, pinler sıfırlanacak.")
            _set_step_pins(0, 0, 0, 0)
        print("Çıkış işlemleri tamamlandı.")
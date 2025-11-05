import machine
import time
import sys
import select
import TMC_UART  # TMC_UART.py dosyasının Pico'da olduğundan emin olun

# --- Pin Tanımlamaları (Değişmedi) ---

# 1. UART (TMC2209 Yapılandırması için)
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0))
time.sleep_ms(100)

# 2. Motor (STEP/DIR/EN) Pinleri
motor_pins = {
    'sol_on': (machine.Pin(2, machine.Pin.OUT), machine.Pin(3, machine.Pin.OUT), machine.Pin(4, machine.Pin.OUT), 0x00),
    'sag_on': (machine.Pin(5, machine.Pin.OUT), machine.Pin(6, machine.Pin.OUT), machine.Pin(7, machine.Pin.OUT), 0x01),
    'sol_arka': (machine.Pin(8, machine.Pin.OUT), machine.Pin(9, machine.Pin.OUT), machine.Pin(10, machine.Pin.OUT),
                 0x02),
    'sag_arka': (machine.Pin(11, machine.Pin.OUT), machine.Pin(12, machine.Pin.OUT), machine.Pin(13, machine.Pin.OUT),
                 0x03),
}

# 3. TMC2209 Sürücü Nesneleri
drivers = {}
for name, pins in motor_pins.items():
    step_pin, dir_pin, en_pin = pins[0], pins[1], pins[2]
    address = pins[3]
    step_pin.value(0)
    dir_pin.value(0)
    en_pin.value(1)  # Pasif
    drivers[name] = TMC_UART.TMC_UART(uart, slave_address=address)

# --- Sürücüleri UART ile Yapılandırma (Değişmedi) ---
RUN_CURRENT_PERCENT = 75
HOLD_CURRENT_PERCENT = 40
MICROSTEPS = 16

for name, driver in drivers.items():
    try:
        driver.set_run_current(RUN_CURRENT_PERCENT, HOLD_CURRENT_PERCENT)
        driver.set_microsteps(MICROSTEPS)
        driver.enable_stealthchop(True)
        driver.set_toff(4)
        driver.enable_interpolation(True)
    except Exception as e:
        print(f"HATA: {name} motoru yapılandırılamadı. {e}")
        # Hata olursa burada dur
        while True: time.sleep(1)

# --- Hareket Fonksiyonları (Değişmedi) ---
STEP_DELAY_US = 250
YON_ILERI = 1
YON_GERI = 0
STEPS_PER_REV = 200 * MICROSTEPS  # Tam tur için 3200 adım


def stop_all_motors():
    for name, pins in motor_pins.items():
        pins[2].value(1)  # EN=1 (Pasif)


def araba_ileri(steps):
    for name, pins in motor_pins.items():
        pins[1].value(YON_ILERI)
        pins[2].value(0)

    for _ in range(steps):
        for name, pins in motor_pins.items(): pins[0].value(1)
        time.sleep_us(STEP_DELAY_US)
        for name, pins in motor_pins.items(): pins[0].value(0)
        time.sleep_us(STEP_DELAY_US)
    stop_all_motors()


def araba_geri(steps):
    for name, pins in motor_pins.items():
        pins[1].value(YON_GERI)
        pins[2].value(0)

    for _ in range(steps):
        for name, pins in motor_pins.items(): pins[0].value(1)
        time.sleep_us(STEP_DELAY_US)
        for name, pins in motor_pins.items(): pins[0].value(0)
        time.sleep_us(STEP_DELAY_US)
    stop_all_motors()


def araba_don_sag(steps):
    motor_pins['sol_on'][1].value(YON_ILERI)
    motor_pins['sol_arka'][1].value(YON_ILERI)
    motor_pins['sag_on'][1].value(YON_GERI)
    motor_pins['sag_arka'][1].value(YON_GERI)
    for name, pins in motor_pins.items(): pins[2].value(0)

    for _ in range(steps):
        for name, pins in motor_pins.items(): pins[0].value(1)
        time.sleep_us(STEP_DELAY_US)
        for name, pins in motor_pins.items(): pins[0].value(0)
        time.sleep_us(STEP_DELAY_US)
    stop_all_motors()


def araba_don_sol(steps):
    motor_pins['sol_on'][1].value(YON_GERI)
    motor_pins['sol_arka'][1].value(YON_GERI)
    motor_pins['sag_on'][1].value(YON_ILERI)
    motor_pins['sag_arka'][1].value(YON_ILERI)
    for name, pins in motor_pins.items(): pins[2].value(0)

    for _ in range(steps):
        for name, pins in motor_pins.items(): pins[0].value(1)
        time.sleep_us(STEP_DELAY_US)
        for name, pins in motor_pins.items(): pins[0].value(0)
        time.sleep_us(STEP_DELAY_US)
    stop_all_motors()


# --- YENİ BÖLÜM: KOMUT DİNLEME DÖNGÜSÜ ---

# USB'den (stdin) gelen verileri kontrol etmek için bir anket nesnesi
poll_obj = select.poll()
poll_obj.register(sys.stdin, select.POLLIN)

print("Pico (Kas) Hazir. Pi 5 (Beyin) komutlari bekleniyor...")

while True:
    # USB'de veri var mı diye 1ms bekle
    if poll_obj.poll(1):
        # Veriyi satır satır oku (Pi 5'ten gelen '\n' sonlu komut)
        command_line = sys.stdin.readline().strip()

        if command_line:
            parts = command_line.split()
            if not parts:
                continue

            cmd = parts[0].upper()

            # Komut için adım sayısı parametresini al
            try:
                # Komutta bir sayı varsa onu kullan
                steps = int(parts[1])
            except (IndexError, ValueError):
                # Sayı yoksa varsayılan olarak 1 tam tur kullan
                steps = STEPS_PER_REV

                # Komutları işle
            if cmd == 'FWD':
                araba_ileri(steps)
            elif cmd == 'REV':
                araba_geri(steps)
            elif cmd == 'LEFT':
                araba_don_sol(steps)
            elif cmd == 'RIGHT':
                araba_don_sag(steps)
            elif cmd == 'STOP':
                stop_all_motors()
            else:
                # Bilinmeyen komut
                print(f"HATA: Bilinmeyen komut: {command_line}")
                continue  # Yanıt gönderme

            # Komutun bittiğine dair Pi 5'e yanıt gönder
            print(f"OK: {command_line}")
# Gerekli kütüphaneleri içe aktar
import machine
import utime

# --- Motor 1 Ayarları ---
motor1_pins = [
    machine.Pin(2, machine.Pin.OUT),
    machine.Pin(3, machine.Pin.OUT),
    machine.Pin(4, machine.Pin.OUT),
    machine.Pin(5, machine.Pin.OUT)
]

# --- Motor 2 Ayarları ---
motor2_pins = [
    machine.Pin(16, machine.Pin.OUT),
    machine.Pin(17, machine.Pin.OUT),
    machine.Pin(18, machine.Pin.OUT),
    machine.Pin(19, machine.Pin.OUT)
]

# --- Sensör Ayarları ---
# Sensör (buton) için bir GPIO pini tanımla.
# Pin.PULL_DOWN: Butona basılmadığında pin değeri 0 (LOW) olur.
# Butona basıldığında 3.3V'a bağlanacağı için değeri 1 (HIGH) olur.
sensor_pin = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_DOWN)

# Step motorlar için adım dizisi (yarım adım - half-step)
step_sequence = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]


def move_motor(motor_pins, steps, direction, delay_ms):
    """
    Belirtilen motoru, belirtilen adım sayısı ve yönde hareket ettirir.
    """
    steps_in_sequence = len(step_sequence)
    current_step = 0

    for _ in range(steps):
        current_step = (current_step + direction) % steps_in_sequence
        for i in range(len(motor_pins)):
            motor_pins[i].value(step_sequence[current_step][i])
        utime.sleep_ms(delay_ms)

    # Motoru durdurmak için tüm pinleri kapat
    for pin in motor_pins:
        pin.value(0)


# --- Ana Program Döngüsü ---
if __name__ == "__main__":
    print("Sensör kontrollü motor programı başlatıldı.")
    print("Motorları çalıştırmak için sensörü (butonu) tetikleyin...")

    motor_speed_delay = 2
    quarter_turn = 1024

    while True:
        # Sensörün tetiklenmesini bekle (butonun basılmasını kontrol et)
        if sensor_pin.value() == 1:
            print("Sensör tetiklendi! Hareket başlıyor...")

            # Motor 1'i hareket ettir
            print("--> Motor 1 saat yönünde çeyrek tur dönüyor...")
            move_motor(motor1_pins, quarter_turn, 1, motor_speed_delay)
            utime.sleep(0.5)  # İki motor arasında kısa bir bekleme

            # Motor 2'yi hareket ettir
            print("--> Motor 2 saat yönünde çeyrek tur dönüyor...")
            move_motor(motor2_pins, quarter_turn, 1, motor_speed_delay)

            print("\nHareket tamamlandı. Yeni tetikleme bekleniyor...")

            # Butonun bırakılmasını bekle (çoklu tetiklemeyi önlemek için)
            while sensor_pin.value() == 1:
                utime.sleep_ms(50)

        # CPU'yu yormamak için döngüde küçük bir bekleme
        utime.sleep_ms(10)
import time
import atexit
from gpiozero import OutputDevice
from gpiozero import Device
from gpiozero.pins.lgpio import LGPIOFactory

# Raspberry Pi 5 için en stabil pin factory'yi ayarlıyoruz
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory (Raspberry Pi 5 uyumlu) basariyla ayarlandi.")
except Exception as e:
    safe_error_message = str(e).encode('ascii', 'ignore').decode('ascii')
    print(f"UYARI: lgpio pin factory ayarlanamadi: {safe_error_message}")

# --- PIN TANIMLAMALARI ---
# Sol Motor Sürücüsü Pinleri
LEFT_IN1 = OutputDevice(21)
LEFT_IN2 = OutputDevice(20)
LEFT_IN3 = OutputDevice(16)
LEFT_IN4 = OutputDevice(12)
left_motor_pins = [LEFT_IN1, LEFT_IN2, LEFT_IN3, LEFT_IN4]


# Sağ Motor Sürücüsü Pinleri
RIGHT_IN1 = OutputDevice(26)
RIGHT_IN2 = OutputDevice(19)
RIGHT_IN3 = OutputDevice(13)
RIGHT_IN4 = OutputDevice(6)
right_motor_pins = [RIGHT_IN1, RIGHT_IN2, RIGHT_IN3, RIGHT_IN4]


# --- PARAMETRELER ---
STEP_DELAY = 0.002  # Hızı belirler. Değeri küçülttükçe motor hızlanır.
STEPS_PER_MOVE = 1024  # Her harekette atılacak adım sayısı (yaklaşık çeyrek tur)

# Yarım adım (half-step) sekansı
step_sequence = [
    [1, 0, 0, 1],
    [0, 0, 0, 1],
    [0, 0, 1, 1],
    [0, 0, 1, 0],
    [0, 1, 1, 0],
    [0, 1, 0, 0],
    [1, 1, 0, 0],
    [1, 0, 0, 0]
]
sequence_count = len(step_sequence)
left_step_index = 0
right_step_index = 0


def cleanup():
    """Tüm pinleri kapatır."""
    print("Tum motor pinleri kapatiliyor...")
    for pin in left_motor_pins + right_motor_pins:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


def take_a_step(direction_left, direction_right):
    """Her iki motor için bir adım atar."""
    global left_step_index, right_step_index

    # Sol motor için bir adım
    if direction_left == 'forward':
        left_step_index = (left_step_index + 1) % sequence_count
    elif direction_left == 'backward':
        left_step_index = (left_step_index - 1 + sequence_count) % sequence_count

    # Sağ motor için bir adım (Ters yönde döneceği için yönler de ters)
    if direction_right == 'forward':
        right_step_index = (right_step_index - 1 + sequence_count) % sequence_count
    elif direction_right == 'backward':
        right_step_index = (right_step_index + 1) % sequence_count

    # Sol motor pinlerini ayarla
    for pin_index, pin_state in enumerate(step_sequence[left_step_index]):
        left_motor_pins[pin_index].value = pin_state

    # Sağ motor pinlerini ayarla
    for pin_index, pin_state in enumerate(step_sequence[right_step_index]):
        right_motor_pins[pin_index].value = pin_state

    time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- 28BYJ-48 & ULN2003 Diferansiyel Sürüş Testi Başlatılıyor ---")

    print(f"\n[TEST 1/4] İleri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('forward', 'forward')

    time.sleep(1)

    print(f"\n[TEST 2/4] Geri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('backward', 'backward')

    time.sleep(1)

    print(f"\n[TEST 3/4] Sağa Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('forward', 'backward')  # Sol ileri, Sağ geri

    time.sleep(1)

    print(f"\n[TEST 4/4] Sola Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('backward', 'forward')  # Sol geri, Sağ ileri

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")

finally:
    pass
import time
import atexit
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory (Raspberry Pi 5 uyumlu) basariyla ayarlandi.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadi: {str(e)}")

# --- YENİ PIN TANIMLAMALARI ---
# Sol Motor Sürücüsü Pinleri
LEFT_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]
# Sağ Motor Sürücüsü Pinleri
RIGHT_PINS = [OutputDevice(2), OutputDevice(3), OutputDevice(4), OutputDevice(27)]

# --- PARAMETRELER ---
STEP_DELAY = 0.002
STEPS_PER_MOVE = 4096

# Daha yüksek tork için "Tam Adım" (full-step) sekansı
step_sequence = [
    [1, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 1],
    [1, 0, 0, 1]
]
sequence_count = len(step_sequence)
left_step_index = 0
right_step_index = 0


def cleanup():
    print("Tum motor pinleri kapatiliyor...")
    for pin in LEFT_PINS + RIGHT_PINS:
        pin.off();
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


def take_a_step(direction_left, direction_right):
    global left_step_index, right_step_index

    if direction_left == 'forward':
        left_step_index = (left_step_index + 1) % sequence_count
    elif direction_left == 'backward':
        left_step_index = (left_step_index - 1 + sequence_count) % sequence_count

    if direction_right == 'forward':
        right_step_index = (right_step_index - 1 + sequence_count) % sequence_count
    elif direction_right == 'backward':
        right_step_index = (right_step_index + 1) % sequence_count

    for i in range(4):
        LEFT_PINS[i].value = step_sequence[left_step_index][i]
        RIGHT_PINS[i].value = step_sequence[right_step_index][i]

    time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- 28BYJ-48 & ULN2003 Diferansiyel Sürüş Testi (YENİ PİNLER) Başlatılıyor ---")

    print(f"\n[TEST 1/4] İleri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE): take_a_step('forward', 'forward')
    time.sleep(1)

    print(f"\n[TEST 2/4] Geri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE): take_a_step('backward', 'backward')
    time.sleep(1)

    print(f"\n[TEST 3/4] Sağa Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE): take_a_step('forward', 'backward')
    time.sleep(1)

    print(f"\n[TEST 4/4] Sola Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE): take_a_step('backward', 'forward')

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")

finally:
    pass  # atexit modülü temizliği zaten yapıyor.

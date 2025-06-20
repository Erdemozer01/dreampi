import time
import atexit
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory (Raspberry Pi 5 uyumlu) basariyla ayarlandi.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadi: {str(e)}")

# --- PIN TANIMLAMALARI ---
LEFT_PINS = [OutputDevice(21), OutputDevice(20), OutputDevice(16), OutputDevice(12)]
RIGHT_PINS = [OutputDevice(26), OutputDevice(19), OutputDevice(13), OutputDevice(6)]

# --- PARAMETRELER ---
# DÜZELTME: Hızı maksimuma çıkarmak için gecikme düşürüldü.
STEP_DELAY = 0.002
STEPS_PER_MOVE = 4096  # Her harekette atılacak adım sayısı (yarım tur)

# DÜZELTME: Daha yüksek tork için "Tam Adım" (full-step) sekansı kullanılıyor.
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

    # Sol ve sağ motor pinlerini ayarla
    for i in range(4):
        LEFT_PINS[i].value = step_sequence[left_step_index][i]
        RIGHT_PINS[i].value = step_sequence[right_step_index][i]

    time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- 28BYJ-48 & ULN2003 Diferansiyel Sürüş Testi (TAM GÜÇ) Başlatılıyor ---")

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
        take_a_step('forward', 'backward')
    time.sleep(1)

    print(f"\n[TEST 4/4] Sola Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('backward', 'forward')

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
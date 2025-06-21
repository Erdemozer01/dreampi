import time
import atexit
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory (Raspberry Pi 5 uyumlu) basariyla ayarlandi.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadi: {str(e)}")

# --- PIN TANIMLAMALARI (Sizin Belirttiğiniz Kuruluma Göre) ---
REAR_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]  # Arka Tekerlekler
FRONT_PINS = [OutputDevice(2), OutputDevice(3), OutputDevice(4), OutputDevice(27)]  # Ön Tekerlekler

# --- PARAMETRELER ---
STEP_DELAY = 0.002
STEPS_PER_MOVE = 4096

# Daha yüksek tork için "Tam Adım" (full-step) sekansı
step_sequence = [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]]
sequence_count = len(step_sequence)
front_step_index = 0
rear_step_index = 0


def cleanup():
    print("Tum motor pinleri kapatiliyor...")
    for pin in FRONT_PINS + REAR_PINS:
        pin.off();
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


def take_a_step(direction_front, direction_rear):
    """Her iki motor seti için bir adım atar."""
    global front_step_index, rear_step_index

    # Ön motorlar için bir adım
    if direction_front == 'forward':
        front_step_index = (front_step_index + 1) % sequence_count
    elif direction_front == 'backward':
        front_step_index = (front_step_index - 1 + sequence_count) % sequence_count

    # Arka motorlar için bir adım
    if direction_rear == 'forward':
        rear_step_index = (rear_step_index + 1) % sequence_count
    elif direction_rear == 'backward':
        rear_step_index = (rear_step_index - 1 + sequence_count) % sequence_count

    # Pinleri ayarla
    for i in range(4):
        FRONT_PINS[i].value = step_sequence[front_step_index][i]
        REAR_PINS[i].value = step_sequence[rear_step_index][i]

    time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- 4x4 28BYJ-48 & ULN2003 Ön/Arka Sürüş Testi Başlatılıyor ---")

    print(f"\n[TEST 1/2] İleri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('forward', 'forward')
    time.sleep(1)

    print(f"\n[TEST 2/2] Geri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('backward', 'backward')
    time.sleep(1)

    print("\nUYARI: Bu pin kurulumuyla sağa/sola dönüş yapılamaz.")
    print("Dönüş kabiliyeti için motorları Sol/Sağ olarak gruplayın.")
    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
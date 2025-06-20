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
STEP_DELAY = 0.002
STEPS_TO_TEST = 512  # Kısa bir test için (1/8 tur)

step_sequence = [[1, 0, 0, 1], [0, 0, 0, 1], [0, 0, 1, 1], [0, 0, 1, 0], [0, 1, 1, 0], [0, 1, 0, 0], [1, 1, 0, 0],
                 [1, 0, 0, 0]]
sequence_count = len(step_sequence)


def cleanup():
    print("Tum motor pinleri kapatiliyor...")
    for pin in LEFT_PINS + RIGHT_PINS:
        pin.off();
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


def run_motor(pins, steps, is_forward):
    current_step = 0
    step_range = range(steps)

    for _ in step_range:
        if is_forward:
            current_step = (current_step + 1) % sequence_count
        else:
            current_step = (current_step - 1 + sequence_count) % sequence_count

        for pin_index, pin_state in enumerate(step_sequence[current_step]):
            pins[pin_index].value = pin_state
        time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- 28BYJ-48 & ULN2003 Sıralı Motor Testi Başlatılıyor ---")

    print(f"\n[TEST 1/2] Sadece SOL motor ileri hareket ettiriliyor ({STEPS_TO_TEST} adım)...")
    run_motor(LEFT_PINS, STEPS_TO_TEST, True)
    time.sleep(1)

    print(f"\n[TEST 2/2] Sadece SAĞ motor ileri hareket ettiriliyor ({STEPS_TO_TEST} adım)...")
    run_motor(RIGHT_PINS, STEPS_TO_TEST, True)

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")
    print("Eğer motorlar hala hareket etmiyorsa, aşağıdaki sorun giderme adımlarını kontrol edin.")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
import time
import atexit
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Raspberry Pi 5 ve uyumlu sistemler için lgpio pin factory kullanılması önerilir.
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory (Raspberry Pi 5 uyumlu) basariyla ayarlandi.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadi: {str(e)}")

# --- PIN TANIMLAMALARI (Tek Motorlu - Arkadan İtişli) ---
# Çıkartılan ön motorların yerine, bu pinler artık arka tekerlekleri kontrol etmektedir.
MOTOR_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]  # Arka Teker

# --- PARAMETRELER ---
STEP_DELAY = 0.002
# Bir tam tur için 4096 adım (yarım adım modunda)
STEPS_PER_FULL_ROTATION = 4096

# Daha yumuşak "Yarım Adım" (half-step) sekansı
step_sequence = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]
sequence_count = len(step_sequence)
step_index = 0


def cleanup():
    """Script sonlandığında tüm motor pinlerini güvenli bir şekilde kapatır."""
    print("Tum motor pinleri kapatiliyor...")
    for pin in MOTOR_PINS:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


# cleanup fonksiyonunu script'in herhangi bir nedenle çıkışında çalışacak şekilde kaydet
atexit.register(cleanup)


def take_a_step(direction):
    """Motor için belirtilen yönde bir adım atar."""
    global step_index

    # Not: 'forward' komutunun aracı fiziksel olarak ileri götürmesi,
    # motorun montaj yönüne bağlıdır. Gerekirse 'forward' ve 'backward'
    # mantığını ters çevirebilirsiniz.
    if direction == 'forward':
        step_index = (step_index + 1) % sequence_count
    elif direction == 'backward':
        step_index = (step_index - 1 + sequence_count) % sequence_count

    # Pinleri ayarla
    for i in range(4):
        MOTOR_PINS[i].value = step_sequence[step_index][i]

    time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ (Tek Motor Testi) ---
try:
    print("--- Arkadan İtişli 28BYJ-48 & ULN2003 Sürüş Testi Başlatılıyor ---")

    print(f"\n[TEST 1/2] İleri Hareket ({STEPS_PER_FULL_ROTATION} adım)...")
    for _ in range(STEPS_PER_FULL_ROTATION):
        take_a_step('forward')
    time.sleep(2)

    print(f"\n[TEST 2/2] Geri Hareket ({STEPS_PER_FULL_ROTATION} adım)...")
    for _ in range(STEPS_PER_FULL_ROTATION):
        take_a_step('backward')
    time.sleep(2)

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
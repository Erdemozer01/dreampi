import time
import atexit
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Sadece sağ motoru test ediyoruz
SAG_MOTOR_PINS = [OutputDevice(4), OutputDevice(14), OutputDevice(15), OutputDevice(18)]
print("Pinler ayarlandi: GPIO 4, 14, 15, 18")

# Pin factory ayarları
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory ayarlandi.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadi: {str(e)}")

# Adım sekansı
step_sequence = [
    [1, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 1],
    [1, 0, 0, 1]
]
sequence_count = len(step_sequence)
step_index = 0


def cleanup():
    print("\nMotor pinleri kapatiliyor...")
    for pin in SAG_MOTOR_PINS:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)

# --- ANA TEST ---
try:
    print("--- SADECE SAĞ MOTOR TESTİ BAŞLATILIYOR ---")
    # Motoru 512 adım (çeyrek tur) ileri döndürmeyi dene
    for i in range(512):
        for pin_index in range(4):
            SAG_MOTOR_PINS[pin_index].value = step_sequence[step_index][pin_index]

        step_index = (step_index + 1) % sequence_count
        time.sleep(0.003)  # Biraz daha yavaş deneyelim

        # Her 100 adımda bir mesaj yazdır
        if i % 100 == 0:
            print(f"Adim {i}...")

    print("\n--- TEST TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! HATA: {e}")
import time
import atexit
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Pin factory ayarları
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory ayarlandi.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadi: {str(e)}")

# --- PIN TANIMLAMALARI (Tek Motor - Arka Aks) ---
MOTOR_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]

# --- PARAMETRELER ---
STEP_DELAY = 0.002

# Değiştirildi: Yüksek tork için "Tam Adım" (full-step) sekansı
step_sequence = [
    [1, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 1],
    [1, 0, 0, 1]
]
sequence_count = len(step_sequence)
step_index = 0


def cleanup():
    """Script durduğunda motor pinlerini kapatır."""
    print("\nMotor pinleri kapatiliyor...")
    for pin in MOTOR_PINS:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


def take_a_step(direction):
    """Motor için tek bir adım atar."""
    global step_index
    if direction == 'forward':
        step_index = (step_index + 1) % sequence_count
    elif direction == 'backward':
        step_index = (step_index - 1 + sequence_count) % sequence_count

    for i in range(4):
        MOTOR_PINS[i].value = step_sequence[step_index][i]
    time.sleep(STEP_DELAY)


# --- KONTROL FONKSİYONLARI ---

def ileri_git(adim_sayisi):
    """Belirtilen adım sayısı kadar aracı ileri hareket ettirir."""
    print(f"{adim_sayisi} adim ileri gidiliyor...")
    for _ in range(adim_sayisi):
        take_a_step('forward')


def geri_git(adim_sayisi):
    """Belirtilen adım sayısı kadar aracı geri hareket ettirir."""
    print(f"{adim_sayisi} adim geri gidiliyor...")
    for _ in range(adim_sayisi):
        take_a_step('backward')


def dur(saniye):
    """Belirtilen süre kadar bekler."""
    print(f"{saniye} saniye duruluyor...")
    time.sleep(saniye)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- Arkadan İtişli Araç Kontrolü (Tam Adım Modu) Başlatılıyor ---")

    # Değiştirildi: Tam adım modunda bir tam teker turu yaklaşık 2048 adımdır.
    bir_tur = 2048

    ileri_git(bir_tur)  # 1 tur ileri
    dur(2)  # 2 saniye bekle
    geri_git(bir_tur // 2)  # Yarım tur geri
    dur(2)  # 2 saniye bekle
    ileri_git(bir_tur // 4)  # Çeyrek tur ileri

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
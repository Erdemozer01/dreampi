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

# --- PIN TANIMLAMALARI ---
# Sol motor pinleri (Çalıştığı için bu kısım doğru varsayılıyor)
SOL_MOTOR_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]

# !!! KONTROL EDİLECEK YER !!!
# Bu koddaki sıralama, FİZİKSEL olarak sürücü kartınızdaki
# IN1, IN2, IN3, IN4 sıralamasıyla TAM OLARAK EŞLEŞMELİDİR.
SAG_MOTOR_PINS = [OutputDevice(22), OutputDevice(4), OutputDevice(14), OutputDevice(18)]

# --- PARAMETRELER ---
STEP_DELAY = 0.002  # Bu değeri 0.004 yaparak yavaşlatabilir ama kararlılığı artırabilirsiniz

# --- Değişkenler ---
step_sequence = [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]]
sequence_count = len(step_sequence)
sol_motor_step_index = 0
sag_motor_step_index = 0


def cleanup():
    print("\nMotor pinleri kapatiliyor...")
    all_pins = SOL_MOTOR_PINS + SAG_MOTOR_PINS
    for pin in all_pins:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


# --- KONTROL FONKSİYONLARI ---

def hareket_et(sol_yon, sag_yon, adim_sayisi):
    """Her iki motoru optimize bir şekilde hareket ettirir."""
    global sol_motor_step_index, sag_motor_step_index
    print(f"{adim_sayisi} adim: Sol Motor -> {sol_yon}, Sağ Motor -> {sag_yon}")

    for _ in range(adim_sayisi):
        if sol_yon == 'ileri':
            sol_motor_step_index = (sol_motor_step_index + 1) % sequence_count
        elif sol_yon == 'geri':
            sol_motor_step_index = (sol_motor_step_index - 1 + sequence_count) % sequence_count

        if sag_yon == 'ileri':
            sag_motor_step_index = (sag_motor_step_index + 1) % sequence_count
        elif sag_yon == 'geri':
            sag_motor_step_index = (sag_motor_step_index - 1 + sequence_count) % sequence_count

        sol_sequence_step = step_sequence[sol_motor_step_index]
        sag_sequence_step = step_sequence[sag_motor_step_index]

        for i in range(4):
            if sol_yon != 'dur':
                SOL_MOTOR_PINS[i].value = sol_sequence_step[i]
            if sag_yon != 'dur':
                SAG_MOTOR_PINS[i].value = sag_sequence_step[i]

        time.sleep(STEP_DELAY)


# Diğer yüksek seviye fonksiyonlar (ileri_git, geri_git, saga_don, sola_don, dur)
# Bu fonksiyonlarda değişiklik yapmaya gerek yok.
def ileri_git(adim_sayisi):
    hareket_et('ileri', 'ileri', adim_sayisi)


def geri_git(adim_sayisi):
    hareket_et('geri', 'geri', adim_sayisi)


def saga_don(adim_sayisi):
    hareket_et('ileri', 'geri', adim_sayisi)


def sola_don(adim_sayisi):
    hareket_et('geri', 'ileri', adim_sayisi)


def dur(saniye):
    all_pins = SOL_MOTOR_PINS + SAG_MOTOR_PINS
    for pin in all_pins:
        pin.off()
    print(f"{saniye} saniye duruluyor...")
    time.sleep(saniye)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- Test Başlatılıyor ---")
    ileri_git(2048)  # 1 tam tur ileri gitmeyi dene
    print("\n--- TEST TAMAMLANDI ---")
except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! HATA: {e}")
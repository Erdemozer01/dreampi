import time
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# --- Pin Factory Ayarları ---
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory ayarlandı.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadı: {str(e)}")

# --- PIN TANIMLAMALARI ---
SOL_MOTOR_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]
# UYARI: GPIO 14 bir UART pinidir. Kullanmak için `sudo raspi-config` ile seri konsolu kapatmanız gerekir.
# Veya bu listeyi [17, 27, 22, 23] gibi güvenli pinlerle değiştirin.
SAG_MOTOR_PINS = [OutputDevice(22), OutputDevice(15), OutputDevice(4), OutputDevice(18)]

# --- PARAMETRELER ---
STEP_DELAY = 0.003
step_sequence = [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]]
sequence_count = len(step_sequence)

sol_motor_step_index = 0
sag_motor_step_index = 0

def cleanup():
    """Script durduğunda TÜM motor pinlerini kapatır."""
    print("\nMotor pinleri kapatılıyor...")
    all_pins = SOL_MOTOR_PINS + SAG_MOTOR_PINS
    for pin in all_pins:
        # DÜZELTME: 'is_closed' yerine 'closed' kullanıldı.
        if not pin.closed:
            pin.off()
            pin.close()
    print("Temizleme tamamlandı.")

# --- ANA KONTROL FONKSİYONU ---
def hareket_et(sol_yon, sag_yon, adim_sayisi):
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

# --- Hareket Fonksiyonları ---
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
        if not pin.closed:
            pin.off()
    print(f"{saniye} saniye duruluyor...")
    time.sleep(saniye)

# --- ANA TEST DÖNGÜSÜ ---
if __name__ == "__main__":
    try:
        print("--- Diferansiyel Sürüş Testi Başlatılıyor ---")
        kisa_mesafe = 512
        donus_miktari = 512
        print("\n1. Adım: İleri Git")
        ileri_git(kisa_mesafe)
        dur(2)
        print("\n2. Adım: Sağa Dönüş")
        saga_don(donus_miktari)
        dur(2)
        print("\n3. Adım: Sola Dönüş")
        sola_don(donus_miktari)
        dur(2)
        print("\n4. Adım: Geri Git")
        geri_git(kisa_mesafe)
        dur(2)
        print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")
    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
    finally:
        # Kod bittiğinde veya hata verdiğinde her şeyi temizle
        cleanup()
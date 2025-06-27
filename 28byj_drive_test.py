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

# --- PIN TANIMLAMALARI (İki Bağımsız Motor - Sağ/Sol) ---
# Lütfen bu pin numaralarını kendi bağlantılarınıza göre güncelleyin.
SOL_MOTOR_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]
SAG_MOTOR_PINS = [OutputDevice(4), OutputDevice(14), OutputDevice(15), OutputDevice(18)]

# --- PARAMETRELER ---
STEP_DELAY = 0.004
# Yüksek tork için "Tam Adım" (full-step) sekansı
step_sequence = [
    [1, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 1],
    [1, 0, 0, 1]
]
sequence_count = len(step_sequence)

# Her motor için ayrı adım pozisyonu
sol_motor_step_index = 0
sag_motor_step_index = 0


def cleanup():
    """Script durduğunda TÜM motor pinlerini kapatır."""
    print("\nMotor pinleri kapatiliyor...")
    all_pins = SOL_MOTOR_PINS + SAG_MOTOR_PINS
    for pin in all_pins:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


atexit.register(cleanup)


# --- DÜŞÜK SEVİYE MOTOR KONTROLÜ ---


# YERİNE BU YENİ FONKSİYONU EKLEYİN:

def hareket_et(sol_yon, sag_yon, adim_sayisi):
    """Her iki motoru daha optimize bir şekilde hareket ettirir."""
    global sol_motor_step_index, sag_motor_step_index

    print(f"{adim_sayisi} adim: Sol Motor -> {sol_yon}, Sağ Motor -> {sag_yon}")

    for _ in range(adim_sayisi):
        # Önce her iki motorun bir sonraki adımını hesapla
        if sol_yon == 'ileri':
            sol_motor_step_index = (sol_motor_step_index + 1) % sequence_count
        elif sol_yon == 'geri':
            sol_motor_step_index = (sol_motor_step_index - 1 + sequence_count) % sequence_count

        if sag_yon == 'ileri':
            sag_motor_step_index = (sag_motor_step_index + 1) % sequence_count
        elif sag_yon == 'geri':
            sag_motor_step_index = (sag_motor_step_index - 1 + sequence_count) % sequence_count

        # İlgili adım sekanslarını al
        sol_sequence_step = step_sequence[sol_motor_step_index]
        sag_sequence_step = step_sequence[sag_motor_step_index]

        # Tek bir blokta tüm pinleri ayarla (daha verimli)
        for i in range(4):
            if sol_yon != 'dur':
                SOL_MOTOR_PINS[i].value = sol_sequence_step[i]
            if sag_yon != 'dur':
                SAG_MOTOR_PINS[i].value = sag_sequence_step[i]

        time.sleep(STEP_DELAY)


# --- YÜKSEK SEVİYE KONTROL FONKSİYONLARI ---

def hareket_et(sol_yon, sag_yon, adim_sayisi):
    """Her iki motoru belirtilen yönlerde ve adım sayısında hareket ettirir."""
    global sol_motor_step_index, sag_motor_step_index

    print(f"{adim_sayisi} adim: Sol Motor -> {sol_yon}, Sağ Motor -> {sag_yon}")

    for _ in range(adim_sayisi):
        sol_motor_step_index = motor_adim_at(SOL_MOTOR_PINS, sol_motor_step_index, sol_yon)
        sag_motor_step_index = motor_adim_at(SAG_MOTOR_PINS, sag_motor_step_index, sag_yon)
        time.sleep(STEP_DELAY)


def ileri_git(adim_sayisi):
    hareket_et('ileri', 'ileri', adim_sayisi)


def geri_git(adim_sayisi):
    hareket_et('geri', 'geri', adim_sayisi)


def saga_don(adim_sayisi):
    """Yerinde sağa döner (sol ileri, sağ geri)."""
    hareket_et('ileri', 'geri', adim_sayisi)


def sola_don(adim_sayisi):
    """Yerinde sola döner (sağ ileri, sol geri)."""
    hareket_et('geri', 'ileri', adim_sayisi)


def dur(saniye):
    """Tüm motorları durdurup belirtilen süre kadar bekler."""
    # Motorları durdurmak için pinlere güç vermeyi kesiyoruz.
    # cleanup fonksiyonu script sonunda zaten kapatacaktır.
    # Alternatif olarak tüm pinleri .off() yapabilirsiniz.
    all_pins = SOL_MOTOR_PINS + SAG_MOTOR_PINS
    for pin in all_pins:
        pin.off()
    print(f"{saniye} saniye duruluyor...")
    time.sleep(saniye)


# --- ANA TEST DÖNGÜSÜ ---
try:
    print("--- Diferansiyel Sürüşlü Araç Kontrolü Başlatılıyor ---")

    # Bir tekerin tam turu için gereken adım sayısı (~2048)
    bir_tur = 2048
    # Aracın 90 derece dönmesi için gereken adım sayısı. Deneyerek bulmalısınız.
    doksan_derece_donus = 1024

    ileri_git(bir_tur)  # 1 tur ileri
    dur(1)

    saga_don(doksan_derece_donus)  # 90 derece sağa dön
    dur(1)

    ileri_git(bir_tur)  # 1 tur daha ileri
    dur(1)

    sola_don(doksan_derece_donus)  # 90 derece sola dönerek başlangıç yönüne gel
    dur(2)

    geri_git(bir_tur // 2)  # Yarım tur geri

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
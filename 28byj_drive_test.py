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

# --- PIN TANIMLAMALARI (İsteğinize Göre Düzenlendi) ---
# Not: Mantıksal olarak burası hala aracın "sol tarafı" gibi çalışır.
LEFT_PINS = [OutputDevice(25), OutputDevice(8), OutputDevice(7), OutputDevice(5)]  # Ön Teker
# Not: Mantıksal olarak burası hala aracın "sağ tarafı" gibi çalışır.
RIGHT_PINS = [OutputDevice(14), OutputDevice(15), OutputDevice(18), OutputDevice(4)] # Arka Teker

# --- PARAMETRELER ---
STEP_DELAY = 0.001
STEPS_PER_MOVE = 2048

# Daha yüksek tork için "Tam Adım" (full-step) sekansı
step_sequence = [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]]
sequence_count = len(step_sequence)
left_step_index = 0
right_step_index = 0


def cleanup():
    """Script sonlandığında tüm motor pinlerini güvenli bir şekilde kapatır."""
    print("Tum motor pinleri kapatiliyor...")
    for pin in LEFT_PINS + RIGHT_PINS:
        pin.off()
        pin.close()
    print("Temizleme tamamlandi.")


# cleanup fonksiyonunu script'in herhangi bir nedenle çıkışında çalışacak şekilde kaydet
atexit.register(cleanup)


def take_a_step(direction_left, direction_right):
    """Her iki motor seti için bir adım atar."""
    global left_step_index, right_step_index

    # Sol (Ön) motorlar için bir adım
    if direction_left == 'forward':
        left_step_index = (left_step_index + 1) % sequence_count
    elif direction_left == 'backward':
        left_step_index = (left_step_index - 1 + sequence_count) % sequence_count

    # Sağ (Arka) motorlar, zıt yönde monte edildiği varsayılarak düz gitmek amacıyla ters yönde dönmelidir.
    if direction_right == 'forward':
        right_step_index = (right_step_index - 1 + sequence_count) % sequence_count
    elif direction_right == 'backward':
        right_step_index = (right_step_index + 1) % sequence_count

    # Pinleri ayarla
    for i in range(4):
        LEFT_PINS[i].value = step_sequence[left_step_index][i]
        RIGHT_PINS[i].value = step_sequence[right_step_index][i]

    time.sleep(STEP_DELAY)


# --- ANA TEST DÖNGÜSÜ (Dönüş Testleri Eklendi) ---
try:
    print("--- 4x4 28BYJ-48 & ULN2003 Diferansiyel Sürüş Testi Başlatılıyor ---")

    print(f"\n[TEST 1/4] İleri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('forward', 'forward')
    time.sleep(1)

    print(f"\n[TEST 2/4] Geri Hareket ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('backward', 'backward')
    time.sleep(3)

    print(f"\n[TEST 3/4] Sağa Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('forward', 'backward')  # Ön tekerler ileri, Arka tekerler geri
    time.sleep(3)

    print(f"\n[TEST 4/4] Sola Dönüş (Tank) ({STEPS_PER_MOVE} adım)...")
    for _ in range(STEPS_PER_MOVE):
        take_a_step('backward', 'forward')  # Ön tekerler geri, Arka tekerler ileri
    time.sleep(3)

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
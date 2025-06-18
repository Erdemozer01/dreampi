import time
import threading  # DÜZELTME: stop_event için gerekli kütüphane import edildi
from gpiozero import Motor
from gpiozero import Device
from gpiozero.pins.lgpio import LGPIOFactory

# Pin factory'yi doğrudan lgpio olarak ayarlıyoruz.
try:
    Device.pin_factory = LGPIOFactory()
    print("✓ lgpio pin factory (Raspberry Pi 5 uyumlu) başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: lgpio pin factory ayarlanamadı: {e}")
    print("Lütfen 'sudo apt-get install python3-lgpio' komutuyla kütüphanenin yüklü olduğundan emin olun.")

# --- PIN TANIMLAMALARI ---
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# Hız kontrolü için Enable pinleri
ENA_PIN_LEFT = 14
ENB_PIN_RIGHT = 15

# --- HIZ AYARLARI ---
MOVE_SPEED = 0.8
TURN_MAX_SPEED = 1.0

print("--- Yumuşak Kalkışlı Dönüş Testi Başlatılıyor ---")
print("Çıkmak için CTRL+C tuşlarına basın.")

# DÜZELTME: Güvenli durdurma için stop_event nesnesi oluşturuldu
stop_event = threading.Event()

left_motors = None
right_motors = None

try:
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD, enable=ENA_PIN_LEFT)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD, enable=ENB_PIN_RIGHT)

    print("\n[TEST 1/2] İleri Hareket Testi (2 saniye)...")
    left_motors.forward(speed=MOVE_SPEED)
    right_motors.forward(speed=MOVE_SPEED)
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 2/2] Sola Yumuşak Dönüş Testi (Soft Start)...")
    print("Hız yavaşça artırılıyor...")

    # Hızı 0'dan başlayarak yavaşça artırarak ani akım çekişini önlüyoruz.
    for speed_step in [0.4, 0.6, 0.8, TURN_MAX_SPEED]:
        # stop_event kontrolü, CTRL+C ile çıkışta döngünün kırılmasını sağlar
        if stop_event.is_set():
            break
        print(f"--> Dönüş Hızı: %{int(speed_step * 100)}")
        right_motors.forward(speed=speed_step)
        left_motors.backward(speed=speed_step)
        time.sleep(0.7)

    time.sleep(1)  # Tam hızda 1 saniye daha dön

    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")

    print("\n--- TÜM TESTLER BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
    stop_event.set()  # Döngünün durmasını garanti et
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
    print("Lütfen pin numaralarınızı ve donanım bağlantılarınızı kontrol edin.")

finally:
    print("Tüm motor nesneleri kapatılıyor...")
    if left_motors:
        left_motors.close()
    if right_motors:
        right_motors.close()
    print("Temizleme tamamlandı.")

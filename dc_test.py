import time
import threading
from gpiozero import Motor
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device

# pigpio'yu kullanmayı dene
try:
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

# --- PIN TANIMLAMALARI ---
# L298N Motor Sürücü Pinleri
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# Hız kontrolü için Enable pinleri
ENA_PIN_LEFT = 14
ENB_PIN_RIGHT = 15

# --- HIZ AYARLARI ---
MOVE_SPEED = 1  # İleri/geri hareket hızı (%80 güç)
TURN_SPEED = 1.0  # Dönüşlerin daha net olması için tam güç

print("--- Pivot Dönüşlü DC Motor Testi Başlatılıyor ---")
print("Çıkmak için CTRL+C tuşlarına basın.")

# Güvenli durdurma için bir event flag
stop_event = threading.Event()

left_motors = None
right_motors = None

try:
    # Motor nesnelerini, enable pinlerini de belirterek oluştur
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

    # DÜZELTME: Dönüş mantığı isteğinize göre güncellendi.

    print("\n[TEST 2/4] Sola Dönüş (Pivot) Testi (2 saniye)...")
    print("--> Sadece SAĞ motorlar İLERİ çalışacak.")
    right_motors.forward(speed=TURN_SPEED)  # Sağ tekerlek ileri
    left_motors.stop()  # Sol tekerlek duruyor
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 3/4] Sağa Dönüş (Pivot) Testi (2 saniye)...")
    print("--> Sadece SOL motorlar İLERİ çalışacak.")
    left_motors.forward(speed=TURN_SPEED)  # Sol tekerlek ileri
    right_motors.stop()  # Sağ tekerlek duruyor
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")

    print("\n--- TÜM TESTLER BAŞARIYLA TAMAMLANDI ---")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
    print("Lütfen pin numaralarınızı ve donanım bağlantılarınızı (Güç ve GND) kontrol edin.")

finally:
    print("Tüm motor nesneleri kapatılıyor...")
    if left_motors:
        left_motors.close()
    if right_motors:
        right_motors.close()
    print("Temizleme tamamlandı.")
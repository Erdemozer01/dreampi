import threading
import time
from gpiozero import Motor
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device

stop_event = threading.Event()

# pigpio'yu kullanmayı dene
try:
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

# --- PIN TANIMLAMALARI (GÜNCELLENDİ) ---
# L298N Motor Sürücü Pinleri
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# DÜZELTME: Hız kontrolü için Enable pinleri eklendi
# Lütfen bu GPIO pinlerini L298N'deki ENA ve ENB pinlerine bağlayın
ENA_PIN_LEFT = 14  # Sol motorlar için ENA
ENB_PIN_RIGHT = 15  # Sağ motorlar için ENB

# --- HIZ AYARLARI ---
MOVE_SPEED = 0.8  # İleri/geri hareket hızı (%80 güç)
TURN_MAX_SPEED = 1.0  # Dönüşlerin ulaşacağı maksimum hız (%100 güç)

print("--- PWM Hız Kontrollü DC Motor Testi Başlatılıyor ---")
print("Çıkmak için CTRL+C tuşlarına basın.")

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

    print("\n[TEST 2/2] Sola Yumuşak Dönüş Testi (Soft Start)...")
    print("Hız yavaşça artırılıyor...")

    # Hızı 0.3'ten başlayarak yavaşça artır
    for speed_step in [0.3, 0.5, 0.7, 0.9, TURN_MAX_SPEED]:
        if stop_event.is_set(): break
        print(f"--> Dönüş Hızı: %{int(speed_step * 100)}")
        left_motors.backward(speed=speed_step)  # Sol tekerlek geri
        right_motors.forward(speed=speed_step)  # Sağ tekerlek ileri
        time.sleep(0.5)  # Her hız adımında yarım saniye bekle

    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")

    print("\n--- TÜM TESTLER BAŞARIYLA TAMAMLANDI ---")

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

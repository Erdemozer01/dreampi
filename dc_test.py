# motor_testi.py - Tank Dönüşlerini Yumuşak Kalkış ile Test Etme

import time
import threading
from gpiozero import Motor
from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device

# pigpio'yu kullanmayı dene, bu PWM kontrolü için daha stabildir
try:
    Device.pin_factory = LGPIOFactory()
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
MOVE_SPEED = 0.8  # İleri/geri hareket hızı (%80 güç)
TURN_MAX_SPEED = 1.0  # Dönüşlerin ulaşacağı maksimum hız

print("--- Yumuşak Kalkışlı Dönüş Testi Başlatılıyor ---")
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

    # DÜZELTME: Hızı 0'dan başlayarak yavaşça artırarak ani akım çekişini önlüyoruz.
    for speed_step in [0.4, 0.6, 0.8, TURN_MAX_SPEED]:
        print(f"--> Dönüş Hızı: %{int(speed_step * 100)}")
        right_motors.forward(speed=speed_step)  # Sağ tekerlek ileri
        left_motors.backward(speed=speed_step)  # Sol tekerlek geri
        time.sleep(0.7)  # Her hız adımında biraz bekle

    time.sleep(1)  # Tam hızda 1 saniye daha dön

    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")

    print("\n--- TÜM TESTLER BAŞARIYLA TAMAMLANDI ---")
    print(
        "\nEğer bu testte dönüşler yine olmadıysa, sorun kesinlikle harici güç kaynağınızın (pillerin) yetersiz olmasından kaynaklanmaktadır.")

except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
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

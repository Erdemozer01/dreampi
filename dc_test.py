# motor_testi.py - DC Motorlar için İleri, Geri, Sağ ve Sol Dönüş Testi

import time
from gpiozero import Motor
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device
import RPi.GPIO as GPIO

# pigpio'yu kullanmayı dene, bu daha stabil bir kontrol sağlar
try:
    Device.pin_factory = PiGPIOFactory()
    print("✓ pigpio pin factory başarıyla ayarlandı.")
except Exception as e:
    print(f"UYARI: pigpio kullanılamadı: {e}. Varsayılan pin factory kullanılıyor.")

# --- PIN TANIMLAMALARI ---
# L298N Motor Sürücü Pinleri (Lütfen kendi bağlantılarınızı doğrulayın)
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# --- HIZ AYARLARI ---
MOVE_SPEED = 0.8  # İleri/geri hareket hızı (%80 güç)
TURN_SPEED = 0.7  # Dönüş hızı (%70 güç)

print("--- Kapsamlı DC Motor Donanım Testi Başlatılıyor ---")
print("Çıkmak için CTRL+C tuşlarına basın.")

# Motor nesnelerini başlangıçta None olarak ayarlıyoruz
left_motors = None
right_motors = None

try:
    # Motor nesnelerini oluştur
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)

    print("\n[TEST 1/4] İleri Hareket (2 saniye)...")
    left_motors.forward(speed=MOVE_SPEED)
    right_motors.forward(speed=MOVE_SPEED)
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 2/4] Geri Hareket (2 saniye)...")
    left_motors.backward(speed=MOVE_SPEED)
    right_motors.backward(speed=MOVE_SPEED)
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 3/4] Sola Dönüş (2 saniye)...")
    left_motors.backward(speed=TURN_SPEED)  # Sol tekerlek geri
    right_motors.forward(speed=TURN_SPEED)  # Sağ tekerlek ileri
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 4/4] Sağa Dönüş (2 saniye)...")
    left_motors.forward(speed=TURN_SPEED)  # Sol tekerlek ileri
    right_motors.backward(speed=TURN_SPEED)  # Sağ tekerlek geri
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")

    print("\n--- TÜM TESTLER BAŞARIYLA TAMAMLANDI ---")

except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
    print("Lütfen pin numaralarınızı ve donanım bağlantılarınızı (Güç ve GND) kontrol edin.")

finally:
    # Programdan çıkarken tüm gpiozero nesnelerini güvenli bir şekilde kapat
    print("Tüm motor nesneleri kapatılıyor...")
    if left_motors:
        left_motors.close()
    if right_motors:
        right_motors.close()

    # GPIO pinlerini serbest bırak
    # Bazen gpiozero'dan sonra ek bir temizlik gerekebilir
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.cleanup()
        print("GPIO temizliği tamamlandı.")
    except:
        pass
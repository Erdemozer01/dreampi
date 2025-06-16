# motor_testi.py - Sadece DC Motorları Test Etmek İçin Basit Betik

import time
from gpiozero import Motor
import RPi.GPIO as GPIO

# --- PIN TANIMLAMALARI ---
# L298N Motor Sürücü Pinleri (Lütfen kendi bağlantılarınızı doğrulayın)
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

print("--- Basit DC Motor Donanım Testi Başlatılıyor ---")
print("Bu test, sadece L298N sürücü ve tekerlek motorlarını kontrol eder.")
print("Çıkmak için CTRL+C tuşlarına basın.")

# gpiozero'nun pinleri serbest bırakmasını sağlamak için GPIO modunu ayarla
GPIO.setmode(GPIO.BCM)

try:
    # Motor nesnelerini oluştur
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)

    print("\n[TEST 1/4] Sol tekerlekler 2 saniye İLERİ döndürülüyor...")
    left_motors.forward()
    time.sleep(2)
    left_motors.stop()
    print("-> Sol tekerlekler durduruldu.")
    time.sleep(1)

    print("\n[TEST 2/4] Sol tekerlekler 2 saniye GERİ döndürülüyor...")
    left_motors.backward()
    time.sleep(2)
    left_motors.stop()
    print("-> Sol tekerlekler durduruldu.")
    time.sleep(1)

    print("\n[TEST 3/4] Sağ tekerlekler 2 saniye İLERİ döndürülüyor...")
    right_motors.forward()
    time.sleep(2)
    right_motors.stop()
    print("-> Sağ tekerlekler durduruldu.")
    time.sleep(1)

    print("\n[TEST 4/4] Sağ tekerlekler 2 saniye GERİ döndürülüyor...")
    right_motors.backward()
    time.sleep(2)
    right_motors.stop()
    print("-> Sağ tekerlekler durduruldu.")

    print("\n--- TEST BAŞARIYLA TAMAMLANDI ---")

except Exception as e:
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")
    print("Lütfen pin numaralarınızı ve donanım bağlantılarınızı kontrol edin.")

finally:
    # Programdan çıkarken tüm GPIO pinlerini temizle
    print("Tüm GPIO pinleri temizleniyor...")
    GPIO.cleanup()
    print("Temizleme tamamlandı.")
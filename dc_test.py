import time
import threading
from gpiozero import Motor, Device
from gpiozero.pins.lgpio import LGPIOFactory

# pigpio'yu kullanmayı dene, bu daha stabil bir kontrol sağlar
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] pigpio pin factory basariyla ayarlandi.")
except Exception as e:
    safe_error_message = str(e).encode('ascii', 'ignore').decode('ascii')
    print(f"UYARI: pigpio pin factory ayarlanamadi: {safe_error_message}")

# --- PIN TANIMLAMALARI ---
# L298N Motor Sürücü Pinleri
MOTOR_LEFT_FORWARD = 10
MOTOR_LEFT_BACKWARD = 9
MOTOR_RIGHT_FORWARD = 8
MOTOR_RIGHT_BACKWARD = 7

# ENA ve ENB pinleri artık yazılımda kullanılmıyor, jumper'lar takılı.

print("--- Jumper Takılı, Tam Güçte Dönüş Testi Başlatılıyor ---")
print("Çıkmak için CTRL+C tuşlarına basın.")

left_motors = None
right_motors = None

try:
    # Motor nesneleri, enable pinleri OLMADAN oluşturuluyor.
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD)

    print("\n[TEST 1/4] İleri Hareket Testi (2 saniye)...")
    left_motors.forward()
    right_motors.forward()
    time.sleep(2)
    left_motors.stop()
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 2/4] Geri Hareket Testi (2 saniye)...")
    left_motors.backward()
    right_motors.backward()
    time.sleep(2)
    left_motors.stop()
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 3/4] Sola Dönüş (Tank) Testi (2 saniye)...")
    print("--> Sağ motorlar İLERİ, Sol motorlar GERİ çalışacak.")
    right_motors.forward()  # Tam güç
    left_motors.stop()  # Tam güç
    time.sleep(10)
    left_motors.stop()
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 4/4] Sağa Dönüş (Tank) Testi (2 saniye)...")
    print("--> Sol motorlar İLERİ, Sağ motorlar GERİ çalışacak.")
    left_motors.forward()  # Tam güç
    right_motors.stop()  # Tam güç
    time.sleep(10)
    left_motors.stop()
    right_motors.stop()
    print("-> Durduruldu.")

    print("\n--- TÜM TESTLER BAŞARIYLA TAMAMLANDI ---")
    print(
        "\nEğer bu testte dönüşler yine de çalışmıyorsa, sorun kesinlikle harici güç kaynağınızın (pillerin) yetersizliğidir.")


except KeyboardInterrupt:
    print("\nKullanıcı tarafından durduruldu.")
except Exception as e:
    safe_error_message = str(e).encode('ascii', 'ignore').decode('ascii')
    print(f"\n!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {safe_error_message}")
    print("Lütfen pin numaralarınızı ve donanım bağlantılarınızı kontrol edin.")

finally:
    print("Tüm motor nesneleri kapatılıyor...")
    if left_motors:
        left_motors.close()
    if right_motors:
        right_motors.close()
    print("Temizleme tamamlandı.")
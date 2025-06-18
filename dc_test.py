import time
from gpiozero import Motor
from gpiozero import Device
from gpiozero.pins.lgpio import LGPIOFactory

# Pin factory'yi doğrudan lgpio olarak ayarlıyoruz.
try:
    Device.pin_factory = LGPIOFactory()
    print("[OK] lgpio pin factory (Raspberry Pi 5 uyumlu) basariyla ayarlandi.")
except Exception as e:
    safe_error_message = str(e).encode('ascii', 'ignore').decode('ascii')
    print(f"UYARI: lgpio pin factory ayarlanamadi: {safe_error_message}")
    print("Lutfen 'sudo apt-get install python3-lgpio' komutuyla kutuphanenin yuklu oldugundan emin olun.")

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
TURN_SPEED = 1.0  # Dönüşlerin net olması için tam güç

print("--- Pivot Dönüşlü DC Motor Testi Başlatılıyor ---")
print("Çıkmak için CTRL+C tuşlarına basın.")

left_motors = None
right_motors = None

try:
    left_motors = Motor(forward=MOTOR_LEFT_FORWARD, backward=MOTOR_LEFT_BACKWARD, enable=ENA_PIN_LEFT)
    right_motors = Motor(forward=MOTOR_RIGHT_FORWARD, backward=MOTOR_RIGHT_BACKWARD, enable=ENB_PIN_RIGHT)

    print("\n[TEST 1/4] İleri Hareket Testi (2 saniye)...")
    left_motors.forward(speed=MOVE_SPEED)
    right_motors.forward(speed=MOVE_SPEED)
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 2/4] Geri Hareket Testi (2 saniye)...")
    left_motors.backward(speed=MOVE_SPEED)
    right_motors.backward(speed=MOVE_SPEED)
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    # DÜZELTME: Daha az güç gerektiren pivot dönüş mantığına geçildi.
    print("\n[TEST 3/4] Sola Dönüş (Pivot) Testi (2 saniye)...")
    print("--> Sadece SAĞ motorlar İLERİ çalışacak.")
    right_motors.forward(speed=TURN_SPEED)  # Sağ tekerlek ileri
    left_motors.stop()  # Sol tekerlek duruyor
    time.sleep(2)
    left_motors.stop();
    right_motors.stop()
    print("-> Durduruldu.")
    time.sleep(1)

    print("\n[TEST 4/4] Sağa Dönüş (Pivot) Testi (2 saniye)...")
    print("--> Sadece SOL motorlar İLERİ çalışacak.")
    left_motors.forward(speed=TURN_SPEED)  # Sol tekerlek ileri
    right_motors.stop()  # Sağ tekerlek duruyor
    time.sleep(2)
    left_motors.stop();
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
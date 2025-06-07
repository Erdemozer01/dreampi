from gpiozero import DistanceSensor
import time

# Ana betiğinizdeki pin tanımları
TRIG_PIN, ECHO_PIN = 23, 24
TRIG2_PIN, ECHO2_PIN = 20, 21

print("Sensör 1 (pin 23, 24) başlatılıyor...")
try:
    sensor1 = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN)
    print(">>> Sensör 1 başarıyla başlatıldı.")
except Exception as e:
    print(f"!!! HATA: Sensör 1 başlatılamadı: {e}")
    sensor1 = None

print("\nSensör 2 (pin 20, 21) başlatılıyor...")
try:
    sensor2 = DistanceSensor(echo=ECHO2_PIN, trigger=TRIG2_PIN)
    print(">>> Sensör 2 başarıyla başlatıldı.")
except Exception as e:
    print(f"!!! HATA: Sensör 2 başlatılamadı: {e}")
    sensor2 = None

print("\nÖlçüm döngüsü başlıyor (Durdurmak için Ctrl+C)...")
print("-" * 30)

try:
    while True:
        if sensor1:
            try:
                dist1 = sensor1.distance * 100
                print(f"Sensör 1 Mesafe: {dist1:.1f} cm")
            except Exception as e:
                print(f"!!! HATA: Sensör 1'den okunamadı: {e}")

        if sensor2:
            try:
                dist2 = sensor2.distance * 100
                print(f"Sensör 2 Mesafe: {dist2:.1f} cm")
            except Exception as e:
                print(f"!!! HATA: Sensör 2'den okunamadı: {e}")

        print("-" * 30)
        time.sleep(1)

except KeyboardInterrupt:
    print("\nTest kullanıcı tarafından durduruldu.")
finally:
    print("Temizlik yapılıyor.")
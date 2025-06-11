import time
from gpiozero import DistanceSensor

# LÜTFEN KENDİ BAĞLANTINIZA GÖRE BU PIN NUMARALARINI DOĞRULAYIN
TRIG_PIN = 23
ECHO_PIN = 24

print("Ultrasonik sensör testi başlatılıyor...")
print(f"TRIG pini: {TRIG_PIN}, ECHO pini: {ECHO_PIN}")

try:
    # Sensörü tanımla
    # queue_len, sensörün daha stabil okumalar yapması için birkaç ölçümün ortalamasını almasını sağlar.
    sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, queue_len=5)
    print("Sensör başarıyla başlatıldı. 5 saniye içinde ölçüm başlayacak...")
    time.sleep(5)

    while True:
        # Mesafeyi santimetre cinsinden al ve yazdır
        distance_cm = sensor.distance * 100
        print(f"Mesafe: {distance_cm:.2f} cm")
        time.sleep(1)

except Exception as e:
    print(f"Bir hata oluştu: {e}")

finally:
    print("Test sonlandırıldı.")
# ultrasonic_test.py

import time
from gpiozero import DistanceSensor

# Lütfen pinlerin doğru olduğundan emin olun
TRIG_PIN_1, ECHO_PIN_1 = 23, 24
TRIG_PIN_2, ECHO_PIN_2 = 17, 27

print(">>> Ultrasonik Sensör Testi Başlatılıyor...")
print(">>> Çıkmak için CTRL+C tuşlarına basın.")

try:
    # Sensör nesnelerini oluştur
    sensor1 = DistanceSensor(echo=ECHO_PIN_1, trigger=TRIG_PIN_1)
    sensor2 = DistanceSensor(echo=ECHO_PIN_2, trigger=TRIG_PIN_2)

    while True:
        # Her iki sensörden de mesafeyi oku ve cm cinsinden ekrana yazdır
        dist1_cm = sensor1.distance * 100
        dist2_cm = sensor2.distance * 100

        print(f"Sensör 1: {dist1_cm:.1f} cm  |  Sensör 2: {dist2_cm:.1f} cm")

        # Her saniye başı ölçüm yap
        time.sleep(1)

except KeyboardInterrupt:
    print("\n>>> Test kullanıcı tarafından sonlandırıldı.")
except Exception as e:
    print(f"\n!!! TEST SIRASINDA HATA: {e}")

finally:
    print(">>> Kaynaklar serbest bırakılıyor.")
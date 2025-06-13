# test_sensor.py
# Yalnızca bir ultrasonik sensörün (HC-SR04) çalışıp çalışmadığını test etmek için
# basit bir script.

import time
from gpiozero import DistanceSensor
from gpiozero.exc import DistanceSensorNoEcho

# --- AYARLAR ---
# Test etmek istediğiniz sensörün TRIG ve ECHO pinlerini buraya girin.
#
# Sensör 1 için pinler (orijinal kodunuza göre):
#TRIG_PIN = 23
#ECHO_PIN = 24
#
# Sensör 2'yi test etmek isterseniz, bu satırları kullanın:
TRIG_PIN = 17
ECHO_PIN = 18
# -----------------

print(f"Ultrasonik Sensör Test Script'i Başlatıldı.")
print(f"Kullanılan pinler: TRIG={TRIG_PIN}, ECHO={ECHO_PIN}")
print("Mesafe ölçülüyor... Durdurmak için CTRL+C'ye basın.")
print("-" * 30)

# Sensör nesnesini oluştur
sensor = None
try:
    sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=3.0)

    # Sürekli olarak mesafeyi ölç ve ekrana yazdır
    while True:
        try:
            # .distance özelliği mesafeyi metre cinsinden verir, 100 ile çarparak cm'e çeviriyoruz.
            distance_in_cm = sensor.distance * 100
            print(f"Ölçülen Mesafe: {distance_in_cm:.2f} cm")

            # `gpiozero` kütüphanesi echo alamadığında bir uyarı verir ve .distance 
            # `max_distance` değerini döndürür. Bu durumu kullanıcıya bildirelim.
            if not sensor.is_active:
                print(">> UYARI: Sensör menzil dışında veya bir echo alamadı!")

        except DistanceSensorNoEcho:
            # Bu hatayı ayrıca yakalayarak daha net bir mesaj verebiliriz.
            print(">> HATA: Echo alınamadı! Kabloları ve sensörün önündeki engeli kontrol edin.")

        # Her ölçüm arasında 1 saniye bekle
        time.sleep(1)

except KeyboardInterrupt:
    # Kullanıcı CTRL+C'ye bastığında
    print("\nTest kullanıcı tarafından durduruldu.")

except Exception as e:
    # Diğer olası hatalar için (örn: pin meşgul)
    print(f"\nBeklenmedik bir hata oluştu: {e}")

finally:
    # Script ne şekilde sonlanırsa sonlansın kaynakları serbest bırak
    if sensor:
        sensor.close()
    print("GPIO kaynakları serbest bırakıldı. Program sonlandı.")
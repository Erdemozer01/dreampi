from gpiozero import Servo
from time import sleep

# Servo motorunuzun bağlı olduğu GPIO pini
SERVO_PIN = 12

def degree_to_servo_value(angle_deg):
    """0-180 dereceyi, gpiozero'nun -1 ile 1 aralığına çevirir."""
    # Değeri 0 ile 180 arasında sınırla
    clamped_angle = max(0, min(180, angle_deg))
    # -1.0 (0 derece) ile 1.0 (180 derece) arasına haritala
    return (clamped_angle / 90.0) - 1.0

# Servoyu başlat
try:
    my_servo = Servo(SERVO_PIN)
    print(f"Servo pini {SERVO_PIN} üzerinde başlatıldı.")
except Exception as e:
    print(f"HATA: Servo başlatılamadı: {e}")
    exit()

print("Servo artımlı hareket testi başlıyor...")
print("0'dan 180'e ve 180'den 0'a 10'ar derecelik adımlarla hareket edilecek.")
print("Durdurmak için Ctrl+C tuşlarına basın.")

try:
    # Başlangıç pozisyonu olarak ortaya git
    my_servo.value = degree_to_servo_value(90)
    sleep(2)

    while True:
        # 0'dan 180'e doğru hareket et
        print("\n--> YUKARI hareket (0 -> 180)")
        for angle in range(0, 181, 10): # 181, 180'in de dahil olmasını sağlar
            print(f"Hedef Açı: {angle}°")
            my_servo.value = degree_to_servo_value(angle)
            sleep(0.4) # Motorun pozisyon alması için kısa bir bekleme

        print("\n<-- GERİ hareket (180 -> 0)")
        # 180'den 0'a doğru hareket et
        for angle in range(180, -1, -10): # -1, 0'ın da dahil olmasını sağlar
            print(f"Hedef Açı: {angle}°")
            my_servo.value = degree_to_servo_value(angle)
            sleep(0.4)

except KeyboardInterrupt:
    print("\nTest kullanıcı tarafından durduruldu.")
finally:
    # Test bittiğinde veya durdurulduğunda motoru serbest bırak
    print("Servo serbest bırakılıyor.")
    my_servo.detach()
    print("Test tamamlandı.")
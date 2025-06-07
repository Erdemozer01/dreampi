from gpiozero import Servo
from time import sleep

# Ana betiğinizdeki pin ve fonksiyonun aynısı
SERVO_PIN = 12

def degree_to_servo_value(angle_deg):
    """0-180 dereceyi, gpiozero'nun -1 ile 1 aralığına çevirir."""
    clamped_angle = max(0, min(180, angle_deg))
    return (clamped_angle / 90.0) - 1.0

# Servo'yu başlat
my_servo = Servo(SERVO_PIN)

print("Servo motor testi başlıyor... (Durdurmak için Ctrl+C)")
print("Servo, 0 -> 90 -> 180 derece pozisyonlarını deneyecek.")

try:
    while True:
        # 0 dereceye git (en bir uç)
        print("Hedef: 0 derece")
        my_servo.value = degree_to_servo_value(0)
        sleep(3) # 3 saniye bekle

        # 90 dereceye git (orta nokta)
        print("Hedef: 90 derece")
        my_servo.value = degree_to_servo_value(90)
        sleep(3) # 3 saniye bekle

        # 180 dereceye git (diğer en uç nokta)
        print("Hedef: 180 derece")
        my_servo.value = degree_to_servo_value(180)
        sleep(3) # 3 saniye bekle

except KeyboardInterrupt:
    print("\nTest durduruldu. Servo serbest bırakılıyor.")
    my_servo.detach()
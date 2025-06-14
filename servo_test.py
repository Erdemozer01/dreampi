# test_servo.py
import time
from gpiozero import Servo
from gpiozero.pins.pigpio import PiGPIOFactory

# pigpio kullanmak servo titremesini (jitter) azaltır
factory = PiGPIOFactory()

# Servo'nun SİNYAL kablosunun bağlı olduğu GPIO pinini yazın (BCM numarası)
# Örneğin, GPIO 17 için:
servo = Servo(4, pin_factory=factory)

try:
    print("Servo minimum pozisyonda.")
    servo.min()
    time.sleep(2)

    print("Servo orta pozisyonda.")
    servo.mid()
    time.sleep(2)

    print("Servo maksimum pozisyonda.")
    servo.max()
    time.sleep(2)

    print("Test tamamlandı. Servo serbest bırakılıyor.")
    servo.detach()

except Exception as e:
    print(f"Bir hata oluştu: {e}")
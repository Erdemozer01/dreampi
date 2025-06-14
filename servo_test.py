# servo_test.py (Raspberry Pi 5 için Modern Versiyon)
import time
from gpiozero import Servo
# PiGPIOFactory artık kullanılmıyor, çünkü gpiozero doğru olanı seçecek.

# Servo'nun SİNYAL kablosunun bağlı olduğu GPIO pinini yazın (BCM numarası)
servo_pin_numarasi = 4

# Bu satır, gpiozero'nun Pi 5 için en uygun kütüphaneyi (lgpio)
# otomatik olarak seçmesini sağlar.
servo = Servo(servo_pin_numarasi)

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

    print("Test tamamlandı.")

except Exception as e:
    print(f"Bir hata oluştu: {e}")
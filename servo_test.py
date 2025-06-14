# servo_test.py (RPi.GPIO versiyonu)
import RPi.GPIO as GPIO
import time

# Servo'nun SİNYAL kablosunun bağlı olduğu GPIO pinini yazın (BCM numarası)
servo_pin = 17

# Pin numaralandırma modunu ayarla (BCM: GPIO numaraları, BOARD: Fiziksel pin numaraları)
GPIO.setmode(GPIO.BCM)

# Pini çıkış olarak ayarla
GPIO.setup(servo_pin, GPIO.OUT)

# PWM sinyalini 50Hz'de başlat
p = GPIO.PWM(servo_pin, 50)
p.start(0) # Başlangıçta sinyal yok

def set_angle(angle):
    # Açıyı 0-180 arası bir değere göre %2 ile %12 arasında bir duty cycle'a çevirir
    duty = angle / 18 + 2
    GPIO.output(servo_pin, True)
    p.ChangeDutyCycle(duty)
    time.sleep(1) # Servonun pozisyon alması için bekle
    GPIO.output(servo_pin, False)
    p.ChangeDutyCycle(0)

try:
    print("Servo 0 derece pozisyonunda.")
    set_angle(0)
    time.sleep(1)

    print("Servo 90 derece pozisyonunda.")
    set_angle(90)
    time.sleep(1)

    print("Servo 180 derece pozisyonunda.")
    set_angle(180)
    time.sleep(1)

    print("Test tamamlandı.")

except KeyboardInterrupt:
    print("Program durduruldu.")
finally:
    # Program sonlandığında temizlik yap
    p.stop()
    GPIO.cleanup()
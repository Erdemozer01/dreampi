import RPi.GPIO as GPIO
import time

LED_PIN = 17 # GPIO pin numarası

GPIO.setmode(GPIO.BCM) # Pin numaralandırma modunu BCM olarak ayarla
GPIO.setup(LED_PIN, GPIO.OUT) # Pini çıkış olarak ayarla

try:
    while True:
        GPIO.output(LED_PIN, GPIO.HIGH) # LED'i yak
        print("LED Açık")
        time.sleep(1)
        GPIO.output(LED_PIN, GPIO.LOW)  # LED'i söndür
        print("LED Kapalı")
        time.sleep(1)

except KeyboardInterrupt:
    print("Program Durduruldu")
finally:
    GPIO.cleanup() # GPIO ayarlarını sıfırla
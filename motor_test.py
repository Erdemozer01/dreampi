# motor_test.py - Tüm karmaşadan arındırılmış basit motor test betiği

import time
from gpiozero import OutputDevice

# Lütfen bu pin numaralarının motor sürücünüze bağlı olan
# GPIO pinleri ile aynı olduğundan emin olun.
MOTOR_IN1 = 26
MOTOR_IN2 = 19
MOTOR_IN3 = 13
MOTOR_IN4 = 6

# Motorun bir tam turu için gereken adım sayısı (28BYJ-48 için genellikle 4096'dır)
# Hızlı bir test için daha düşük bir değer kullanabiliriz.
STEPS_PER_REVOLUTION = 4096
# Testin daha hızlı olması için sadece çeyrek tur attıracağız
STEPS_TO_RUN = int(STEPS_PER_REVOLUTION / 4)

# Adım gecikmesi - motorun adım atması için gereken süre
# Çok düşük olursa motor titrer, çok yüksek olursa yavaş döner.
STEP_DELAY = 0.0015

print(">>> Basit Motor Testi Başlatılıyor...")
print(f">>> Pinler: IN1={MOTOR_IN1}, IN2={MOTOR_IN2}, IN3={MOTOR_IN3}, IN4={MOTOR_IN4}")
print(f">>> Motor {STEPS_TO_RUN} adım (çeyrek tur) saat yönünde dönecek...")

try:
    # GPIO pinlerini çıkış olarak ayarla
    in1 = OutputDevice(MOTOR_IN1)
    in2 = OutputDevice(MOTOR_IN2)
    in3 = OutputDevice(MOTOR_IN3)
    in4 = OutputDevice(MOTOR_IN4)
    motor_pins = [in1, in2, in3, in4]

    # 8 adımlık step motor sekansı
    step_sequence = [
        [1, 0, 0, 1],
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1]
    ]

    # Motoru belirtilen adım kadar döndür
    for i in range(STEPS_TO_RUN):
        for step in range(8):
            # Mevcut adımdaki pin durumlarını ayarla
            for pin_index in range(4):
                motor_pins[pin_index].value = step_sequence[step][pin_index]
            time.sleep(STEP_DELAY)

    print(">>> Test tamamlandı.")

except Exception as e:
    print(f"!!! TEST SIRASINDA KRİTİK BİR HATA OLUŞTU: {e}")

finally:
    # Program bittiğinde veya hata verdiğinde tüm pinleri kapat
    print(">>> Motor pinleri kapatılıyor...")
    try:
        in1.off()
        in2.off()
        in3.off()
        in4.off()
    except:
        pass

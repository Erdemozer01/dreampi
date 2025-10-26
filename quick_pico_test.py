"""
Minimal Pico test - sadece seri iletişim
TMC2209 olmadan da çalışır
"""

import sys
import uselect
import utime
from machine import Pin

# LED
try:
    led = Pin("LED", Pin.OUT)
    led.on()
except:
    try:
        led = Pin(25, Pin.OUT)
        led.on()
    except:
        led = None

# Başlatma mesajı
print("\n" + "=" * 60)
print("PICO MINIMAL TEST")
print("=" * 60)
print("Pico (Kas) Hazir")
print("Komut bekleniyor...\n")

# LED yanıp sönsün
if led:
    for _ in range(3):
        led.off()
        utime.sleep_ms(100)
        led.on()
        utime.sleep_ms(100)

# Poll objesi
spoll = uselect.poll()
spoll.register(sys.stdin, uselect.POLLIN)

command_count = 0

# Ana döngü
while True:
    try:
        # Komut kontrol
        if spoll.poll(0):
            line = sys.stdin.readline()

            if not line:
                utime.sleep_ms(5)
                continue

            cmd = line.strip()

            if not cmd:
                continue

            command_count += 1

            if led:
                led.off()

            # ACK gönder
            print("ACK")

            # Komut işle (basit)
            if cmd == "STOP_DRIVE" or cmd == "STOP_ALL":
                print("DONE")
            elif cmd.startswith("FORWARD:") or cmd.startswith("BACKWARD:"):
                duration = int(cmd.split(":")[1])
                # Simüle et
                utime.sleep_ms(min(duration, 100))
                print("DONE")
            elif cmd.startswith("TURN_"):
                duration = int(cmd.split(":")[1])
                utime.sleep_ms(min(duration, 100))
                print("DONE")
            elif cmd.startswith("SLIGHT_"):
                duration = int(cmd.split(":")[1])
                utime.sleep_ms(min(duration, 100))
                print("DONE")
            elif cmd.startswith("CONTINUOUS_"):
                print("DONE")
            else:
                print("ERR:BilinmeyenKomut")

            if led:
                led.on()

            # Her 10 komutta log
            if command_count % 10 == 0:
                print(f"# {command_count} komut islendi", file=sys.stderr)

        else:
            utime.sleep_ms(10)

    except KeyboardInterrupt:
        print("Program sonlandi")
        break
    except Exception as e:
        print(f"ERR:{e}")
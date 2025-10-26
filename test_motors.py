#!/usr/bin/env python3
# test_motors.py - Tarama Motorlarını Ayrı Ayrı Test Et

import time
from gpiozero import OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Pi 5 için LGPIO
Device.pin_factory = LGPIOFactory()

print("=" * 60)
print("⚙️  MOTOR TEST PROGRAMI")
print("=" * 60)

# Pin numaraları (robot_config.json'dan)
H_PINS = [26, 19, 13, 6]  # Yatay motor
V_PINS = [21, 20, 16, 12]  # Dikey motor

# 28BYJ-48 step sequence
STEP_SEQUENCE = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]


def test_motor(name, pins, color="⚙️"):
    """Tek bir motoru test et"""
    print(f"\n{color} {name} MOTOR TESTİ")
    print(f"   Pinler: GPIO {pins}")
    print("-" * 60)

    try:
        # Motor pinlerini oluştur
        motor_pins = [OutputDevice(pin) for pin in pins]
        print("   ✓ Motor pinleri başarıyla oluşturuldu")

        # Test 1: Pin testi (her pin ayrı ayrı)
        print("\n   🔸 TEST 1: Pin Kontrolü")
        for i, pin in enumerate(motor_pins):
            print(f"      Pin {i + 1} (GPIO {pins[i]}): ", end="")
            pin.on()
            time.sleep(0.3)
            pin.off()
            print("✓")
            time.sleep(0.1)

        # Test 2: Step sequence
        print("\n   🔸 TEST 2: Step Sequence (10 adım)")
        for step in range(10):
            seq = STEP_SEQUENCE[step % len(STEP_SEQUENCE)]
            for i, pin in enumerate(motor_pins):
                pin.value = seq[i]
            print(f"      Adım {step + 1}/10", end="\r")
            time.sleep(0.05)
        print("\n      ✓ Tamamlandı")

        # Test 3: İleri dönüş (1 saniye)
        print("\n   🔸 TEST 3: İleri Dönüş (1 saniye)")
        print("      Motor dönüyor olmalı... ", end="")
        start_time = time.time()
        step_index = 0

        while time.time() - start_time < 1.0:
            seq = STEP_SEQUENCE[step_index % len(STEP_SEQUENCE)]
            for i, pin in enumerate(motor_pins):
                pin.value = seq[i]
            time.sleep(0.002)
            step_index += 1

        steps_done = step_index
        print(f"✓ ({steps_done} adım)")

        # Test 4: Geri dönüş (1 saniye)
        print("\n   🔸 TEST 4: Geri Dönüş (1 saniye)")
        print("      Motor ters dönüyor olmalı... ", end="")
        start_time = time.time()

        while time.time() - start_time < 1.0:
            seq = STEP_SEQUENCE[step_index % len(STEP_SEQUENCE)]
            for i, pin in enumerate(motor_pins):
                pin.value = seq[i]
            time.sleep(0.002)
            step_index -= 1

        print("✓")

        # Motorları durdur
        for pin in motor_pins:
            pin.off()

        print("\n   ✅ MOTOR TESTİ BAŞARILI!")
        print("      Motor dönüş sesini duydunuz mu?")

        # Cleanup
        for pin in motor_pins:
            pin.close()

        return True

    except Exception as e:
        print(f"\n   ❌ MOTOR TESTI BAŞARISIZ: {e}")
        print(f"      - Pin numaraları doğru mu?")
        print(f"      - Motor sürücü board bağlı mı?")
        print(f"      - 5V güç var mı?")
        return False


def interactive_motor_test(name, pins):
    """İnteraktif motor testi"""
    print(f"\n🎮 {name} MOTOR İNTERAKTİF TEST")
    print("-" * 60)

    try:
        motor_pins = [OutputDevice(pin) for pin in pins]
        step_index = 0

        print("\n   Komutlar:")
        print("   [F] İleri    [B] Geri    [Q] Çıkış")
        print("\n   Motor kontrolü aktif. Tuşlara basın:\n")

        import sys, tty, termios

        # Terminal modunu değiştir
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())

            while True:
                # Tek karakter oku
                char = sys.stdin.read(1).lower()

                if char == 'q':
                    break
                elif char == 'f':
                    # İleri 50 adım
                    print("   ⬆️  İleri...", end="\r")
                    for _ in range(50):
                        seq = STEP_SEQUENCE[step_index % len(STEP_SEQUENCE)]
                        for i, pin in enumerate(motor_pins):
                            pin.value = seq[i]
                        time.sleep(0.002)
                        step_index += 1

                elif char == 'b':
                    # Geri 50 adım
                    print("   ⬇️  Geri... ", end="\r")
                    for _ in range(50):
                        seq = STEP_SEQUENCE[step_index % len(STEP_SEQUENCE)]
                        for i, pin in enumerate(motor_pins):
                            pin.value = seq[i]
                        time.sleep(0.002)
                        step_index -= 1

        finally:
            # Terminal modunu eski haline getir
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

        # Motorları durdur
        for pin in motor_pins:
            pin.off()
            pin.close()

        print("\n   ✓ İnteraktif test tamamlandı")

    except Exception as e:
        print(f"\n   ❌ Hata: {e}")


def main():
    """Ana test fonksiyonu"""

    print("\nTest modu seçin:")
    print("1. Otomatik test (önerilen)")
    print("2. İnteraktif test (manuel kontrol)")

    try:
        choice = input("\nSeçim (1-2): ").strip()
    except:
        choice = "1"

    if choice == "2":
        # İnteraktif mod
        print("\n" + "=" * 60)
        interactive_motor_test("YATAY", H_PINS)
        time.sleep(1)
        interactive_motor_test("DİKEY", V_PINS)
    else:
        # Otomatik test
        print("\nOtomatik test başlıyor...\n")

        # 1. Yatay Motor
        h_result = test_motor("YATAY (Horizontal)", H_PINS, "🔴")
        time.sleep(2)

        # 2. Dikey Motor
        v_result = test_motor("DİKEY (Vertical)", V_PINS, "🔵")

        # Genel Sonuç
        print("\n" + "=" * 60)
        print("📊 GENEL SONUÇ")
        print("=" * 60)
        print(f"🔴 Yatay Motor: {'✅ ÇALIŞIYOR' if h_result else '❌ SORUNLU'}")
        print(f"🔵 Dikey Motor: {'✅ ÇALIŞIYOR' if v_result else '❌ SORUNLU'}")

        if not h_result:
            print("\n⚠️  YATAY MOTOR SORUNLU!")
            print("   Olası nedenler:")
            print("   1. Pin bağlantıları yanlış (GPIO 26,19,13,6)")
            print("   2. ULN2003 board bağlı değil")
            print("   3. 5V güç gelmiyor")
            print("   4. Motor bozuk")
            print("\n   Fiziksel kontroller:")
            print("   - Motor kasasına dokunduğunuzda titreşim var mı?")
            print("   - ULN2003 board'daki LED'ler yanıp sönüyor mu?")

        if not v_result:
            print("\n⚠️  DİKEY MOTOR SORUNLU!")
            print("   Olası nedenler:")
            print("   1. Pin bağlantıları yanlış (GPIO 21,20,16,12)")
            print("   2. ULN2003 board bağlı değil")
            print("   3. 5V güç gelmiyor")
            print("   4. Motor bozuk")

        if h_result and v_result:
            print("\n🎉 HER İKİ MOTOR DE ÇALIŞIYOR!")
            print("   Sorun yazılımda veya sensörlerde olabilir.")

        print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest iptal edildi (Ctrl+C)")
    except Exception as e:
        print(f"\n❌ Kritik Hata: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup
        try:
            Device.pin_factory.close()
        except:
            pass
#!/usr/bin/env python3
# test_sensors.py - Sensörleri Ayrı Ayrı Test Et

import time
from gpiozero import DistanceSensor, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Pi 5 için LGPIO
Device.pin_factory = LGPIOFactory()

print("=" * 60)
print("🔬 SENSÖR TEST PROGRAMI")
print("=" * 60)

# Pin numaraları (robot_config.json'dan)
H_TRIG = 23
H_ECHO = 24
V_TRIG = 17
V_ECHO = 27


def test_sensor(name, trig_pin, echo_pin, color="🔵"):
    """Tek bir sensörü test et"""
    print(f"\n{color} {name} SENSÖR TESTİ")
    print(f"   Trigger Pin: GPIO {trig_pin}")
    print(f"   Echo Pin: GPIO {echo_pin}")
    print("-" * 60)

    try:
        sensor = DistanceSensor(
            echo=echo_pin,
            trigger=trig_pin,
            max_distance=4,
            threshold_distance=0.3
        )

        print("   ✓ Sensör başarıyla oluşturuldu")
        print("   ⏱ 10 okuma yapılıyor...\n")

        readings = []
        errors = 0

        for i in range(10):
            try:
                distance = sensor.distance * 100  # cm'ye çevir
                readings.append(distance)

                # Görselleştirme
                if distance < 10:
                    status = "❌ ÇOK YAKIN"
                    bar = "█" * 1
                elif distance > 390:
                    status = "❌ ARALIK DIŞI"
                    bar = "░" * 20
                else:
                    status = "✓"
                    bar_len = min(20, int(distance / 20))
                    bar = "█" * bar_len + "░" * (20 - bar_len)

                print(f"   {i + 1:2d}. {distance:6.1f} cm  [{bar}] {status}")
                time.sleep(0.3)

            except Exception as e:
                print(f"   {i + 1:2d}. OKUMA HATASI: {e}")
                errors += 1
                time.sleep(0.3)

        # İstatistikler
        print("\n" + "-" * 60)
        if readings:
            avg = sum(readings) / len(readings)
            min_dist = min(readings)
            max_dist = max(readings)

            print(f"   📊 İSTATİSTİKLER:")
            print(f"      Ortalama: {avg:.1f} cm")
            print(f"      Min: {min_dist:.1f} cm")
            print(f"      Max: {max_dist:.1f} cm")
            print(f"      Başarılı: {len(readings)}/10")
            print(f"      Hata: {errors}/10")

            # Değerlendirme
            if errors > 5:
                print(f"\n   ❌ SONUÇ: SENSÖR ÇALIŞMIYOR!")
                print(f"      - Kabloları kontrol edin")
                print(f"      - Pin numaralarını doğrulayın")
                return False
            elif min_dist < 5 and max_dist > 300:
                print(f"\n   ⚠️  SONUÇ: SENSÖR KARARSIZ")
                print(f"      - Bağlantıları sıkılaştırın")
                print(f"      - Sensör önünde engel olmasın")
                return False
            elif 20 < avg < 200:
                print(f"\n   ✅ SONUÇ: SENSÖR ÇALIŞIYOR!")
                return True
            else:
                print(f"\n   ⚠️  SONUÇ: ŞÜPHELİ DEGERLER")
                print(f"      - Sensör önü açık mı kontrol edin")
                return False
        else:
            print(f"\n   ❌ SONUÇ: HİÇ OKUMA ALINAMADI!")
            return False

        sensor.close()

    except Exception as e:
        print(f"\n   ❌ SENSÖR BAŞLATILAMADI: {e}")
        print(f"      - Pin numaraları yanlış olabilir")
        print(f"      - Başka bir program pin kullanıyor olabilir")
        return False


def main():
    """Ana test fonksiyonu"""

    print("\nTest başlıyor...")
    print("Her sensörden 10 okuma yapılacak.\n")

    # 1. Yatay Sensör
    h_result = test_sensor("YATAY (Horizontal)", H_TRIG, H_ECHO, "🔴")
    time.sleep(1)

    # 2. Dikey Sensör
    v_result = test_sensor("DİKEY (Vertical)", V_TRIG, V_ECHO, "🔵")

    # Genel Sonuç
    print("\n" + "=" * 60)
    print("📊 GENEL SONUÇ")
    print("=" * 60)
    print(f"🔴 Yatay Sensör: {'✅ ÇALIŞIYOR' if h_result else '❌ SORUNLU'}")
    print(f"🔵 Dikey Sensör: {'✅ ÇALIŞIYOR' if v_result else '❌ SORUNLU'}")

    if not h_result:
        print("\n⚠️  YATAY SENSÖR SORUNLU!")
        print("   Olası nedenler:")
        print("   1. Pin bağlantıları yanlış (GPIO 23, 24)")
        print("   2. Sensör bozuk")
        print("   3. Kablo gevşek/kopuk")
        print("   4. 5V güç gelmiyor")

    if not v_result:
        print("\n⚠️  DİKEY SENSÖR SORUNLU!")
        print("   Olası nedenler:")
        print("   1. Pin bağlantıları yanlış (GPIO 17, 27)")
        print("   2. Sensör bozuk")
        print("   3. Kablo gevşek/kopuk")
        print("   4. 5V güç gelmiyor")

    if h_result and v_result:
        print("\n🎉 HER İKİ SENSÖR DE ÇALIŞIYOR!")
        print("   Sorun tarama motorlarında olabilir.")

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
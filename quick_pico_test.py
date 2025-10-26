#!/usr/bin/env python3
"""
Pico'nun main.py ile çalışıp çalışmadığını test et
"""

import serial
import time


def test_pico():
    print("🧪 Pico Test Başlatılıyor...")

    try:
        # Bağlan
        ser = serial.Serial('/dev/ttyACM0', 115200, timeout=3)
        print("✓ Port açıldı")

        # 3 saniye bekle (Pico'nun başlaması için)
        time.sleep(3)

        # Buffer'ı temizle
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print("\n📡 Pico'dan mesaj bekleniyor (10 saniye)...")
        start = time.time()

        while time.time() - start < 10:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"   📨 {line}")

                    if "Hazir" in line or "PICO" in line:
                        print("\n✅ BAŞARI! main.py çalışıyor!")

                        # Komut testi
                        print("\n🧪 Komut testi: STOP_DRIVE")
                        ser.write(b"STOP_DRIVE\n")
                        ser.flush()

                        time.sleep(0.5)

                        responses = []
                        while ser.in_waiting > 0:
                            resp = ser.readline().decode('utf-8', errors='ignore').strip()
                            if resp:
                                responses.append(resp)
                                print(f"   📨 {resp}")

                        if "ACK" in responses and "DONE" in responses:
                            print("\n✅ MÜKEMMEL! Protokol doğru çalışıyor!")
                            print("\n🚀 autonomous_drive_pi5.py'yi çalıştırabilirsiniz!")
                            return True
                        else:
                            print("\n⚠️ Protokol tam değil")
                            return False

        print("\n❌ Timeout: Pico yanıt vermiyor")
        print("\n🔧 Yapılacaklar:")
        print("   1. Pico'yu USB'den çıkarıp tekrar takın")
        print("   2. Thonny'de CTRL+D yapın (soft reset)")
        print("   3. main.py'nin Pico'da olduğunu doğrulayın")
        return False

    except Exception as e:
        print(f"\n❌ Hata: {e}")
        return False
    finally:
        try:
            ser.close()
        except:
            pass


if __name__ == "__main__":
    test_pico()
#!/usr/bin/env python3
"""
Pico bağlantı tanı aracı
Pico'nun yanıt verip vermediğini test eder
"""

import serial
import time
import sys

PICO_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200


def test_pico_connection():
    """Pico bağlantısını test et"""
    print("=" * 60)
    print("🔍 PICO BAĞLANTI TANI ARACI")
    print("=" * 60)

    try:
        print(f"\n1️⃣ Seri port açılıyor: {PICO_PORT}")
        ser = serial.Serial(PICO_PORT, BAUD_RATE, timeout=2)
        print("   ✓ Port açıldı")

        time.sleep(2)  # Pico'nun boot etmesini bekle

        print("\n2️⃣ Buffer temizleniyor...")
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print("   ✓ Buffer temiz")

        print("\n3️⃣ Pico'dan gelen mesajlar dinleniyor (30 saniye)...")
        print("   (Pico'yu manuel olarak RESET yapabilirsiniz)\n")

        start_time = time.time()
        messages_received = []

        while time.time() - start_time < 30:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"   📨 Pico: '{line}'")
                        messages_received.append(line)

                        if any(kw in line.lower() for kw in ["hazir", "pico", "motor", "ready"]):
                            print(f"\n   ✅ BAŞARI! Pico hazır mesajı alındı!")
                            break
                except Exception as e:
                    print(f"   ⚠️ Mesaj okuma hatası: {e}")

            time.sleep(0.1)

        if not messages_received:
            print("\n   ❌ SORUN: Pico'dan hiç mesaj alınamadı!")
            print("\n   Kontrol edilmesi gerekenler:")
            print("   1. Pico'nun doğru USB portuna bağlı olduğunu doğrulayın")
            print("   2. Pico'da main.py veya boot.py dosyasının olduğunu kontrol edin")
            print("   3. Pico'yu BOOTSEL tuşuna basarak yeniden başlatın")
            print("   4. Thonny IDE ile Pico'ya bağlanıp kodu çalıştırmayı deneyin")
        else:
            print(f"\n   ℹ️ Toplam {len(messages_received)} mesaj alındı")

        print("\n4️⃣ Test komutu gönderiliyor: STOP_DRIVE")
        ser.write(b"STOP_DRIVE\n")
        print("   ✓ Komut gönderildi")

        print("\n5️⃣ Yanıt bekleniyor (5 saniye)...")
        responses = []
        start_time = time.time()

        while time.time() - start_time < 5:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"   📨 Yanıt: '{line}'")
                        responses.append(line)

                        if line in ["ACK", "DONE"]:
                            print(f"   ✅ Geçerli yanıt alındı!")
                            if len(responses) >= 2:
                                break
                except Exception as e:
                    print(f"   ⚠️ Yanıt okuma hatası: {e}")

            time.sleep(0.1)

        if "ACK" in responses and "DONE" in responses:
            print("\n" + "=" * 60)
            print("✅ SONUÇ: Pico tamamen çalışıyor!")
            print("=" * 60)
        elif responses:
            print("\n" + "=" * 60)
            print("⚠️ SONUÇ: Pico yanıt veriyor ama protokol tam değil")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ SONUÇ: Pico komutlara yanıt vermiyor")
            print("=" * 60)

        ser.close()

    except serial.SerialException as e:
        print(f"\n❌ HATA: Seri port açılamadı: {e}")
        print("\nKontrol edilecekler:")
        print(f"  • ls -l {PICO_PORT} (dosya var mı?)")
        print(f"  • sudo usermod -a -G dialout $USER (izin var mı?)")
        print(f"  • lsusb (Pico USB'de görünüyor mu?)")

    except Exception as e:
        print(f"\n❌ Beklenmeyen hata: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_pico_connection()
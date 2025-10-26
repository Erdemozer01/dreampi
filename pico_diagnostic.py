#!/usr/bin/env python3
"""
Pico bağlantı tanı aracı
Pico'nun yanıt verip vermediğini test eder
"""

import serial
import time
import sys
import glob

PICO_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200


def find_serial_ports():
    """Mevcut serial portları bul"""
    ports = []
    for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*', '/dev/serial*']:
        ports.extend(glob.glob(pattern))
    return ports


def test_pico_connection():
    """Pico bağlantısını test et"""
    print("=" * 60)
    print("🔍 PICO BAĞLANTI TANI ARACI")
    print("=" * 60)

    # Önce portları listele
    print("\n📋 Mevcut serial portlar:")
    ports = find_serial_ports()
    if not ports:
        print("   ❌ Hiç serial port bulunamadı!")
        print("\n   Kontrol edin:")
        print("   • Pico USB'ye takılı mı?")
        print("   • USB kablosu veri taşıyor mu? (şarj kablosu olabilir)")
        print("   • 'lsusb' komutu ile USB cihazlarını kontrol edin")
        return

    for port in ports:
        print(f"   ✓ {port}")

    # Test için port seç
    test_port = PICO_PORT if PICO_PORT in ports else ports[0]
    print(f"\n🔌 Test edilen port: {test_port}")

    try:
        print(f"\n1️⃣ Seri port açılıyor...")
        ser = serial.Serial(test_port, BAUD_RATE, timeout=2)
        print("   ✓ Port açıldı")

        time.sleep(2)  # Pico'nun boot etmesini bekle

        print("\n2️⃣ Buffer temizleniyor...")
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print("   ✓ Buffer temiz")

        print("\n3️⃣ Pico'dan gelen mesajlar dinleniyor (30 saniye)...")
        print("   💡 İpucu: Pico'yu RESET yapın veya USB'yi çıkarıp takın\n")

        start_time = time.time()
        messages_received = []

        while time.time() - start_time < 30:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"   📨 Pico: '{line}'")
                        messages_received.append(line)

                        if any(kw in line.lower() for kw in ["hazir", "pico", "motor", "ready", "kas"]):
                            print(f"\n   ✅ BAŞARI! Pico hazır mesajı alındı!")
                            break
                except Exception as e:
                    print(f"   ⚠️ Mesaj okuma hatası: {e}")

            time.sleep(0.1)

        if not messages_received:
            print("\n   ❌ SORUN: Pico'dan hiç mesaj alınamadı!")
            print("\n   🔧 Yapılması gerekenler:")
            print("   1. Pico'nun LED'i yanıyor mu kontrol edin")
            print("   2. Thonny IDE ile Pico'ya bağlanmayı deneyin")
            print("   3. main.py dosyasının Pico'da olduğunu doğrulayın")
            print("   4. Pico'yu BOOTSEL tuşuna basarak resetleyin")
            print("   5. MicroPython firmware'in yüklü olduğunu kontrol edin")
        else:
            print(f"\n   ℹ️ Toplam {len(messages_received)} mesaj alındı")

        print("\n4️⃣ Test komutu gönderiliyor: STOP_DRIVE")
        ser.write(b"STOP_DRIVE\n")
        ser.flush()
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

        print("\n" + "=" * 60)
        if "ACK" in responses and "DONE" in responses:
            print("✅ SONUÇ: Pico tamamen çalışıyor!")
        elif responses:
            print("⚠️ SONUÇ: Pico yanıt veriyor ama protokol tam değil")
            print("   → main.py dosyasını Pico'ya yeniden yükleyin")
        else:
            print("❌ SONUÇ: Pico komutlara yanıt vermiyor")
            print("   → main.py dosyası Pico'da çalışmıyor")
        print("=" * 60)

        ser.close()

    except serial.SerialException as e:
        print(f"\n❌ HATA: Seri port açılamadı: {e}")
        print("\n🔧 Çözümler:")
        print(f"  1. sudo chmod 666 {test_port}")
        print(f"  2. sudo usermod -a -G dialout $USER (sonra logout/login)")
        print(f"  3. USB kablosunu değiştirin (veri kablosu olmalı)")

    except Exception as e:
        print(f"\n❌ Beklenmeyen hata: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_pico_connection()
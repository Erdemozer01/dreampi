import serial
import time

# Pico'nun bağlı olduğu portu bulun.
# Pi 5 terminaline 'ls /dev/tty*' yazarak bulabilirsiniz. Genellikle 'ttyACM0' olur.
PICO_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200  # Thonny'nin kullandığı varsayılan hız

try:
    # Pico'ya seri bağlantıyı aç
    pico = serial.Serial(PICO_PORT, BAUD_RATE, timeout=2)
    print(f"Pico'ya {PICO_PORT} portundan bağlanıldı.")
    time.sleep(2)  # Pico'nun resetlenip başlaması için 2 saniye bekle

    # Pico'dan gelen "Hazir" mesajını bekle
    # readline() fonksiyonu '\n' (yeni satır) karakterine kadar okur
    ready_message = pico.readline().decode().strip()
    if "Hazir" in ready_message:
        print(f"Pico Yanıtı: {ready_message}")
        print("Test komutları gönderiliyor...")
    else:
        print(f"Pico'dan beklenen 'Hazir' mesajı alınamadı. Alınan: {ready_message}")
        pico.close()
        exit()

except serial.SerialException as e:
    print(f"HATA: Pico'ya {PICO_PORT} portundan bağlanılamadı.")
    print(f"Detay: {e}")
    print("Pico'nun bağlı olduğundan ve doğru portu yazdığınızdan emin olun.")
    exit()


def gonder_ve_bekle(komut):
    """
    Pico'ya bir komut gönderir, komutun bittiğine dair
    'OK:' yanıtı gelene kadar bekler.
    """
    print(f"-> Beyin: '{komut}'")

    # Komutu '\n' karakteri ile bitirerek gönderiyoruz (Pico'daki readline için)
    pico.write(f"{komut}\n".encode('utf-8'))

    # Pico'dan 'OK:' ile başlayan yanıtı bekle
    response = pico.readline().decode().strip()

    if response.startswith("OK:"):
        print(f"<- Kas (Pico): {response}")
    else:
        print(f"<- Kas (Pico) HATA/Beklenmedik Yanıt: {response}")


# --- ANA KONTROL DÖNGÜSÜ ---
try:
    # 3200 adım = 1 tam tur (16 microstep ile)
    yarim_tur = 1600
    tam_tur = 3200

    gonder_ve_bekle(f"FWD {tam_tur}")
    time.sleep(0.5)

    gonder_ve_bekle(f"REV {tam_tur}")
    time.sleep(0.5)

    gonder_ve_bekle(f"RIGHT {yarim_tur}")  # Yarım tur sağa dön
    time.sleep(0.5)

    gonder_ve_bekle(f"LEFT {yarim_tur}")  # Yarım tur sola dön
    time.sleep(0.5)

    gonder_ve_bekle("STOP")  # Ekstra güvenlik
    print("Test tamamlandı.")

except KeyboardInterrupt:
    print("\nProgram durduruldu. Motorlar durduruluyor.")
    gonder_ve_bekle("STOP")  # Program kesilirse motorları durdur

except Exception as e:
    print(f"Beklenmedik bir hata oluştu: {e}")
    gonder_ve_bekle("STOP")  # Hata olursa motorları durdur

finally:
    # Bağlantıyı her zaman güvenle kapat
    pico.close()
    print("Pico bağlantısı kapatıldı.")
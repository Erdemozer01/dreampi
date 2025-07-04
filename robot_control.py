# FINAL RASPBERRY PI 5 CONTROL SCRIPT
# This version is stable and includes an auto-stop safety feature.

import sys
import tty
import termios
import serial
import time
import select

# --- AYARLAR (CONFIGURATION) ---
PICO_PORT = '/dev/ttyACM0'  # Hata alırsanız `ls /dev/ttyACM*` komutuyla kontrol edin
BAUD_RATE = 115200

# --- PICO BAĞLANTISI (PICO CONNECTION) ---
pico_serial = None
try:
    pico_serial = serial.Serial(PICO_PORT, BAUD_RATE, timeout=1)
    print(f"Pico'ya {PICO_PORT} portundan başarıyla bağlanıldı.")
    time.sleep(2)  # Pico'nun kendine gelmesi için kısa bir bekleme
except serial.SerialException as e:
    print(f"HATA: Pico'ya bağlanılamadı. {e}")
    exit()


# --- FONKSİYONLAR (FUNCTIONS) ---
def send_command(command):
    """Komutu Pico'ya gönderir."""
    if pico_serial and pico_serial.is_open:
        pico_serial.write(command.encode('utf-8'))


def get_key_press():
    """Terminalden ok tuşları dahil tek bir tuş basımını okur."""
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        char = sys.stdin.read(1)
        if char == '\x1b':  # Ok tuşları 3 karakterli bir kod gönderir, bu ilk karakterdir.
            sequence = sys.stdin.read(2)
            key_map = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return key_map.get(sequence)
        return char
    return None


# --- ANA PROGRAM (MAIN PROGRAM) ---
print("\n--- Robot Kontrol Paneli (Nihai Versiyon) ---")
print("   Hareket için ok tuşlarını kullanın (tuşu bırakınca durur).")
print("   Anında durmak için SPACEBAR tuşuna basın.")
print("   Çıkmak için 'q' tuşuna basın.")
print("----------------------------------------------\n")

# Orijinal terminal ayarlarını kaydet
old_settings = termios.tcgetattr(sys.stdin)

try:
    # Terminali anlık okuma moduna al (her tuş basımını anında yakalar)
    tty.setcbreak(sys.stdin.fileno())

    last_sent_command = None
    while True:
        key = get_key_press()

        current_command = None
        if key == 'up':
            current_command = 'F\n'  # İleri
        elif key == 'down':
            current_command = 'B\n'  # Geri
        elif key == 'left':
            current_command = 'L\n'  # Sola Dön
        elif key == 'right':
            current_command = 'R\n'  # Sağa Dön
        elif key == ' ':  # Boşluk tuşu
            current_command = 'S\n'  # Dur
        elif key == 'q':
            print("'q' tuşuna basıldı, çıkılıyor.")
            break
        else:
            # ÖNEMLİ GÜVENLİK ÖZELLİĞİ: Eğer hiçbir tuşa basılmıyorsa,
            # robota sürekli 'Dur' komutu gönderilir.
            # Bu, robotun siz tuşu bırakınca durmasını sağlar.
            if last_sent_command != 'S\n':
                current_command = 'S\n'

        # Aynı komutu sürekli göndermemek için kontrol et
        if current_command and current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        # İşlemciyi yormamak için kısa bir bekleme
        time.sleep(0.05)

finally:
    # Programdan çıkarken her zaman terminali eski haline getir ve robotu durdur
    print("Terminal ayarları geri yükleniyor ve DUR komutu gönderiliyor.")
    send_command('S\n')
    if pico_serial and pico_serial.is_open:
        pico_serial.close()
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
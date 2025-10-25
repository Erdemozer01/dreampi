# autonomous_drive_pi5.py - Pi 5 (Beyin) -> Pico (Kas) Sürümü
# Proaktif ve Akıllı Navigasyon Betiği (Seri Komut Kontrolü ile)

import os
import sys
import time
import logging
import atexit
import signal
import threading
import traceback
import math
import serial  # gpiozero yerine serial kütüphanesi eklendi

# --- TEMEL YAPILANDIRMA ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SABİTLER ---
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'
# Pico'nun bağlandığı seri port (Linux'ta genellikle ttyACM0 veya ttyACM1 olur)
PICO_SERIAL_PORT = '/dev/ttyACM0'
PICO_BAUD_RATE = 115200

# --- PARAMETRELER (Pico'daki kod bu süreleri uygular) ---
MOVE_DURATION_MS = 1000  # milisaniye
TURN_DURATION_MS = 500  # milisaniye
OBSTACLE_DISTANCE_CM = 35

# --- GLOBAL NESNELER ---
pico: serial.Serial = None  # Motor nesneleri yerine seri port nesnesi
stop_event = threading.Event()
# Pico'dan cevap beklerken kilitlenme yaşanmaması için bir kilit
pico_lock = threading.Lock()


# --- SÜREÇ, DONANIM VE HAREKET FONKSİYONLARI ---
def signal_handler(sig, frame): stop_event.set()


def create_pid_file():
    try:
        with open(AUTONOMOUS_SCRIPT_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def cleanup_on_exit():
    logging.info("Program sonlanıyor...");
    stop_event.set()
    try:
        if pico and pico.is_open:
            # Pico'ya tüm motorları durdurma komutu gönder
            send_command_to_pico("STOP_ALL")
            pico.close()
    except Exception as e:
        logging.error(f"Donanım durdurulurken hata: {e}")
    finally:
        if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE): os.remove(AUTONOMOUS_SCRIPT_PID_FILE)
        logging.info("Temizleme tamamlandı.")


def setup_hardware():
    global pico
    try:
        pico = serial.Serial(PICO_SERIAL_PORT, PICO_BAUD_RATE, timeout=2)
        time.sleep(2)  # Pico'nun yeniden başlaması için bekle
        pico.flushInput()
        logging.info(f"Pico'ya {PICO_SERIAL_PORT} üzerinden başarıyla bağlanıldı.")
    except serial.SerialException as e:
        logging.critical(f"KRİTİK HATA: Pico'ya bağlanılamadı: {e}")
        logging.critical("Pico'nun bağlı olduğundan ve doğru portun (örn: /dev/ttyACM0) seçildiğinden emin olun.")
        sys.exit(1)


def send_command_to_pico(command, wait_for_response=False):
    """
    Pico'ya kilitli (thread-safe) bir şekilde komut gönderir ve isteğe bağlı olarak yanıt bekler.
    """
    if stop_event.is_set() or not pico:
        return None

    with pico_lock:
        try:
            pico.write(f"{command}\n".encode('utf-8'))
            logging.debug(f"PICO_CMD_SEND: {command}")

            if wait_for_response:
                response = pico.readline().decode('utf-8').strip()
                logging.debug(f"PICO_CMD_RECV: {response}")
                if response.startswith("OK:"):
                    return response[3:]  # "OK:" prefix'ini kaldır
                elif response.startswith("ERR:"):
                    logging.error(f"Pico Hatası: {response[4:]}")
                    return None
                else:
                    return response  # Ham veri (örn: mesafe)
            return "OK"  # Yanıt beklemiyorsak

        except serial.SerialException as e:
            logging.error(f"Pico ile iletişim hatası: {e}")
            stop_event.set()  # İletişim koptuysa ana döngüyü durdur
            return None
        except Exception as e:
            logging.error(f"send_command_to_pico içinde beklenmedik hata: {e}")
            return None


# --- Hareket Fonksiyonları (Pico'ya Komut Gönderir) ---

def move_forward():
    logging.info(f"İleri Gidiliyor ({MOVE_DURATION_MS} ms)...");
    send_command_to_pico(f"FORWARD:{MOVE_DURATION_MS}")


def move_backward():
    logging.info(f"Geri Gidiliyor ({MOVE_DURATION_MS} ms)...");
    send_command_to_pico(f"BACKWARD:{MOVE_DURATION_MS}")


def turn_left():
    logging.info(f"Sola Dönülüyor ({TURN_DURATION_MS} ms)...");
    send_command_to_pico(f"TURN_LEFT:{TURN_DURATION_MS}")


def turn_right():
    logging.info(f"Sağa Dönülüyor ({TURN_DURATION_MS} ms)...");
    send_command_to_pico(f"TURN_RIGHT:{TURN_DURATION_MS}")


def stop_motors():
    logging.info("Tekerlek Motorları Durduruldu.");
    send_command_to_pico("STOP_DRIVE")  # Sadece sürüş motorlarını durdur


def stop_step_motors():
    # Pico'ya tarama motorlarını durdurma komutu gönderiyor
    send_command_to_pico("STOP_SCAN")


# --- Tarama Fonksiyonları (Pico'ya Komut Gönderir) ---

def move_step_motor_to_angle(motor_name, target_angle_deg):
    """
    Pico'ya hangi motoru hangi açıya getireceğini söyler.
    motor_name: 'FRONT' veya 'REAR'
    """
    command = f"SCAN_{motor_name}:{int(target_angle_deg)}"
    send_command_to_pico(command)


def get_distance_from_sensor():
    """
    Pico'dan mesafe okumasını ister.
    """
    response = send_command_to_pico("GET_DISTANCE", wait_for_response=True)
    try:
        # Pico "999.9" gibi bir float string gönderecek
        return float(response)
    except (ValueError, TypeError):
        logging.warning(f"Pico'dan geçersiz mesafe verisi alındı: '{response}'")
        return float('inf')  # Hata durumunda sonsuz mesafe varsay


def perform_front_scan():
    logging.info("Ön taraf taranıyor...")
    scan_angles = [90, 0, -90]
    measurements = {}
    for angle in scan_angles:
        if stop_event.is_set(): break
        move_step_motor_to_angle('FRONT', angle)
        time.sleep(0.3)  # Motorun açıya gelmesi ve sensörün stabilize olması için bekle
        distance = get_distance_from_sensor()
        measurements[angle] = distance
        logging.info(f"  Ön Tarama: Açı={angle}°, Mesafe={distance:.1f} cm")
    move_step_motor_to_angle('FRONT', 0)  # Tarama sonrası merkeze dön
    return measurements


def check_rear():
    logging.info("Arka taraf kontrol ediliyor ('Dikiz Aynası')...")
    move_step_motor_to_angle('REAR', 180)
    if stop_event.is_set(): return 0
    time.sleep(0.3)  # Motorun açıya gelmesi ve sensörün stabilize olması için bekle
    distance = get_distance_from_sensor()
    logging.info(f"  Arka Tarama: Mesafe={distance:.1f} cm")
    move_step_motor_to_angle('REAR', 0)
    return distance


# --- ANA MANTIK (Orijinal betikle aynı) ---

def analyze_and_decide(front_scan, rear_distance):
    logging.info("Tüm yönler analiz ediliyor...")
    all_options = {
        "TURN_RIGHT": front_scan.get(90, 0),
        "FORWARD": front_scan.get(0, 0),
        "TURN_LEFT": front_scan.get(-90, 0),
        "BACKWARD": rear_distance
    }
    logging.info(f"Tüm Yönler ve Mesafeler: {all_options}")
    safe_options = {direction: dist for direction, dist in all_options.items() if dist > OBSTACLE_DISTANCE_CM}
    if not safe_options:
        logging.warning("Tüm yönler kapalı veya engel mesafesinden yakın. Durulacak.")
        return "STOP"
    best_direction = max(safe_options, key=safe_options.get)
    logging.info(f"Karar: En uygun yol {best_direction} yönünde. Mesafe: {safe_options[best_direction]:.1f} cm")
    return best_direction


# --- ANA ÇALIŞMA DÖNGÜSÜ ---
def main():
    atexit.register(cleanup_on_exit);
    signal.signal(signal.SIGTERM, signal_handler);
    signal.signal(signal.SIGINT, signal_handler);
    create_pid_file()

    try:
        setup_hardware()  # Bu artık seri portu başlatıyor

        # Pico'nun donanımı kendi içinde başlatmasını bekle
        logging.info("Pico'nun başlatılması bekleniyor...")
        time.sleep(1)

        # Tarama motorlarını sıfırla
        move_step_motor_to_angle('REAR', 0)
        move_step_motor_to_angle('FRONT', 0)

        logging.info("Otonom sürüş modu başlatıldı...")

        while not stop_event.is_set():
            logging.info("\n--- YENİ DÖNGÜ: En Uygun Yolu Bul ve İlerle ---")
            stop_motors()
            stop_step_motors()

            front_scan_data = perform_front_scan()
            if stop_event.is_set(): break
            rear_distance = check_rear()
            if stop_event.is_set(): break

            stop_step_motors()  # Sadece tarama motorlarını durdur

            decision = analyze_and_decide(front_scan_data, rear_distance)

            if decision == "FORWARD":
                move_forward()
            elif decision == "BACKWARD":
                move_backward()
            elif decision == "TURN_LEFT":
                turn_left()
            elif decision == "TURN_RIGHT":
                turn_right()
            elif decision == "STOP":
                logging.error("SIKIŞTI! Hareket edecek güvenli bir yol yok. İşlem durduruluyor.")
                break

            time.sleep(1)  # Pi 5 tarafındaki ana döngü beklemesi

    except KeyboardInterrupt:
        print("\nProgram kullanıcı tarafından sonlandırıldı (CTRL+C).")
    except Exception as e:
        logging.error(f"KRİTİK BİR HATA OLUŞTU: {e}")
        traceback.print_exc()
    finally:
        logging.info("Ana döngüden çıkıldı.")


if __name__ == '__main__':
    main()

# autonomous_drive_pi5.py - Pi 5 (Beyin) -> Pico (Kas) Sürümü - İYİLEŞTİRİLMİŞ
# Proaktif ve Akıllı Navigasyon Betiği (Seri Komut Kontrolü ile)
#
# YENİ MİMARİ:
# BEYİN (Pi 5): 2x Tarama (28BYJ H+V) + 2x Sensör (HC-SR04 H+V) + Mantık.
# KAS (Pico): Sadece Sürüş (2x NEMA 17).

import os
import sys
import time
import logging
import atexit
import signal
import threading
import traceback
import statistics
import json
from pathlib import Path
import serial

from gpiozero import DistanceSensor, OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

try:
    from gpiozero.pins.pigpio import PiGPIOFactory
except ImportError:
    PiGPIOFactory = None

# Pi 5 için LGPIO kullan
try:
    Device.pin_factory = LGPIOFactory()
    logging.info("LGPIO pin factory (Pi 5) başarıyla ayarlandı.")
except Exception as e:
    logging.warning(f"LGPIO kullanılamadı: {e}")

# --- YAPILANDIRMA DOSYASI ---
CONFIG_FILE = '/home/pi/robot_config.json'
DEFAULT_CONFIG = {
    "autonomous_script_pid_file": "/tmp/autonomous_drive_script.pid",
    "pico_serial_port": "/dev/ttyACM0",
    "pico_baud_rate": 115200,
    "pico_response_timeout": 10.0,
    "h_pin_trig": 23,
    "h_pin_echo": 24,
    "v_pin_trig": 17,
    "v_pin_echo": 27,
    "horizontal_scan_motor_pins": [26, 19, 13, 6],
    "vertical_scan_motor_pins": [21, 20, 16, 12],
    "move_duration_ms": 1000,
    "turn_duration_ms": 500,
    "obstacle_distance_cm": 35,
    "steps_per_revolution": 4096,
    "step_motor_inter_step_delay": 0.002,
    "invert_rear_motor_direction": True,
    "scan_h_angle": 90.0,
    "scan_h_step": 30.0,
    "scan_v_angle": 30.0,
    "scan_v_step": 15.0,
    "sensor_readings_count": 3,
    "min_loop_duration": 2.0,
    "motor_settle_time": 0.3,
    "scan_settle_time": 0.05
}

# --- LOGLAMA ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/pi/autonomous_drive.log')
    ]
)


# --- KONFİGÜRASYON YÖNETİMİ ---
def load_config():
    """Konfigürasyon dosyasını yükler veya varsayılanı oluşturur."""
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                logging.info(f"Konfigürasyon {CONFIG_FILE} dosyasından yüklendi.")
                return config
        except Exception as e:
            logging.error(f"Konfigürasyon yüklenemedi: {e}")

    # Varsayılan konfigürasyon oluştur
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        logging.info(f"Varsayılan konfigürasyon {CONFIG_FILE} dosyasına kaydedildi.")
    except Exception as e:
        logging.warning(f"Konfigürasyon dosyası oluşturulamadı: {e}")

    return DEFAULT_CONFIG


# Konfigürasyonu yükle
CONFIG = load_config()

# --- GLOBAL DEĞİŞKENLER ---
pico: serial.Serial = None
h_sensor: DistanceSensor = None
v_sensor: DistanceSensor = None
stop_event = threading.Event()
pico_lock = threading.Lock()

vertical_scan_motor_devices: tuple = None
horizontal_scan_motor_devices: tuple = None
vertical_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
horizontal_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}

step_sequence = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]

# İstatistikler
stats = {
    'total_scans': 0,
    'forward_moves': 0,
    'backward_moves': 0,
    'left_turns': 0,
    'right_turns': 0,
    'errors': 0,
    'start_time': time.time()
}


# --- SİNYAL YÖNETİMİ ---
def signal_handler(sig, frame):
    logging.info(f"Sinyal alındı: {sig}")
    stop_event.set()


def create_pid_file():
    try:
        with open(CONFIG['autonomous_script_pid_file'], 'w') as f:
            f.write(str(os.getpid()))
        logging.info(f"PID dosyası oluşturuldu: {os.getpid()}")
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def cleanup_on_exit():
    """Temizleme işlemleri."""
    logging.info("Temizleme başlatılıyor...")
    stop_event.set()

    # İstatistikleri yazdır
    runtime = time.time() - stats['start_time']
    logging.info(f"""
    === ÇALIŞMA İSTATİSTİKLERİ ===
    Çalışma Süresi: {runtime:.1f} saniye
    Toplam Tarama: {stats['total_scans']}
    İleri Hareket: {stats['forward_moves']}
    Geri Hareket: {stats['backward_moves']}
    Sola Dönüş: {stats['left_turns']}
    Sağa Dönüş: {stats['right_turns']}
    Hata Sayısı: {stats['errors']}
    =============================""")

    try:
        if h_sensor:
            h_sensor.close()
            logging.info("Yatay sensör kapatıldı.")
        if v_sensor:
            v_sensor.close()
            logging.info("Dikey sensör kapatıldı.")

        stop_step_motors_local()
        logging.info("Tarama motorları durduruldu.")

        # Motor pinlerini temizle
        if vertical_scan_motor_devices:
            for pin in vertical_scan_motor_devices:
                try:
                    pin.close()
                except:
                    pass

        if horizontal_scan_motor_devices:
            for pin in horizontal_scan_motor_devices:
                try:
                    pin.close()
                except:
                    pass

        logging.info("Motor pinleri temizlendi.")

        if pico and pico.is_open:
            try:
                pico.write(b"STOP_ALL\n")
                time.sleep(0.1)
                pico.close()
                logging.info("Pico bağlantısı kapatıldı.")
            except:
                pass
    except Exception as e:
        logging.error(f"Donanım durdurulurken hata: {e}")
    finally:
        # Pin factory'yi temizle
        try:
            if Device.pin_factory:
                Device.pin_factory.close()
                logging.info("Pin factory kapatıldı.")
        except:
            pass

        pid_file = CONFIG['autonomous_script_pid_file']
        if os.path.exists(pid_file):
            os.remove(pid_file)
            logging.info("PID dosyası silindi.")
        logging.info("Temizleme tamamlandı.")


# --- DONANIM BAŞLATMA ---
def setup_hardware():
    """Tüm donanımı başlatır."""
    global pico, h_sensor, v_sensor
    global vertical_scan_motor_devices, horizontal_scan_motor_devices

    try:
        # 1. PICO BAĞLANTISI
        logging.info(f"Pico'ya bağlanılıyor: {CONFIG['pico_serial_port']}")
        pico = serial.Serial(
            CONFIG['pico_serial_port'],
            CONFIG['pico_baud_rate'],
            timeout=CONFIG['pico_response_timeout']
        )
        time.sleep(2)  # Pico'nun başlaması için
        pico.reset_input_buffer()
        pico.reset_output_buffer()

        # Pico'dan "Hazir" mesajı bekle (timeout ile)
        logging.info("Pico'nun 'Hazir' mesajı bekleniyor...")
        start_wait = time.time()
        ready_received = False

        while time.time() - start_wait < 15:
            if pico.in_waiting > 0:
                try:
                    response = pico.readline().decode('utf-8', errors='ignore').strip()
                    logging.info(f"Pico'dan mesaj: '{response}'")
                    # Farklı mesaj formatlarını kontrol et
                    if "Hazir" in response or "PICO" in response or "MOTOR" in response or "hazir" in response.lower():
                        ready_received = True
                        break
                except Exception as e:
                    logging.warning(f"Mesaj okuma hatası: {e}")
            time.sleep(0.1)

        if not ready_received:
            logging.warning("⚠️ Pico 'Hazir' mesajı göndermedi, ancak devam ediliyor...")
            logging.warning("   Pico zaten çalışıyor olabilir. Test ediliyor...")
            # Test komutu gönder
            try:
                pico.write(b"STOP_DRIVE\n")
                time.sleep(0.5)
                if pico.in_waiting > 0:
                    response = pico.readline().decode('utf-8', errors='ignore').strip()
                    logging.info(f"   Test yanıtı: '{response}'")
                    if response in ["ACK", "DONE", "OK"]:
                        logging.info("   ✓ Pico çalışıyor!")
                        ready_received = True
            except:
                pass

        if not ready_received:
            logging.error("❌ Pico ile iletişim kurulamadı!")
            raise Exception("Pico başlatılamadı")

        logging.info("✓ Pico başarıyla bağlandı.")

        # 2. SENSÖRLER
        logging.info(f"Yatay Sensör başlatılıyor (Trig:{CONFIG['h_pin_trig']}, Echo:{CONFIG['h_pin_echo']})")
        h_sensor = DistanceSensor(
            echo=CONFIG['h_pin_echo'],
            trigger=CONFIG['h_pin_trig'],
            max_distance=4,
            threshold_distance=0.3
        )
        logging.info("✓ Yatay Sensör hazır.")

        logging.info(f"Dikey Sensör başlatılıyor (Trig:{CONFIG['v_pin_trig']}, Echo:{CONFIG['v_pin_echo']})")
        v_sensor = DistanceSensor(
            echo=CONFIG['v_pin_echo'],
            trigger=CONFIG['v_pin_trig'],
            max_distance=4,
            threshold_distance=0.3
        )
        logging.info("✓ Dikey Sensör hazır.")

        # 3. TARAMA MOTORLARI
        logging.info("Tarama motorları başlatılıyor...")
        v_pins = CONFIG['vertical_scan_motor_pins']
        vertical_scan_motor_devices = (
            OutputDevice(v_pins[0]), OutputDevice(v_pins[1]),
            OutputDevice(v_pins[2]), OutputDevice(v_pins[3])
        )

        h_pins = CONFIG['horizontal_scan_motor_pins']
        horizontal_scan_motor_devices = (
            OutputDevice(h_pins[0]), OutputDevice(h_pins[1]),
            OutputDevice(h_pins[2]), OutputDevice(h_pins[3])
        )
        logging.info("✓ Tarama motorları hazır.")

        logging.info("=== TÜM DONANIM BAŞARILI ŞEKİLDE BAŞLATILDI ===")

    except Exception as e:
        logging.critical(f"KRİTİK HATA: Donanım başlatılamadı: {e}")
        traceback.print_exc()
        sys.exit(1)


# --- PICO İLETİŞİMİ (İYİLEŞTİRİLMİŞ) ---
def send_command_to_pico(command):
    """
    Pico'ya komut gönderir ve ACK+DONE yanıtı bekler.
    Returns: True if successful, False otherwise
    """
    if stop_event.is_set() or not pico or not pico.is_open:
        return False

    with pico_lock:
        try:
            pico.reset_input_buffer()
            pico.reset_output_buffer()

            # Komutu gönder
            pico.write(f"{command}\n".encode('utf-8'))
            logging.debug(f"→ PICO: {command}")

            # ACK bekle (anında dönmeli)
            ack = pico.readline().decode('utf-8').strip()
            logging.debug(f"← PICO: {ack}")

            if ack != "ACK":
                logging.error(f"Pico'dan ACK yerine '{ack}' alındı")
                return False

            # DONE bekle (motor hareketi bitince)
            done = pico.readline().decode('utf-8').strip()
            logging.debug(f"← PICO: {done}")

            if done != "DONE":
                logging.error(f"Pico'dan DONE yerine '{done}' alındı")
                return False

            return True

        except serial.SerialTimeoutException:
            logging.error("Pico timeout - yanıt alınamadı")
            stats['errors'] += 1
            return False
        except Exception as e:
            logging.error(f"Pico iletişim hatası: {e}")
            stats['errors'] += 1
            return False


# --- HAREKET FONKSİYONLARI ---
def move_forward():
    logging.info(f"→ İLERİ ({CONFIG['move_duration_ms']} ms)")
    if send_command_to_pico(f"FORWARD:{CONFIG['move_duration_ms']}"):
        stats['forward_moves'] += 1
        return True
    return False


def move_backward():
    logging.info(f"← GERİ ({CONFIG['move_duration_ms']} ms)")
    if send_command_to_pico(f"BACKWARD:{CONFIG['move_duration_ms']}"):
        stats['backward_moves'] += 1
        return True
    return False


def turn_left():
    logging.info(f"↶ SOLA ({CONFIG['turn_duration_ms']} ms)")
    if send_command_to_pico(f"TURN_LEFT:{CONFIG['turn_duration_ms']}"):
        stats['left_turns'] += 1
        return True
    return False


def turn_right():
    logging.info(f"↷ SAĞA ({CONFIG['turn_duration_ms']} ms)")
    if send_command_to_pico(f"TURN_RIGHT:{CONFIG['turn_duration_ms']}"):
        stats['right_turns'] += 1
        return True
    return False


def stop_motors():
    logging.info("⏹ MOTORLAR DURDUR")
    return send_command_to_pico("STOP_DRIVE")


# --- TARAMA MOTOR FONKSİYONLARI ---
def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    """Motor pinlerini ayarlar."""
    motor_devices[0].value = bool(s1)
    motor_devices[1].value = bool(s2)
    motor_devices[2].value = bool(s3)
    motor_devices[3].value = bool(s4)


def _step_motor_local(motor_devices, motor_ctx, num_steps, direction_positive, invert_direction=False):
    """Motor adımlarını yürütür."""
    step_increment = 1 if direction_positive else -1
    if invert_direction:
        step_increment *= -1

    for _ in range(int(num_steps)):
        if stop_event.is_set():
            break
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']])
        time.sleep(CONFIG['step_motor_inter_step_delay'])


def move_step_motor_to_angle_local(motor_devices, motor_ctx, target_angle_deg, invert_direction=False):
    """Motoru belirli açıya getirir."""
    deg_per_step = 360.0 / CONFIG['steps_per_revolution']
    angle_diff = target_angle_deg - motor_ctx['current_angle']

    if abs(angle_diff) < deg_per_step:
        return

    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor_local(motor_devices, motor_ctx, num_steps, (angle_diff > 0), invert_direction)

    if not stop_event.is_set():
        motor_ctx['current_angle'] = target_angle_deg


def stop_step_motors_local():
    """Tüm tarama motorlarını durdurur."""
    if vertical_scan_motor_devices:
        _set_motor_pins(vertical_scan_motor_devices, 0, 0, 0, 0)
    if horizontal_scan_motor_devices:
        _set_motor_pins(horizontal_scan_motor_devices, 0, 0, 0, 0)


# --- SENSÖR OKUMA (İYİLEŞTİRİLMİŞ) ---
def get_distance_from_sensors():
    """
    Her iki sensörden de okuma yapar ve güvenilir sonuç döner.
    Birden fazla okuma alıp medyan hesaplar.
    """
    readings_h = []
    readings_v = []

    for _ in range(CONFIG['sensor_readings_count']):
        if stop_event.is_set():
            break

        # Yatay sensör
        try:
            dist_h = h_sensor.distance * 100
            if 2 < dist_h < 398:
                readings_h.append(dist_h)
        except Exception as e:
            logging.debug(f"H-Sensör okuma hatası: {e}")

        # Dikey sensör
        try:
            dist_v = v_sensor.distance * 100
            if 2 < dist_v < 398:
                readings_v.append(dist_v)
        except Exception as e:
            logging.debug(f"V-Sensör okuma hatası: {e}")

        time.sleep(0.01)

    # Medyan hesapla
    dist_h_median = statistics.median(readings_h) if readings_h else float('inf')
    dist_v_median = statistics.median(readings_v) if readings_v else float('inf')

    # En yakın engeli dön
    return min(dist_h_median, dist_v_median)


# --- 3D TARAMA (İYİLEŞTİRİLMİŞ) ---
def find_best_path():
    """
    3D tarama yapar ve en açık yolu bulur.
    Returns: (best_h_angle, max_distance)
    """
    logging.info("🔍 3D TARAMA BAŞLATILIYOR...")
    stats['total_scans'] += 1

    max_distance_found = 0.0
    best_h_angle = 0.0

    h_scan_angle = CONFIG['scan_h_angle']
    h_step = CONFIG['scan_h_step']
    v_scan_angle = CONFIG['scan_v_angle']
    v_step = CONFIG['scan_v_step']

    h_initial_angle = -h_scan_angle / 2.0
    v_initial_angle = 0.0

    num_h_steps = int(h_scan_angle / h_step) if h_step > 0 else 0
    num_v_steps = int(v_scan_angle / v_step) if v_step > 0 else 0

    # Başlangıç pozisyonuna git
    move_step_motor_to_angle_local(
        horizontal_scan_motor_devices,
        horizontal_scan_motor_ctx,
        h_initial_angle
    )
    move_step_motor_to_angle_local(
        vertical_scan_motor_devices,
        vertical_scan_motor_ctx,
        v_initial_angle,
        CONFIG['invert_rear_motor_direction']
    )
    time.sleep(CONFIG['motor_settle_time'])

    # Tarama yap
    scan_points = []

    for i in range(num_h_steps + 1):
        if stop_event.is_set():
            break

        target_h_angle = h_initial_angle + (i * h_step)
        move_step_motor_to_angle_local(
            horizontal_scan_motor_devices,
            horizontal_scan_motor_ctx,
            target_h_angle
        )

        for j in range(num_v_steps + 1):
            if stop_event.is_set():
                break

            # Ping-pong tarama
            if i % 2 == 0:
                target_v_angle = v_initial_angle + (j * v_step)
            else:
                target_v_angle = v_scan_angle - (j * v_step)

            move_step_motor_to_angle_local(
                vertical_scan_motor_devices,
                vertical_scan_motor_ctx,
                target_v_angle,
                CONFIG['invert_rear_motor_direction']
            )

            time.sleep(CONFIG['scan_settle_time'])

            # Mesafe oku
            distance = get_distance_from_sensors()
            scan_points.append({
                'h_angle': target_h_angle,
                'v_angle': target_v_angle,
                'distance': distance
            })

            logging.debug(f"  H={target_h_angle:+6.1f}° V={target_v_angle:+6.1f}° → {distance:6.1f}cm")

            if distance > max_distance_found:
                max_distance_found = distance
                best_h_angle = target_h_angle

    # Merkeze dön
    move_step_motor_to_angle_local(
        horizontal_scan_motor_devices,
        horizontal_scan_motor_ctx,
        0
    )
    move_step_motor_to_angle_local(
        vertical_scan_motor_devices,
        vertical_scan_motor_ctx,
        0,
        CONFIG['invert_rear_motor_direction']
    )
    time.sleep(CONFIG['motor_settle_time'])

    logging.info(f"✓ Tarama tamamlandı: En açık yol {best_h_angle:+.1f}° ({max_distance_found:.1f}cm)")
    logging.info(f"  Toplam {len(scan_points)} nokta tarandı")

    return best_h_angle, max_distance_found


# --- KARAR MEKANİZMASI ---
def decide_and_act(best_h_angle, max_distance):
    """Tarama sonucuna göre karar verir ve hareket eder."""
    obstacle_limit = CONFIG['obstacle_distance_cm']

    # Kritik durum: Tüm yönler kapalı
    if max_distance < obstacle_limit:
        logging.warning(f"⚠️ SIKIŞTI! En açık yol bile ({max_distance:.1f}cm) çok yakın!")
        logging.warning("   → 180° dönüş yapılıyor...")

        # Yarım tur dön
        for _ in range(2):
            if not turn_right():
                break
            time.sleep(0.2)

        return "TURN_180"

    # İleri git
    elif -15.0 < best_h_angle < 15.0:
        logging.info(f"✓ Karar: İLERİ (Yol açık: {best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        move_forward()
        return "FORWARD"

    # Sağa dön
    elif best_h_angle >= 15.0:
        logging.info(f"✓ Karar: SAĞA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_right()
        return "TURN_RIGHT"

    # Sola dön
    elif best_h_angle <= -15.0:
        logging.info(f"✓ Karar: SOLA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_left()
        return "TURN_LEFT"


# --- ANA DÖNGÜ ---
def main():
    """Ana program döngüsü."""
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    create_pid_file()

    try:
        setup_hardware()

        # Başlangıç pozisyonu
        logging.info("Tarama motorları merkeze alınıyor...")
        move_step_motor_to_angle_local(
            vertical_scan_motor_devices,
            vertical_scan_motor_ctx,
            0,
            CONFIG['invert_rear_motor_direction']
        )
        move_step_motor_to_angle_local(
            horizontal_scan_motor_devices,
            horizontal_scan_motor_ctx,
            0
        )
        time.sleep(0.5)

        logging.info("=" * 60)
        logging.info("🤖 OTONOM SÜRÜŞ MODU BAŞLATILDI")
        logging.info("=" * 60)

        loop_count = 0

        while not stop_event.is_set():
            loop_count += 1
            loop_start_time = time.time()

            logging.info(f"\n{'=' * 60}")
            logging.info(f"DÖNGÜ #{loop_count}")
            logging.info(f"{'=' * 60}")

            # Güvenlik: Motorları durdur
            stop_motors()
            stop_step_motors_local()
            time.sleep(0.1)

            # 1. Tarama yap
            best_h_angle, max_distance = find_best_path()

            if stop_event.is_set():
                break

            # 2. Karar ver ve hareket et
            action = decide_and_act(best_h_angle, max_distance)

            # 3. Minimum döngü süresi
            elapsed = time.time() - loop_start_time
            min_duration = CONFIG['min_loop_duration']

            if elapsed < min_duration:
                sleep_time = min_duration - elapsed
                logging.info(f"⏱ Döngü süresi: {elapsed:.2f}s, {sleep_time:.2f}s bekleniyor...")
                time.sleep(sleep_time)
            else:
                logging.info(f"⏱ Döngü süresi: {elapsed:.2f}s")

    except KeyboardInterrupt:
        logging.info("\n⚠️ Program kullanıcı tarafından durduruldu (CTRL+C)")
    except Exception as e:
        logging.error(f"❌ KRİTİK HATA: {e}")
        traceback.print_exc()
        stats['errors'] += 1
    finally:
        logging.info("Ana döngüden çıkıldı.")


if __name__ == '__main__':
    main()
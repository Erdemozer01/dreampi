# autonomous_drive_pi5.py - Pi 5 (Beyin) -> Pico (Kas) Sürümü - DÜZELTİLMİŞ
# Proaktif ve Akıllı Navigasyon Betiği

import math
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
import fcntl
import queue
from pathlib import Path
import serial

import django

from gpiozero import DistanceSensor, OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Django'yu başlat
sys.path.append('/home/pi')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dreampi.settings')
django.setup()

from scanner.models import Scan, ScanPoint

# GPIO Factory
try:
    Device.pin_factory = LGPIOFactory()
    logging.info("LGPIO pin factory (Pi 5) başarıyla ayarlandı.")
except Exception as e:
    logging.warning(f"LGPIO kullanılamadı: {e}")

# --- YAPILANDIRMA ---
CONFIG_FILE = '/home/pi/robot_config.json'
DEFAULT_CONFIG = {
    "autonomous_script_pid_file": "/tmp/autonomous_drive_script.pid",
    "pico_serial_port": "/dev/ttyACM0",
    "pico_baud_rate": 115200,
    "pico_response_timeout": 2.0,  # ✅ 2 saniyeye düşürüldü
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

# --- GLOBAL DEĞİŞKENLER ---
CONFIG = {}
current_scan = None
point_counter = 0
current_heading = 0.0  # ✅ Robot yönü takibi

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

# Reaktif mod
current_movement_command = None
movement_lock = threading.Lock()
reactive_mode = True

# Komut kuyruğu
command_queue = queue.Queue()

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


# --- YAPILANDIRMA YÖNETİMİ ---
def load_config():
    """Konfigürasyon dosyasını yükle"""
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                logging.info(f"Konfigürasyon yüklendi: {CONFIG_FILE}")
                return config
        except Exception as e:
            logging.error(f"Konfigürasyon yüklenemedi: {e}")

    # Varsayılan oluştur
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        logging.info(f"Varsayılan konfigürasyon oluşturuldu: {CONFIG_FILE}")
    except Exception as e:
        logging.warning(f"Konfigürasyon dosyası oluşturulamadı: {e}")

    return DEFAULT_CONFIG


CONFIG = load_config()


# --- SİNYAL YÖNETİMİ ---
def signal_handler(sig, frame):
    """Sinyal yakalandığında temizlik yap"""
    logging.info(f"Sinyal alındı: {sig}")
    stop_event.set()


def create_pid_file():
    """PID dosyası oluştur"""
    try:
        with open(CONFIG['autonomous_script_pid_file'], 'w') as f:
            f.write(str(os.getpid()))
        logging.info(f"PID dosyası oluşturuldu: {os.getpid()}")
    except IOError as e:
        logging.error(f"PID dosyası oluşturulamadı: {e}")


def cleanup_on_exit():
    """Çıkışta temizlik işlemleri"""
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
    =============================
    """)

    # Tarama oturumunu kapat
    finish_scan_session()

    try:
        # Sensörleri kapat
        if h_sensor:
            h_sensor.close()
            logging.info("Yatay sensör kapatıldı.")
        if v_sensor:
            v_sensor.close()
            logging.info("Dikey sensör kapatıldı.")

        # Motorları durdur
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

        # Pico'yu kapat
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

        # PID dosyasını sil
        pid_file = CONFIG['autonomous_script_pid_file']
        if os.path.exists(pid_file):
            os.remove(pid_file)
            logging.info("PID dosyası silindi.")

        logging.info("Temizleme tamamlandı.")


# --- VERİTABANI FONKSİYONLARI ---
def create_scan_session():
    """Yeni bir tarama oturumu başlat"""
    global current_scan
    try:
        current_scan = Scan.objects.create(
            scan_type='AUT',
            status='RUN',
            h_scan_angle=CONFIG['scan_h_angle'],
            h_step_angle=CONFIG['scan_h_step'],
            v_scan_angle=CONFIG['scan_v_angle'],
            v_step_angle=CONFIG['scan_v_step']
        )
        logging.info(f"✓ Yeni tarama oturumu: ID={current_scan.id}")
        return True
    except Exception as e:
        logging.error(f"Tarama oturumu başlatılamadı: {e}")
        return False


def save_scan_point(h_angle, v_angle, distance):
    """Bir tarama noktasını DB'ye kaydet"""
    global current_scan, point_counter

    if not current_scan:
        return False

    try:
        # Kartezyen koordinatları hesapla
        h_rad = math.radians(h_angle)
        v_rad = math.radians(v_angle)

        x_cm = distance * math.cos(v_rad) * math.cos(h_rad)
        y_cm = distance * math.cos(v_rad) * math.sin(h_rad)
        z_cm = distance * math.sin(v_rad)

        # DB'ye kaydet
        ScanPoint.objects.create(
            scan=current_scan,
            derece=h_angle,
            dikey_aci=v_angle,
            mesafe_cm=distance,
            x_cm=x_cm,
            y_cm=y_cm,
            z_cm=z_cm,
            hiz_cm_s=0.0
        )

        point_counter += 1
        if point_counter % 10 == 0:
            logging.info(f"📊 {point_counter} nokta kaydedildi")

        return True
    except Exception as e:
        logging.error(f"Nokta kaydedilemedi: {e}")
        return False


def finish_scan_session():
    """Tarama oturumunu sonlandır"""
    global current_scan, point_counter

    if not current_scan:
        return

    try:
        current_scan.status = 'COM'
        current_scan.save()
        logging.info(f"✓ Tarama tamamlandı: {point_counter} nokta kaydedildi")
    except Exception as e:
        logging.error(f"Tarama sonlandırılamadı: {e}")



# --- SERIAL PORT OTOMATİK TESPİT ---
def find_pico_serial_port():
    """Pico'nun bağlı olduğu serial portu otomatik bul"""
    import glob

    possible_ports = [
        CONFIG.get('pico_serial_port', '/dev/ttyACM0'),  # Config'den
        '/dev/ttyACM0', '/dev/ttyACM1', '/dev/ttyACM2',
        '/dev/ttyUSB0', '/dev/ttyUSB1', '/dev/ttyUSB2',
        '/dev/serial0', '/dev/serial1'
    ]

    # Glob ile mevcut portları ekle
    for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*']:
        try:
            possible_ports.extend(glob.glob(pattern))
        except:
            pass

    # Unique yap
    possible_ports = list(set(possible_ports))

    logging.info(f"Serial port aranıyor... Denenen portlar: {possible_ports}")

    for port in possible_ports:
        if not os.path.exists(port):
            continue

        try:
            logging.info(f"Deneniyor: {port}")
            test_serial = serial.Serial(
                port,
                CONFIG['pico_baud_rate'],
                timeout=1.0
            )
            time.sleep(0.5)
            test_serial.reset_input_buffer()
            test_serial.close()
            logging.info(f"✓ Port bulundu: {port}")
            return port
        except (OSError, serial.SerialException) as e:
            logging.debug(f"  {port} kullanılamadı: {e}")
            continue

    logging.error("❌ Hiçbir serial port bulunamadı!")
    return None


# --- DONANIM BAŞLATMA ---
def setup_hardware():
    """Enhanced hardware setup with robust Pico communication"""
    global pico, h_sensor, v_sensor
    global vertical_scan_motor_devices, horizontal_scan_motor_devices

    try:
        # 1. FIND PICO PORT
        pico_port = find_pico_serial_port()
        if not pico_port:
            raise Exception("Pico serial port not found!")

        logging.info(f"Connecting to Pico: {pico_port}")

        # 2. OPEN CONNECTION
        pico = serial.Serial(
            pico_port,
            CONFIG['pico_baud_rate'],
            timeout=5.0,  # Longer initial timeout
            write_timeout=5.0
        )

        # 3. WAIT FOR PICO BOOT (important!)
        logging.info("Waiting for Pico to boot...")
        time.sleep(3.0)  # Give Pico time to initialize

        # 4. CLEAR BUFFERS
        pico.reset_input_buffer()
        pico.reset_output_buffer()

        # 5. WAIT FOR READY MESSAGE
        logging.info("Waiting for Pico 'Hazir' message...")
        ready_received = False
        start_wait = time.time()
        max_wait = 15.0

        while time.time() - start_wait < max_wait:
            if stop_event.is_set():
                break

            try:
                # Check if data is available
                if pico.in_waiting > 0:
                    line = pico.readline().decode('utf-8', errors='ignore').strip()

                    if line:
                        logging.info(f"Pico says: '{line}'")

                        # Check for ready keywords
                        if any(kw in line.lower() for kw in ['hazir', 'ready', 'pico', 'kas']):
                            ready_received = True
                            logging.info("✓ Pico is ready!")
                            break
                else:
                    time.sleep(0.2)

            except Exception as e:
                logging.debug(f"Error reading from Pico: {e}")
                time.sleep(0.2)

        # 6. TEST COMMUNICATION
        if not ready_received:
            logging.warning("⚠ Didn't receive ready message, testing with STOP_DRIVE...")

            pico.reset_input_buffer()
            pico.reset_output_buffer()
            time.sleep(0.5)

            # Try test command
            if send_command_to_pico("STOP_DRIVE", max_retries=1, timeout=3.0):
                logging.info("✓ Pico responds to commands!")
                ready_received = True
            else:
                raise Exception("✗ Pico not responding to commands")

        if not ready_received:
            raise Exception("Failed to establish communication with Pico")

        logging.info("✓ Pico communication established")

        # 7. SETUP SENSORS (rest of the code...)
        logging.info(f"Setting up sensors...")
        h_sensor = DistanceSensor(
            echo=CONFIG['h_pin_echo'],
            trigger=CONFIG['h_pin_trig'],
            max_distance=4,
            threshold_distance=0.3
        )

        v_sensor = DistanceSensor(
            echo=CONFIG['v_pin_echo'],
            trigger=CONFIG['v_pin_trig'],
            max_distance=4,
            threshold_distance=0.3
        )
        logging.info("✓ Sensors ready")

        # 8. SETUP SCAN MOTORS
        logging.info("Setting up scan motors...")
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
        logging.info("✓ Scan motors ready")

        logging.info("=" * 60)
        logging.info("✅ ALL HARDWARE INITIALIZED SUCCESSFULLY")
        logging.info("=" * 60)

        return True

    except Exception as e:
        logging.critical(f"CRITICAL: Hardware setup failed: {e}")
        traceback.print_exc()
        sys.exit(1)



# --- PICO İLETİŞİMİ (İYİLEŞTİRİLMİŞ - RETRY) ---
def send_command_to_pico(command, max_retries=2, timeout=3.0):
    """
    ✅ FIXED: Better timeout handling and buffer management
    """
    if stop_event.is_set() or not pico or not pico.is_open:
        return False

    for attempt in range(max_retries):
        with pico_lock:
            try:
                # Clear buffers completely
                pico.reset_input_buffer()
                pico.reset_output_buffer()
                time.sleep(0.1)  # Give time for buffers to clear

                # Send command
                command_bytes = f"{command}\n".encode('utf-8')
                pico.write(command_bytes)
                pico.flush()  # Ensure it's sent
                logging.debug(f"→ PICO: {command}")

                # Wait for ACK with timeout
                pico.timeout = timeout
                start_time = time.time()

                ack = pico.readline().decode('utf-8', errors='ignore').strip()
                ack_time = time.time() - start_time
                logging.debug(f"← PICO ACK: '{ack}' ({ack_time:.2f}s)")

                if ack != "ACK":
                    if ack == "":
                        logging.warning(f"Timeout waiting for ACK (attempt {attempt + 1})")
                    else:
                        logging.error(f"Expected ACK, got '{ack}' (attempt {attempt + 1})")
                    time.sleep(0.3)
                    continue

                # Wait for DONE with timeout
                done = pico.readline().decode('utf-8', errors='ignore').strip()
                done_time = time.time() - start_time
                logging.debug(f"← PICO DONE: '{done}' ({done_time:.2f}s)")

                if done != "DONE":
                    if done == "":
                        logging.warning(f"Timeout waiting for DONE (attempt {attempt + 1})")
                    else:
                        logging.error(f"Expected DONE, got '{done}' (attempt {attempt + 1})")
                    time.sleep(0.3)
                    continue

                # Success
                total_time = time.time() - start_time
                if total_time > 1.0:
                    logging.warning(f"Slow response: {total_time:.2f}s")

                return True

            except serial.SerialTimeoutException:
                logging.warning(f"Serial timeout (attempt {attempt + 1}/{max_retries})")
                time.sleep(0.5)

            except serial.SerialException as e:
                logging.error(f"Serial error: {e} (attempt {attempt + 1})")
                time.sleep(0.5)

            except Exception as e:
                logging.error(f"Unexpected error: {e} (attempt {attempt + 1})")
                traceback.print_exc()
                time.sleep(0.5)

    logging.error(f"✗ Command failed after {max_retries} attempts: {command}")
    stats['errors'] += 1
    return False

# --- HAREKET FONKSİYONLARI ---
def move_forward():
    global current_heading
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
    global current_heading
    logging.info(f"↶ SOLA ({CONFIG['turn_duration_ms']} ms)")
    if send_command_to_pico(f"TURN_LEFT:{CONFIG['turn_duration_ms']}"):
        stats['left_turns'] += 1
        current_heading = (current_heading - 30) % 360  # ✅ Yön takibi
        return True
    return False


def turn_right():
    global current_heading
    logging.info(f"↷ SAĞA ({CONFIG['turn_duration_ms']} ms)")
    if send_command_to_pico(f"TURN_RIGHT:{CONFIG['turn_duration_ms']}"):
        stats['right_turns'] += 1
        current_heading = (current_heading + 30) % 360  # ✅ Yön takibi
        return True
    return False


def turn_slight_left():
    global current_heading
    logging.info(f"↖ HAFİF SOLA ({CONFIG['move_duration_ms']} ms)")
    if send_command_to_pico(f"SLIGHT_LEFT:{CONFIG['move_duration_ms']}"):
        stats['left_turns'] += 1
        current_heading = (current_heading - 15) % 360
        return True
    return False


def turn_slight_right():
    global current_heading
    logging.info(f"↗ HAFİF SAĞA ({CONFIG['move_duration_ms']} ms)")
    if send_command_to_pico(f"SLIGHT_RIGHT:{CONFIG['move_duration_ms']}"):
        stats['right_turns'] += 1
        current_heading = (current_heading + 15) % 360
        return True
    return False


def stop_motors():
    global current_movement_command
    logging.info("⏹ MOTORLAR DURDUR")
    current_movement_command = "STOP"
    return send_command_to_pico("STOP_DRIVE")


# --- REAKTİF MOD FONKSİYONLARI ---
def continuous_move_forward():
    """Sürekli ileri git"""
    logging.info("⏩ SÜREKLİ İLERİ HAREKET BAŞLATILDI")
    return send_command_to_pico("CONTINUOUS_FORWARD")


def continuous_turn_and_move(direction):
    """Dönerken ileri git"""
    if direction == 'LEFT':
        logging.info("↖ SOLA DÖNERKEN İLERİ")
        return send_command_to_pico("CONTINUOUS_TURN_LEFT")
    else:
        logging.info("↗ SAĞA DÖNERKEN İLERİ")
        return send_command_to_pico("CONTINUOUS_TURN_RIGHT")


def continuous_slight_turn(direction):
    """Hafif dönerek ileri git"""
    if direction == 'LEFT':
        logging.info("↰ HAFİF SOLA DÜZELT")
        return send_command_to_pico("CONTINUOUS_SLIGHT_LEFT")
    else:
        logging.info("↱ HAFİF SAĞA DÜZELT")
        return send_command_to_pico("CONTINUOUS_SLIGHT_RIGHT")


def update_movement_command():
    """Mevcut hareket komutunu değiştir"""
    global current_movement_command
    with movement_lock:
        if current_movement_command:
            send_command_to_pico(current_movement_command)


# --- TARAMA MOTOR FONKSİYONLARI ---
def _set_motor_pins(motor_devices, s1, s2, s3, s4):
    """Motor pinlerini ayarla"""
    motor_devices[0].value = bool(s1)
    motor_devices[1].value = bool(s2)
    motor_devices[2].value = bool(s3)
    motor_devices[3].value = bool(s4)


def _step_motor_local(motor_devices, motor_ctx, num_steps, direction_positive, invert_direction=False):
    """Motor adımlarını yürüt"""
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
    """Motoru belirli açıya getir"""
    deg_per_step = 360.0 / CONFIG['steps_per_revolution']
    angle_diff = target_angle_deg - motor_ctx['current_angle']

    if abs(angle_diff) < deg_per_step:
        return

    num_steps = round(abs(angle_diff) / deg_per_step)
    _step_motor_local(motor_devices, motor_ctx, num_steps, (angle_diff > 0), invert_direction)

    if not stop_event.is_set():
        motor_ctx['current_angle'] = target_angle_deg


def stop_step_motors_local():
    """Tüm tarama motorlarını durdur"""
    if vertical_scan_motor_devices:
        _set_motor_pins(vertical_scan_motor_devices, 0, 0, 0, 0)
    if horizontal_scan_motor_devices:
        _set_motor_pins(horizontal_scan_motor_devices, 0, 0, 0, 0)


# --- SENSÖR OKUMA ---
def get_distance_from_sensors():
    """Her iki sensörden de okuma yap ve güvenilir sonuç dön"""
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

    return min(dist_h_median, dist_v_median)


# --- HIZLI TARAMA (REAKTİF MOD) ---
def quick_scan_horizontal():
    """
    Sadece yatay eksende hızlı tarama (dikey sabit)
    ✅ DÜZELTİLDİ: Scan noktalarını kaydediyor
    """
    max_distance_found = 0.0
    best_h_angle = 0.0

    h_scan_angle = 60.0
    h_step = 30.0

    h_initial_angle = -h_scan_angle / 2.0
    num_h_steps = int(h_scan_angle / h_step)

    for i in range(num_h_steps + 1):
        if stop_event.is_set():
            break

        target_h_angle = h_initial_angle + (i * h_step)
        move_step_motor_to_angle_local(
            horizontal_scan_motor_devices,
            horizontal_scan_motor_ctx,
            target_h_angle
        )

        time.sleep(0.03)

        distance = get_distance_from_sensors()

        # ✅ DÜZELTİLDİ: Veriyi kaydet
        save_scan_point(target_h_angle, 0, distance)

        if distance > max_distance_found:
            max_distance_found = distance
            best_h_angle = target_h_angle

    # Merkeze dön
    move_step_motor_to_angle_local(
        horizontal_scan_motor_devices,
        horizontal_scan_motor_ctx,
        0
    )

    return best_h_angle, max_distance_found


# --- TAM 3D TARAMA ---
def find_best_path():
    """
    3D tarama yapar ve en açık yolu bulur
    ✅ DÜZELTİLDİ: Scan noktalarını kaydediyor
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

            # ✅ DB'ye kaydet
            save_scan_point(target_h_angle, target_v_angle, distance)

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


# --- REAKTİF KARAR MEKANİZMASI ---
def reactive_decide_and_act(best_h_angle, max_distance):
    """Reaktif navigasyon - motorlar sürekli hareket eder"""
    global current_movement_command

    obstacle_limit = CONFIG['obstacle_distance_cm']

    # ACİL DURUM
    if max_distance < obstacle_limit * 0.7:
        logging.warning(f"🚨 ACİL DURUM! Engel çok yakın: {max_distance:.1f}cm")
        current_movement_command = "STOP_DRIVE"
        update_movement_command()
        time.sleep(0.3)
        send_command_to_pico(f"BACKWARD:{CONFIG['move_duration_ms'] // 2}")
        return "EMERGENCY_STOP"

    # TEHLİKE
    elif max_distance < obstacle_limit:
        logging.warning(f"⚠️ Engel yakın: {max_distance:.1f}cm, keskin dönüş")
        if best_h_angle >= 0:
            current_movement_command = "CONTINUOUS_TURN_RIGHT"
        else:
            current_movement_command = "CONTINUOUS_TURN_LEFT"
        update_movement_command()
        return "SHARP_TURN"

    # BÜYÜK SAPMA
    elif abs(best_h_angle) > 45.0:
        if best_h_angle > 0:
            logging.info(f"↗ SAĞA DÖNERKEN İLERİ ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_TURN_RIGHT"
        else:
            logging.info(f"↖ SOLA DÖNERKEN İLERİ ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_TURN_LEFT"
        update_movement_command()
        return "TURN_WHILE_MOVING"

    # ORTA SAPMA
    elif abs(best_h_angle) > 15.0:
        if best_h_angle > 0:
            logging.info(f"↱ HAFİF SAĞA DÜZELT ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_SLIGHT_RIGHT"
        else:
            logging.info(f"↰ HAFİF SOLA DÜZELT ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_SLIGHT_LEFT"
        update_movement_command()
        return "SLIGHT_CORRECTION"

    # YOL AÇIK
    else:
        logging.info(f"⏩ DÜMDÜZ İLERİ ({best_h_angle:.1f}°, {max_distance:.1f}cm)")
        current_movement_command = "CONTINUOUS_FORWARD"
        update_movement_command()
        return "STRAIGHT"


# --- HEDEFE NAVİGASYON ---
def navigate_to_target(target_x, target_y, target_z):
    """
    Belirli bir hedefe (3D koordinat) gitmek için
    robotun yönünü ayarlar ve hareket eder
    ✅ DÜZELTİLDİ: current_heading kullanıyor
    """
    global current_heading

    logging.info(f"🎯 Hedefe gidiliyor: ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")

    # 1. Hedefe yönelme açısını hesapla
    distance_2d = math.sqrt(target_x ** 2 + target_y ** 2)
    target_angle = math.degrees(math.atan2(target_y, target_x))

    logging.info(f"   Hedef açı: {target_angle:.1f}°, Mesafe: {distance_2d:.1f}cm")

    # 2. Açı farkını hesapla
    angle_diff = target_angle - current_heading

    # Normalize et (-180° ile +180° arası)
    while angle_diff > 180:
        angle_diff -= 360
    while angle_diff < -180:
        angle_diff += 360

    # 3. Dönüş yap
    if abs(angle_diff) > 5:
        num_turns = int(abs(angle_diff) / 30)

        for _ in range(num_turns):
            if angle_diff > 0:
                logging.info("   ↷ Sağa dön")
                turn_right()
            else:
                logging.info("   ↶ Sola dön")
                turn_left()
            time.sleep(0.2)

    # 4. İleri git (mesafeye göre süre hesapla)
    # Varsayım: Robot ~20cm/s hızla gider
    required_duration = int((distance_2d / 20.0) * 1000)
    required_duration = min(required_duration, 5000)  # Max 5 saniye

    logging.info(f"   → İleri git ({required_duration}ms)")

    if send_command_to_pico(f"FORWARD:{required_duration}"):
        logging.info("   ✓ Hedefe ulaşıldı (yaklaşık)")
    else:
        logging.error("   ✗ Hareket başarısız")

    # 5. Doğrulama taraması
    best_angle, min_dist = find_best_path()
    if min_dist < 30:
        logging.warning("   ⚠️ Hedefe yaklaşıldı ama engel var!")


# --- KOMUT DİNLEYİCİ THREAD ---
def command_listener_thread():
    """
    Komut dosyasından komut dinler
    ✅ DÜZELTİLDİ: Atomic file operations + fcntl lock
    """
    command_file = '/tmp/robot_command.txt'

    while not stop_event.is_set():
        try:
            if os.path.exists(command_file):
                with open(command_file, 'r+') as f:
                    # ✅ Dosyayı kilitle
                    fcntl.flock(f, fcntl.LOCK_EX)
                    command = f.read().strip()
                    f.seek(0)
                    f.truncate(0)
                    fcntl.flock(f, fcntl.LOCK_UN)

                if command.startswith("GOTO:"):
                    # Format: GOTO:x,y,z
                    coords = command.split(":")[1].split(",")
                    target_x = float(coords[0])
                    target_y = float(coords[1])
                    target_z = float(coords[2])

                    logging.info(f"📨 Komut alındı: {command}")
                    command_queue.put(('goto', target_x, target_y, target_z))

                # Dosyayı sil
                try:
                    os.remove(command_file)
                except:
                    pass

        except Exception as e:
            logging.debug(f"Komut dinleme hatası: {e}")

        time.sleep(0.5)


# --- REAKTİF ANA DÖNGÜ ---
def main_reactive():
    """Reaktif navigasyon ana döngüsü"""
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    create_pid_file()

    # Komut dinleyici thread'i başlat
    listener = threading.Thread(target=command_listener_thread, daemon=True)
    listener.start()

    try:
        setup_hardware()

        if not create_scan_session():
            logging.critical("Veritabanı oturumu oluşturulamadı, çıkılıyor.")
            return

        # Başlangıç pozisyonu
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

        logging.info("=" * 60)
        logging.info("🚀 REAKTİF OTONOM SÜRÜŞ MODU BAŞLATILDI")
        logging.info("=" * 60)

        # İlk hareketi başlat
        continuous_move_forward()

        loop_count = 0

        while not stop_event.is_set():
            loop_count += 1
            loop_start_time = time.time()

            logging.debug(f"--- Döngü #{loop_count} ---")

            # Komut kuyruğunu kontrol et
            if not command_queue.empty():
                cmd = command_queue.get()

                if cmd[0] == 'goto':
                    _, target_x, target_y, target_z = cmd
                    logging.info("🎯 Hedefe gitme modu aktif")

                    # Mevcut hareketi durdur
                    stop_motors()
                    time.sleep(0.5)

                    # Hedefe git
                    navigate_to_target(target_x, target_y, target_z)

                    # Normal otonom moda dön
                    logging.info("↩ Normal otonom moda dönülüyor")
                    continuous_move_forward()
                    continue

            # HIZLI TARAMA (motorlar hareket ederken)
            best_h_angle, max_distance = quick_scan_horizontal()

            if stop_event.is_set():
                break

            # ANINDA KARAR VE YÖNLENDİRME
            action = reactive_decide_and_act(best_h_angle, max_distance)

            # Döngü süresi kontrolü
            elapsed = time.time() - loop_start_time
            logging.debug(f"Döngü süresi: {elapsed:.3f}s")

            # Minimum 0.2 saniye bekle
            if elapsed < 0.2:
                time.sleep(0.2 - elapsed)

    except KeyboardInterrupt:
        logging.info("\n⚠️ Program kullanıcı tarafından durduruldu (CTRL+C)")
        stop_motors()
    except Exception as e:
        logging.error(f"❌ KRİTİK HATA: {e}")
        traceback.print_exc()
        stop_motors()
    finally:
        logging.info("Ana döngüden çıkıldı.")


# --- KLASİK ANA DÖNGÜ (PERİYODİK TARAMA) ---
def main_classic():
    """Klasik navigasyon - periyodik tam tarama"""
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    create_pid_file()

    try:
        setup_hardware()

        if not create_scan_session():
            logging.critical("Veritabanı oturumu oluşturulamadı, çıkılıyor.")
            return

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
        logging.info("🤖 KLASİK OTONOM SÜRÜŞ MODU BAŞLATILDI")
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

            # 1. Tam 3D tarama yap
            best_h_angle, max_distance = find_best_path()

            if stop_event.is_set():
                break

            # 2. Karar ver ve hareket et
            obstacle_limit = CONFIG['obstacle_distance_cm']

            # Kritik durum: Tüm yönler kapalı
            if max_distance < obstacle_limit:
                logging.warning(f"⚠️ SIKIŞTI! En açık yol bile ({max_distance:.1f}cm) çok yakın!")
                logging.warning("   → 180° dönüş yapılıyor...")

                for _ in range(2):
                    if not turn_right():
                        break
                    time.sleep(0.2)

                action = "TURN_180"

            # İleri git
            elif -15.0 < best_h_angle < 15.0:
                logging.info(f"✓ Karar: İLERİ (Yol açık: {best_h_angle:+.1f}°, {max_distance:.1f}cm)")
                move_forward()
                action = "FORWARD"

            # Sağa dön
            elif best_h_angle >= 15.0:
                logging.info(f"✓ Karar: SAĞA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
                turn_right()
                action = "TURN_RIGHT"

            # Sola dön
            elif best_h_angle <= -15.0:
                logging.info(f"✓ Karar: SOLA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
                turn_left()
                action = "TURN_LEFT"

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


# --- PROGRAM BAŞLANGIÇ ---
if __name__ == '__main__':
    if reactive_mode:
        main_reactive()  # ✅ Reaktif mod (varsayılan)
    else:
        main_classic()  # Klasik periyodik tarama modu
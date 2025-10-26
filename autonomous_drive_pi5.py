# autonomous_drive_pi5.py'ye eklenecek - REAKTİF NAVİGASYON MODU

import threading

# --- GLOBAL DEĞİŞKENLER (ekleyin) ---
current_movement_command = None
movement_lock = threading.Lock()
reactive_mode = True  # Reaktif mod aktif mi?


# --- REAKTİF HAREKET FONKSİYONLARI ---

def continuous_move_forward():
    """Sürekli ileri git (arkaplanda)"""
    logging.info("⏩ SÜREKLİ İLERİ HAREKET BAŞLATILDI")
    if send_command_to_pico("CONTINUOUS_FORWARD"):
        return True
    return False


def continuous_turn_and_move(direction):
    """
    Dönüş yaparken ileri git
    direction: 'LEFT' veya 'RIGHT'
    """
    if direction == 'LEFT':
        logging.info("↖ SOLA DÖNERKEN İLERİ")
        command = "CONTINUOUS_TURN_LEFT"
    else:
        logging.info("↗ SAĞA DÖNERKEN İLERİ")
        command = "CONTINUOUS_TURN_RIGHT"

    if send_command_to_pico(command):
        return True
    return False


def continuous_slight_turn(direction):
    """
    Hafif dönüş yaparak ileri git (düzeltme)
    direction: 'LEFT' veya 'RIGHT'
    """
    if direction == 'LEFT':
        logging.info("↰ HAFİF SOLA DÜZELT")
        command = "CONTINUOUS_SLIGHT_LEFT"
    else:
        logging.info("↱ HAFİF SAĞA DÜZELT")
        command = "CONTINUOUS_SLIGHT_RIGHT"

    if send_command_to_pico(command):
        return True
    return False


def update_movement_command():
    """
    Mevcut hareket komutunu değiştirir (motorlar durmadan)
    """
    global current_movement_command

    with movement_lock:
        # Yeni komutu Pico'ya gönder
        if current_movement_command:
            send_command_to_pico(current_movement_command)


# --- HIZLI TARAMA (Reaktif Mod İçin) ---

def quick_scan_horizontal():
    """
    Sadece yatay eksende hızlı tarama (dikey sabit)
    Çok daha hızlı: ~0.5 saniye
    """
    max_distance_found = 0.0
    best_h_angle = 0.0

    h_scan_angle = 60.0  # Daha dar açı (90° yerine)
    h_step = 30.0  # Daha büyük adımlar

    h_initial_angle = -h_scan_angle / 2.0
    num_h_steps = int(h_scan_angle / h_step)

    # Yatay motoru hareket ettir, dikey sabit
    for i in range(num_h_steps + 1):
        if stop_event.is_set():
            break

        target_h_angle = h_initial_angle + (i * h_step)
        move_step_motor_to_angle_local(
            horizontal_scan_motor_devices,
            horizontal_scan_motor_ctx,
            target_h_angle
        )

        time.sleep(0.03)  # Çok kısa bekleme

        distance = get_distance_from_sensors()

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


# --- REAKTİF KARAR MEKANİZMASI ---

def reactive_decide_and_act(best_h_angle, max_distance):
    """
    Reaktif navigasyon - motorlar sürekli hareket eder
    Sadece yön değiştirilir
    """
    global current_movement_command

    obstacle_limit = CONFIG['obstacle_distance_cm']

    # ACİL DURUM: Çok yakın engel
    if max_distance < obstacle_limit * 0.7:  # %70'inden yakınsa
        logging.warning(f"🚨 ACİL DURUM! Engel çok yakın: {max_distance:.1f}cm")
        current_movement_command = "STOP_DRIVE"
        update_movement_command()
        time.sleep(0.3)
        # Geri git
        send_command_to_pico(f"BACKWARD:{CONFIG['move_duration_ms'] // 2}")
        return "EMERGENCY_STOP"

    # TEHLİKE: Engel yakın ama dönebiliriz
    elif max_distance < obstacle_limit:
        logging.warning(f"⚠️ Engel yakın: {max_distance:.1f}cm, keskin dönüş")
        if best_h_angle >= 0:
            current_movement_command = "CONTINUOUS_TURN_RIGHT"
        else:
            current_movement_command = "CONTINUOUS_TURN_LEFT"
        update_movement_command()
        return "SHARP_TURN"

    # BÜYÜK SAPMA: Dönüş yaparken ileri (45°+)
    elif abs(best_h_angle) > 45.0:
        if best_h_angle > 0:
            logging.info(f"↗ SAĞA DÖNERKEN İLERİ ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_TURN_RIGHT"
        else:
            logging.info(f"↖ SOLA DÖNERKEN İLERİ ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_TURN_LEFT"
        update_movement_command()
        return "TURN_WHILE_MOVING"

    # ORTA SAPMA: Hafif dönüş (15° - 45°)
    elif abs(best_h_angle) > 15.0:
        if best_h_angle > 0:
            logging.info(f"↱ HAFİF SAĞA DÜZELT ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_SLIGHT_RIGHT"
        else:
            logging.info(f"↰ HAFİF SOLA DÜZELT ({best_h_angle:.1f}°)")
            current_movement_command = "CONTINUOUS_SLIGHT_LEFT"
        update_movement_command()
        return "SLIGHT_CORRECTION"

    # YOL AÇIK: Dümdüz ileri
    else:
        logging.info(f"⏩ DÜMDÜZ İLERİ ({best_h_angle:.1f}°, {max_distance:.1f}cm)")
        current_movement_command = "CONTINUOUS_FORWARD"
        update_movement_command()
        return "STRAIGHT"


# --- REAKTİF ANA DÖNGÜ ---

def main_reactive():
    """Reaktif navigasyon ana döngüsü"""
    anext.register(cleanup_on_exit)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    create_pid_file()

    try:
        setup_hardware()

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

            # HIZLI TARAMA (motorlar hareket ederken)
            best_h_angle, max_distance = quick_scan_horizontal()

            if stop_event.is_set():
                break

            # ANINDA KARAR VE YÖNLENDĐRME
            action = reactive_decide_and_act(best_h_angle, max_distance)

            # Döngü süresi kontrolü
            elapsed = time.time() - loop_start_time
            logging.debug(f"Döngü süresi: {elapsed:.3f}s")

            # Minimum 0.2 saniye bekle (çok hızlı değişim olmasın)
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


# autonomous_drive_pi5.py sonuna ekleyin:

reactive_mode = True  # False yaparsanız klasik mod

if __name__ == '__main__':
    if reactive_mode:
        main_reactive()  # REAKTİF MOD
    else:
        main()           # KLASİK MOD
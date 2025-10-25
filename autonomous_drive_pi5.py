# autonomous_drive_pi5.py içine eklenecek fonksiyonlar

# --- YUMUŞAK DÖNÜŞ FONKSİYONLARI ---

def turn_slight_left():
    """Hafif sola dön (bir tekerlek yavaş, diğeri hızlı)"""
    logging.info(f"↖ HAFİF SOLA ({CONFIG['move_duration_ms']} ms)")
    # Pico'ya özel komut gönder
    if send_command_to_pico(f"SLIGHT_LEFT:{CONFIG['move_duration_ms']}"):
        stats['left_turns'] += 1
        return True
    return False


def turn_slight_right():
    """Hafif sağa dön (bir tekerlek yavaş, diğeri hızlı)"""
    logging.info(f"↗ HAFİF SAĞA ({CONFIG['move_duration_ms']} ms)")
    if send_command_to_pico(f"SLIGHT_RIGHT:{CONFIG['move_duration_ms']}"):
        stats['right_turns'] += 1
        return True
    return False


def turn_sharp_left():
    """Keskin sola dön (yerinde)"""
    logging.info(f"↰ KESKİN SOLA ({CONFIG['turn_duration_ms']} ms)")
    if send_command_to_pico(f"TURN_LEFT:{CONFIG['turn_duration_ms']}"):
        stats['left_turns'] += 1
        return True
    return False


def turn_sharp_right():
    """Keskin sağa dön (yerinde)"""
    logging.info(f"↱ KESKİN SAĞA ({CONFIG['turn_duration_ms']} ms)")
    if send_command_to_pico(f"TURN_RIGHT:{CONFIG['turn_duration_ms']}"):
        stats['right_turns'] += 1
        return True
    return False


# --- GELİŞMİŞ KARAR MEKANİZMASI ---

def decide_and_act_smooth(best_h_angle, max_distance):
    """
    Açıya göre daha yumuşak hareket kararları verir.
    """
    obstacle_limit = CONFIG['obstacle_distance_cm']

    # Kritik durum: Tüm yönler kapalı
    if max_distance < obstacle_limit:
        logging.warning(f"⚠️ SIKIŞTI! En açık yol bile ({max_distance:.1f}cm) çok yakın!")
        logging.warning("   → 180° dönüş yapılıyor...")
        for _ in range(2):
            if not turn_sharp_right():
                break
            time.sleep(0.2)
        return "TURN_180"

    # Hafif sapma: İleri giderken dönerek düzelt (5° - 20°)
    elif 5.0 < best_h_angle <= 20.0:
        logging.info(f"✓ Karar: HAFİF SAĞA DÖN + İLERİ ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_slight_right()
        time.sleep(0.1)
        move_forward()
        return "SLIGHT_RIGHT_FORWARD"

    elif -20.0 <= best_h_angle < -5.0:
        logging.info(f"✓ Karar: HAFİF SOLA DÖN + İLERİ ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_slight_left()
        time.sleep(0.1)
        move_forward()
        return "SLIGHT_LEFT_FORWARD"

    # Orta sapma: Keskin dönüş (20° - 45°)
    elif 20.0 < best_h_angle <= 45.0:
        logging.info(f"✓ Karar: KESKİN SAĞA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_sharp_right()
        return "SHARP_RIGHT"

    elif -45.0 <= best_h_angle < -20.0:
        logging.info(f"✓ Karar: KESKİN SOLA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_sharp_left()
        return "SHARP_LEFT"

    # Büyük sapma: Birden fazla dönüş (45°+)
    elif best_h_angle > 45.0:
        logging.info(f"✓ Karar: BÜYÜK SAĞA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_sharp_right()
        time.sleep(0.1)
        turn_sharp_right()
        return "LARGE_RIGHT"

    elif best_h_angle < -45.0:
        logging.info(f"✓ Karar: BÜYÜK SOLA DÖN ({best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        turn_sharp_left()
        time.sleep(0.1)
        turn_sharp_left()
        return "LARGE_LEFT"

    # Minimal sapma: Dümdüz ileri (-5° ile +5° arası)
    else:
        logging.info(f"✓ Karar: İLERİ (Yol açık: {best_h_angle:+.1f}°, {max_distance:.1f}cm)")
        move_forward()
        return "FORWARD"

# main() içinde değişiklik:
# decide_and_act(best_h_angle, max_distance) yerine:
# decide_and_act_smooth(best_h_angle, max_distance)
#!/usr/bin/env python3
# debug_scan.py - Ana programın tarama fonksiyonunu debug et

import time
import json
import logging
import statistics
from gpiozero import DistanceSensor, OutputDevice, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Pi 5 için LGPIO
Device.pin_factory = LGPIOFactory()

# Loglama
logging.basicConfig(
    level=logging.DEBUG,  # Her şeyi göster
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Config yükle
with open('/home/pi/robot_config.json', 'r') as f:
    CONFIG = json.load(f)

# Global değişkenler
h_sensor = None
v_sensor = None
horizontal_scan_motor_devices = None
vertical_scan_motor_devices = None
horizontal_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}
vertical_scan_motor_ctx = {'current_angle': 0.0, 'sequence_index': 0}

step_sequence = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]


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

    logging.debug(
        f"Motor step: {num_steps} adım, yön: {'ileri' if direction_positive else 'geri'}, invert: {invert_direction}")

    for i in range(int(num_steps)):
        motor_ctx['sequence_index'] = (motor_ctx['sequence_index'] + step_increment) % len(step_sequence)
        _set_motor_pins(motor_devices, *step_sequence[motor_ctx['sequence_index']])
        time.sleep(CONFIG['step_motor_inter_step_delay'])

        if i % 100 == 0:
            logging.debug(f"  Adım {i}/{num_steps}")


def move_step_motor_to_angle_local(motor_devices, motor_ctx, target_angle_deg, invert_direction=False):
    """Motoru belirli açıya getirir."""
    deg_per_step = 360.0 / CONFIG['steps_per_revolution']
    angle_diff = target_angle_deg - motor_ctx['current_angle']

    logging.info(f"Motor hedef: {target_angle_deg}° (mevcut: {motor_ctx['current_angle']}°, fark: {angle_diff}°)")

    if abs(angle_diff) < deg_per_step:
        logging.debug("  Açı farkı çok küçük, hareket yok")
        return

    num_steps = round(abs(angle_diff) / deg_per_step)
    logging.info(f"  {num_steps} adım yapılacak")

    _step_motor_local(motor_devices, motor_ctx, num_steps, (angle_diff > 0), invert_direction)
    motor_ctx['current_angle'] = target_angle_deg
    logging.info(f"  Motor pozisyonu güncellendi: {motor_ctx['current_angle']}°")


def get_distance_from_sensors():
    """Sensörlerden mesafe oku."""
    readings_h = []
    readings_v = []

    for i in range(CONFIG['sensor_readings_count']):
        # Yatay sensör
        try:
            dist_h = h_sensor.distance * 100
            if 2 < dist_h < 398:
                readings_h.append(dist_h)
                logging.debug(f"  H-Sensör okuma {i + 1}: {dist_h:.1f}cm ✓")
            else:
                logging.warning(f"  H-Sensör okuma {i + 1}: {dist_h:.1f}cm (aralık dışı)")
        except Exception as e:
            logging.error(f"  H-Sensör okuma {i + 1} HATA: {e}")

        # Dikey sensör
        try:
            dist_v = v_sensor.distance * 100
            if 2 < dist_v < 398:
                readings_v.append(dist_v)
                logging.debug(f"  V-Sensör okuma {i + 1}: {dist_v:.1f}cm ✓")
            else:
                logging.warning(f"  V-Sensör okuma {i + 1}: {dist_v:.1f}cm (aralık dışı)")
        except Exception as e:
            logging.error(f"  V-Sensör okuma {i + 1} HATA: {e}")

        time.sleep(0.01)

    # Medyan hesapla
    dist_h_median = statistics.median(readings_h) if readings_h else float('inf')
    dist_v_median = statistics.median(readings_v) if readings_v else float('inf')

    result = min(dist_h_median, dist_v_median)

    logging.info(
        f"Sensör sonuç: H={dist_h_median:.1f}cm ({len(readings_h)} okuma), V={dist_v_median:.1f}cm ({len(readings_v)} okuma) → Min={result:.1f}cm")

    return result


def debug_scan():
    """Debug tarama fonksiyonu"""
    logging.info("=" * 60)
    logging.info("🔬 DEBUG TARAMA BAŞLATILIYOR")
    logging.info("=" * 60)

    h_scan_angle = CONFIG['scan_h_angle']
    h_step = CONFIG['scan_h_step']
    v_scan_angle = CONFIG['scan_v_angle']
    v_step = CONFIG['scan_v_step']

    h_initial_angle = -h_scan_angle / 2.0
    v_initial_angle = 0.0

    num_h_steps = int(h_scan_angle / h_step) if h_step > 0 else 0
    num_v_steps = int(v_scan_angle / v_step) if v_step > 0 else 0

    logging.info(f"Yatay tarama: {h_initial_angle}° → +{h_scan_angle / 2}° ({num_h_steps + 1} nokta)")
    logging.info(f"Dikey tarama: 0° → {v_scan_angle}° ({num_v_steps + 1} nokta)")
    logging.info(f"Toplam tarama noktası: {(num_h_steps + 1) * (num_v_steps + 1)}")

    # Başlangıç pozisyonuna git
    logging.info("\n🔧 Başlangıç pozisyonuna gidiliyor...")

    logging.info("  📍 YATAY motor başlangıca")
    move_step_motor_to_angle_local(
        horizontal_scan_motor_devices,
        horizontal_scan_motor_ctx,
        h_initial_angle
    )

    logging.info("  📍 DİKEY motor başlangıca")
    move_step_motor_to_angle_local(
        vertical_scan_motor_devices,
        vertical_scan_motor_ctx,
        v_initial_angle,
        CONFIG['invert_rear_motor_direction']
    )

    logging.info(f"  ⏱ Motor stabilizasyonu: {CONFIG['motor_settle_time']}s")
    time.sleep(CONFIG['motor_settle_time'])

    # Tarama yap
    logging.info("\n🔍 TARAMA BAŞLIYOR...")
    scan_points = []
    max_distance = 0.0
    best_h_angle = 0.0

    for i in range(num_h_steps + 1):
        target_h_angle = h_initial_angle + (i * h_step)

        logging.info(f"\n--- YATAY POZİSYON {i + 1}/{num_h_steps + 1}: {target_h_angle:+.1f}° ---")

        move_step_motor_to_angle_local(
            horizontal_scan_motor_devices,
            horizontal_scan_motor_ctx,
            target_h_angle
        )

        for j in range(num_v_steps + 1):
            # Ping-pong tarama
            if i % 2 == 0:
                target_v_angle = v_initial_angle + (j * v_step)
            else:
                target_v_angle = v_scan_angle - (j * v_step)

            logging.info(f"\n  ↕ Dikey pozisyon {j + 1}/{num_v_steps + 1}: {target_v_angle:+.1f}°")

            move_step_motor_to_angle_local(
                vertical_scan_motor_devices,
                vertical_scan_motor_ctx,
                target_v_angle,
                CONFIG['invert_rear_motor_direction']
            )

            logging.info(f"  ⏱ Sensör stabilizasyonu: {CONFIG['scan_settle_time']}s")
            time.sleep(CONFIG['scan_settle_time'])

            # Mesafe oku
            logging.info("  📏 Sensör okuması:")
            distance = get_distance_from_sensors()

            scan_points.append({
                'h_angle': target_h_angle,
                'v_angle': target_v_angle,
                'distance': distance
            })

            logging.info(f"  📊 H={target_h_angle:+6.1f}° V={target_v_angle:+6.1f}° → {distance:6.1f}cm")

            if distance > max_distance:
                max_distance = distance
                best_h_angle = target_h_angle
                logging.info(f"  🎯 YENİ EN AÇIK YOL: {best_h_angle:+.1f}° ({max_distance:.1f}cm)")

    # Merkeze dön
    logging.info("\n🔧 Merkeze dönülüyor...")
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

    # Sonuçlar
    logging.info("\n" + "=" * 60)
    logging.info("📊 TARAMA SONUÇLARI")
    logging.info("=" * 60)
    logging.info(f"Toplam nokta: {len(scan_points)}")
    logging.info(f"En açık yol: {best_h_angle:+.1f}° ({max_distance:.1f}cm)")

    # Tüm noktaları listele
    logging.info("\n📋 TÜM TARAMA NOKTALARI:")
    for i, point in enumerate(scan_points, 1):
        marker = "🎯" if point['h_angle'] == best_h_angle else "  "
        logging.info(
            f"{marker} {i:2d}. H={point['h_angle']:+6.1f}° V={point['v_angle']:+6.1f}° → {point['distance']:6.1f}cm")

    return best_h_angle, max_distance


def main():
    """Ana fonksiyon"""
    global h_sensor, v_sensor
    global horizontal_scan_motor_devices, vertical_scan_motor_devices

    try:
        logging.info("🚀 Donanım başlatılıyor...")

        # Sensörler
        logging.info(f"  📡 Yatay sensör: Trig={CONFIG['h_pin_trig']}, Echo={CONFIG['h_pin_echo']}")
        h_sensor = DistanceSensor(
            echo=CONFIG['h_pin_echo'],
            trigger=CONFIG['h_pin_trig'],
            max_distance=4,
            threshold_distance=0.3
        )
        logging.info("  ✓ Yatay sensör OK")

        logging.info(f"  📡 Dikey sensör: Trig={CONFIG['v_pin_trig']}, Echo={CONFIG['v_pin_echo']}")
        v_sensor = DistanceSensor(
            echo=CONFIG['v_pin_echo'],
            trigger=CONFIG['v_pin_trig'],
            max_distance=4,
            threshold_distance=0.3
        )
        logging.info("  ✓ Dikey sensör OK")

        # Motorlar
        v_pins = CONFIG['vertical_scan_motor_pins']
        logging.info(f"  ⚙️ Dikey motor: {v_pins}")
        vertical_scan_motor_devices = (
            OutputDevice(v_pins[0]), OutputDevice(v_pins[1]),
            OutputDevice(v_pins[2]), OutputDevice(v_pins[3])
        )
        logging.info("  ✓ Dikey motor OK")

        h_pins = CONFIG['horizontal_scan_motor_pins']
        logging.info(f"  ⚙️ Yatay motor: {h_pins}")
        horizontal_scan_motor_devices = (
            OutputDevice(h_pins[0]), OutputDevice(h_pins[1]),
            OutputDevice(h_pins[2]), OutputDevice(h_pins[3])
        )
        logging.info("  ✓ Yatay motor OK")

        logging.info("\n✅ TÜM DONANIM HAZIR\n")

        # Debug tarama
        best_angle, max_dist = debug_scan()

        logging.info("\n🎉 Debug tarama tamamlandı!")

    except KeyboardInterrupt:
        logging.info("\n⚠️ Kullanıcı tarafından durduruldu")
    except Exception as e:
        logging.error(f"\n❌ HATA: {e}", exc_info=True)
    finally:
        logging.info("\n🧹 Temizleme...")
        try:
            if h_sensor:
                h_sensor.close()
            if v_sensor:
                v_sensor.close()

            # Motorları durdur
            if horizontal_scan_motor_devices:
                _set_motor_pins(horizontal_scan_motor_devices, 0, 0, 0, 0)
                for pin in horizontal_scan_motor_devices:
                    pin.close()

            if vertical_scan_motor_devices:
                _set_motor_pins(vertical_scan_motor_devices, 0, 0, 0, 0)
                for pin in vertical_scan_motor_devices:
                    pin.close()

            Device.pin_factory.close()
            logging.info("✓ Temizleme tamamlandı")
        except:
            pass


if __name__ == "__main__":
    main()
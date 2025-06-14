# ConfigManager sınıfının sonrasına ekleyin:
import contextlib
from typing import Optional

class HardwareManager:
    def __init__(self):
        self.devices = {}
        self.is_initialized = False
        self.config = config_manager.config
    
    @contextlib.contextmanager
    def safe_device_operation(self, device_name: str):
        """Cihaz işlemlerini güvenli bir şekilde yürüt"""
        try:
            device = self.devices.get(device_name)
            if device is None:
                logger.warning(f"{device_name} cihazı bulunamadı")
                yield None
            else:
                yield device
        except Exception as e:
            logger.error(f"{device_name} cihazında hata: {e}")
            yield None
    
    def get_sensor_reading(self, sensor_name: str) -> Optional[float]:
        """Güvenli sensör okuma"""
        with self.safe_device_operation(sensor_name) as sensor:
            if sensor:
                try:
                    distance = sensor.distance
                    return (distance * 100) if distance is not None else None
                except Exception as e:
                    logger.warning(f"{sensor_name} okuma hatası: {e}")
                    return None
        return None
    
    def initialize_all_devices(self):
        """Tüm cihazları başlat"""
        try:
            # Motor cihazları
            if MOTOR_BAGLI:
                motor_pins = self.config["hardware"]["motor_pins"]
                self.devices['in1_dev_step'] = OutputDevice(motor_pins["IN1"])
                self.devices['in2_dev_step'] = OutputDevice(motor_pins["IN2"])
                self.devices['in3_dev_step'] = OutputDevice(motor_pins["IN3"])
                self.devices['in4_dev_step'] = OutputDevice(motor_pins["IN4"])
            
            # Sensörler
            sensor_pins = self.config["hardware"]["sensor_pins"]
            self.devices['sensor_1'] = DistanceSensor(
                echo=sensor_pins["ECHO_1"], trigger=sensor_pins["TRIG_1"], 
                max_distance=3.0, queue_len=5
            )
            self.devices['sensor_2'] = DistanceSensor(
                echo=sensor_pins["ECHO_2"], trigger=sensor_pins["TRIG_2"], 
                max_distance=3.0, queue_len=5
            )
            
            # Servo
            self.devices['servo'] = Servo(
                self.config["hardware"]["servo_pin"],
                min_pulse_width=0.0005, max_pulse_width=0.0025, frame_width=0.02
            )
            
            # Buzzer ve LED
            self.devices['buzzer'] = Buzzer(self.config["hardware"]["buzzer_pin"])
            self.devices['led'] = LED(self.config["hardware"]["led_pin"])
            
            # LCD (opsiyonel)
            try:
                lcd_config = self.config["hardware"]["lcd"]
                self.devices['lcd'] = CharLCD(
                    i2c_expander=lcd_config["port_expander"],
                    address=int(lcd_config["address"], 16),
                    port=lcd_config["i2c_port"],
                    cols=lcd_config["cols"],
                    rows=lcd_config["rows"],
                    auto_linebreaks=True
                )
                self.devices['lcd'].clear()
                self.devices['lcd'].write_string("Sistem Hazir")
            except Exception as e:
                logger.warning(f"LCD başlatılamadı: {e}")
                self.devices['lcd'] = None
            
            self.is_initialized = True
            logger.info("Tüm cihazlar başarıyla başlatıldı")
            return True
            
        except Exception as e:
            logger.error(f"Cihaz başlatma hatası: {e}")
            return False
    
    def cleanup_all_devices(self):
        """Tüm cihazları temizle"""
        for name, device in self.devices.items():
            try:
                if device and hasattr(device, 'close'):
                    device.close()
                    logger.debug(f"{name} cihazı kapatıldı")
            except Exception as e:
                logger.warning(f"{name} kapatma hatası: {e}")
        
        self.devices.clear()
        self.is_initialized = False

# Global hardware manager
hardware_manager = HardwareManager()
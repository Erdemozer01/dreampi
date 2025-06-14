# Import kısmının sonuna ekleyin:
import json, logging
from pathlib import Path
import contextlib
from typing import Optional
from logging import Logger

logger: Logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        self.config_file = Path('config/sensor_config.json')
        self.config = self.load_config()
    
    def load_config(self):
        """Config dosyasından ayarları yükle"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Config dosyası okunamadı: {e}")
                return self.get_default_config()
        else:
            logger.warning("Config dosyası bulunamadı, varsayılan ayarlar kullanılıyor")
            return self.get_default_config()
    
    def get_default_config(self):
        """Varsayılan config döndür"""
        return {
            "hardware": {
                "motor_pins": {"IN1": 26, "IN2": 19, "IN3": 13, "IN4": 6},
                "sensor_pins": {"TRIG_1": 23, "ECHO_1": 24, "TRIG_2": 17, "ECHO_2": 18},
                "servo_pin": 4, "buzzer_pin": 25, "led_pin": 27
            },
            "scan_settings": {
                "horizontal_angle": 270.0, "horizontal_step": 10.0,
                "vertical_angle": 180.0, "vertical_step": 15.0,
                "buzzer_distance": 10, "steps_per_revolution": 4096
            },
            "timing": {
                "inter_step_delay": 0.0015, "settle_time": 0.05,
                "servo_delay": 0.4, "loop_interval": 0.2
            }
        }

# Global config instance oluşturun
config_manager = ConfigManager()
# Bu dosyanın adı: TMC_UART.py
# Yazar: teemu-h (Teemu H)
# https://github.com/teemu-h/TMC-API
# MicroPython için TMC2209 UART kütüphanesi

import time


class TMC_UART:
    # TMC2209 Kayıt Adresleri (Register Addresses)
    TMC2209_GCONF = 0x00
    TMC2209_GSTAT = 0x01
    TMC2209_IFCNT = 0x02
    TMC2209_SLAVECONF = 0x03
    TMC2209_IOIN = 0x04
    TMC2209_X_COMPARE = 0x05
    TMC2209_OTP_PROG = 0x06
    TMC2209_OTP_READ = 0x07
    TMC2209_FACTORY_CONF = 0x08
    TMC2209_SHORT_CONF = 0x09
    TMC2209_DRV_CONF = 0x0A
    TMC2209_GLOBAL_SCALER = 0x0B
    TMC2209_OFFSET_READ = 0x0C
    TMC2209_IHOLD_IRUN = 0x10
    TMC2209_TPOWERDOWN = 0x11
    TMC2209_TSTEP = 0x12
    TMC2209_TPWMTHRS = 0x13
    TMC2209_TCOOLTHRS = 0x14
    TMC2209_THIGH = 0x15
    TMC2209_VDCMIN = 0x1A
    TMC2209_MSLUT0 = 0x60
    TMC2209_MSLUT1 = 0x61
    TMC2209_MSLUT2 = 0x62
    TMC2209_MSLUT3 = 0x63
    TMC2209_MSLUT4 = 0x64
    TMC2209_MSLUT5 = 0x65
    TMC2209_MSLUT6 = 0x66
    TMC2209_MSLUT7 = 0x67
    TMC2209_MSLUTSEL = 0x68
    TMC2209_MSLUTSTART = 0x69
    TMC2209_MSCNT = 0x6A
    TMC2209_MSCURACT = 0x6B
    TMC2209_CHOPCONF = 0x6C
    TMC2209_COOLCONF = 0x6D
    TMC2209_DCCTRL = 0x6E
    TMC2209_DRVSTATUS = 0x6F
    TMC2209_PWMCONF = 0x70
    TMC2209_PWM_SCALE = 0x71
    TMC2209_PWM_AUTO = 0x72
    TMC2209_SGTHRS = 0x40
    TMC2209_SG_RESULT = 0x41
    TMC2209_COOL_CONF = 0x42

    # GCONF bitleri
    TMC2209_GCONF_I_SCALE_ANALOG = 0
    TMC2209_GCONF_INTERNAL_RSENSE = 1
    TMC2209_GCONF_EN_SPREADCYCLE = 2
    TMC2209_GCONF_SHAFT = 3
    TMC2209_GCONF_INDEX_OTPW = 4
    TMC2209_GCONF_INDEX_STEP = 5
    TMC2209_GCONF_PDN_DISABLE = 6
    TMC2209_GCONF_MSTEP_REG_EX = 7
    TMC2209_GCONF_MULTISTEP_FILT = 8
    TMC2209_GCONF_TEST_MODE = 9

    # CHOPCONF bitleri
    TMC2209_CHOPCONF_TOFF_0 = 0
    TMC2209_CHOPCONF_TOFF_1 = 1
    TMC2209_CHOPCONF_TOFF_2 = 2
    TMC2209_CHOPCONF_TOFF_3 = 3
    TMC2209_CHOPCONF_HSTRT_0 = 4
    TMC2209_CHOPCONF_HSTRT_1 = 5
    TMC2209_CHOPCONF_HSTRT_2 = 6
    TMC2209_CHOPCONF_HEND_0 = 7
    TMC2209_CHOPCONF_HEND_1 = 8
    TMC2209_CHOPCONF_HEND_2 = 9
    TMC2209_CHOPCONF_HEND_3 = 10
    TMC2209_CHOPCONF_FD3 = 11
    TMC2209_CHOPCONF_DISFDCC = 12
    TMC2209_CHOPCONF_CHM = 14
    TMC2209_CHOPCONF_TBL_0 = 15
    TMC2209_CHOPCONF_TBL_1 = 16
    TMC2209_CHOPCONF_VHIGHCHM = 18
    TMC2209_CHOPCONF_VHIGHFS = 19
    TMC2209_CHOPCONF_MRES_0 = 24
    TMC2209_CHOPCONF_MRES_1 = 25
    TMC2209_CHOPCONF_MRES_2 = 26
    TMC2209_CHOPCONF_MRES_3 = 27
    TMC2209_CHOPCONF_INTPOL = 28
    TMC2209_CHOPCONF_DEDGE = 29
    TMC2209_CHOPCONF_DISS2G = 30
    TMC2209_CHOPCONF_DISS2VS = 31

    # PWMCONF bitleri
    TMC2209_PWMCONF_PWM_OFS_0 = 0
    TMC2209_PWMCONF_PWM_OFS_1 = 1
    TMC2209_PWMCONF_PWM_OFS_2 = 2
    TMC2209_PWMCONF_PWM_OFS_3 = 3
    TMC2209_PWMCONF_PWM_OFS_4 = 4
    TMC2209_PWMCONF_PWM_OFS_5 = 5
    TMC2209_PWMCONF_PWM_OFS_6 = 6
    TMC2209_PWMCONF_PWM_OFS_7 = 7
    TMC2209_PWMCONF_PWM_GRAD_0 = 8
    TMC2209_PWMCONF_PWM_GRAD_1 = 9
    TMC2209_PWMCONF_PWM_GRAD_2 = 10
    TMC2209_PWMCONF_PWM_GRAD_3 = 11
    TMC2209_PWMCONF_PWM_GRAD_4 = 12
    TMC2209_PWMCONF_PWM_GRAD_5 = 13
    TMC2209_PWMCONF_PWM_GRAD_6 = 14
    TMC2209_PWMCONF_PWM_GRAD_7 = 15
    TMC2209_PWMCONF_PWM_AMPL_0 = 16
    TMC2209_PWMCONF_PWM_AMPL_1 = 17
    TMC2209_PWMCONF_PWM_AMPL_2 = 18
    TMC2209_PWMCONF_PWM_AMPL_3 = 19
    TMC2209_PWMCONF_PWM_AMPL_4 = 20
    TMC2209_PWMCONF_PWM_AMPL_5 = 21
    TMC2209_PWMCONF_PWM_AMPL_6 = 22
    TMC2209_PWMCONF_PWM_AMPL_7 = 23
    TMC2209_PWMCONF_PWM_FREQ_0 = 24
    TMC2209_PWMCONF_PWM_FREQ_1 = 25
    TMC2209_PWMCONF_PWM_AUTOSCALE = 26
    TMC2209_PWMCONF_PWM_AUTOGRAD = 27
    TMC2209_PWMCONF_FREEWHEEL_0 = 28
    TMC2209_PWMCONF_FREEWHEEL_1 = 29
    TMC2209_PWMCONF_PWM_REG_0 = 30
    TMC2209_PWMCONF_PWM_REG_1 = 31

    # IHOLD_IRUN bitleri
    TMC2209_IHOLD_IRUN_IHOLD_0 = 0
    TMC2209_IHOLD_IRUN_IHOLD_1 = 1
    TMC2209_IHOLD_IRUN_IHOLD_2 = 2
    TMC2209_IHOLD_IRUN_IHOLD_3 = 3
    TMC2209_IHOLD_IRUN_IHOLD_4 = 4
    TMC2209_IHOLD_IRUN_IRUN_0 = 8
    TMC2209_IHOLD_IRUN_IRUN_1 = 9
    TMC2209_IHOLD_IRUN_IRUN_2 = 10
    TMC2209_IHOLD_IRUN_IRUN_3 = 11
    TMC2209_IHOLD_IRUN_IRUN_4 = 12
    TMC2209_IHOLD_IRUN_IHOLDDELAY_0 = 16
    TMC2209_IHOLD_IRUN_IHOLDDELAY_1 = 17
    TMC2209_IHOLD_IRUN_IHOLDDELAY_2 = 18
    TMC2209_IHOLD_IRUN_IHOLDDELAY_3 = 19

    # Sabitler
    TMC2209_SYNC = 0x05
    TMC2209_WRITE_ACCESS = 0x80
    TMC2209_READ_ACCESS = 0x00

    def __init__(self, uart, slave_address=0x00):
        self.uart = uart
        self.slave_address = slave_address
        self.write_datagram = bytearray(8)
        self.read_datagram = bytearray(4)

    def _calculate_crc(self, datagram, datagram_length):
        crc = 0
        for i in range(datagram_length):
            current_byte = datagram[i]
            for j in range(8):
                if (crc >> 7) ^ (current_byte & 0x01):
                    crc = (crc << 1) ^ 0x07
                else:
                    crc = crc << 1
                crc &= 0xFF
                current_byte >>= 1
        return crc

    def write_register(self, register_address, data):
        self.write_datagram[0] = self.TMC2209_SYNC
        self.write_datagram[1] = self.slave_address
        self.write_datagram[2] = register_address | self.TMC2209_WRITE_ACCESS
        self.write_datagram[3] = (data >> 24) & 0xFF
        self.write_datagram[4] = (data >> 16) & 0xFF
        self.write_datagram[5] = (data >> 8) & 0xFF
        self.write_datagram[6] = data & 0xFF
        self.write_datagram[7] = self._calculate_crc(self.write_datagram, 7)

        self.uart.write(self.write_datagram)
        # Yazma işleminden sonra sürücünün yanıt vermesi için küçük bir gecikme
        time.sleep_us(50)

        # Sadece-yazma modunda (write-only) okuma fonksiyonu pasifize edilmiştir.

    # Bu kütüphanenin orijinalinde okuma fonksiyonları da bulunur ancak
    # bizim tek pinli kurulumumuz için gerekli değiller.

    # --- Yüksek Seviyeli Ayar Fonksiyonları ---

    def set_run_current(self, percent, ihold_percent=50):
        """
        Çalışma (IRUN) ve Bekleme (IHOLD) akımını 0-100 arası yüzde olarak ayarlar.
        """
        irun = int(31 * percent / 100)
        ihold = int(31 * ihold_percent / 100)
        ihold_delay = 4  # Orta bir değer

        data = (ihold_delay << self.TMC2209_IHOLD_IRUN_IHOLDDELAY_0) | \
               (irun << self.TMC2209_IHOLD_IRUN_IRUN_0) | \
               (ihold << self.TMC2209_IHOLD_IRUN_IHOLD_0)

        self.write_register(self.TMC2209_IHOLD_IRUN, data)

    def set_microsteps(self, microsteps):
        """
        Microstep çözünürlüğünü ayarlar. Değerler: 256, 128, 64, 32, 16, 8, 4, 2, 0 (Full step)
        """
        mres_val = {
            256: 0b0000,
            128: 0b0001,
            64: 0b0010,
            32: 0b0011,
            16: 0b0100,
            8: 0b0101,
            4: 0b0110,
            2: 0b0111,
            0: 0b1000,  # Full step
        }.get(microsteps, 0b0100)  # Varsayılan 16

        # CHOPCONF register'ını oku (Normalde okumamız lazım, ama yazma modundayız)
        # Varsayılan CHOPCONF değerini (0x10000053) temel alarak MRES bitlerini değiştireceğiz
        # Bu sadece yazma modunda bir varsayımdır.

        chopconf_data = 0x10000053  # Varsayılan değer

        # Önce MRES bitlerini temizle
        chopconf_data &= ~((0b1111) << self.TMC2209_CHOPCONF_MRES_0)
        # Yeni MRES bitlerini ayarla
        chopconf_data |= (mres_val << self.TMC2209_CHOPCONF_MRES_0)

        self.write_register(self.TMC2209_CHOPCONF, chopconf_data)

    def enable_stealthchop(self, enable=True):
        """
        StealthChop (sessiz mod) özelliğini açar veya kapatır.
        """
        # GCONF register'ını oku (Normalde okumamız lazım, ama yazma modundayız)
        # Varsayılan GCONF değerini (0x000000C0) temel alacağız

        gconf_data = 0x000000C0  # Varsayılan

        if enable:
            gconf_data &= ~(1 << self.TMC2209_GCONF_EN_SPREADCYCLE)
        else:
            gconf_data |= (1 << self.TMC2209_GCONF_EN_SPREADCYCLE)

        self.write_register(self.TMC2209_GCONF, gconf_data)

    def set_toff(self, toff_value):
        """
        TOFF (chopper off time) ayarı. 0-15 arası. 0: Sürücü kapalı.
        Varsayılan: 3. Düşük hızlarda 3-5, yüksek hızlarda 1-2 önerilir.
        """
        toff_value = max(0, min(15, toff_value))

        # CHOPCONF register
        chopconf_data = 0x10000053  # Varsayılan

        # TOFF bitlerini temizle
        chopconf_data &= ~((0b1111) << self.TMC2209_CHOPCONF_TOFF_0)
        # Yeni TOFF bitlerini ayarla
        chopconf_data |= (toff_value << self.TMC2209_CHOPCONF_TOFF_0)

        self.write_register(self.TMC2209_CHOPCONF, chopconf_data)

    def enable_interpolation(self, enable=True):
        """
        Microstep enterpolasyonunu (16'dan 256'ya) açar.
        """
        chopconf_data = 0x10000053  # Varsayılan

        if enable:
            chopconf_data |= (1 << self.TMC2209_CHOPCONF_INTPOL)
        else:
            chopconf_data &= ~(1 << self.TMC2209_CHOPCONF_INTPOL)

        self.write_register(self.TMC2209_CHOPCONF, chopconf_data)
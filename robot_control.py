# robot_control.py
# This code runs on the Raspberry Pi 5.

import serial
import time
import keyboard

# The serial port where the Pico is connected. Change if necessary (e.g., '/dev/ttyACM1').
PICO_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200

pico_serial = None
try:
    pico_serial = serial.Serial(PICO_PORT, BAUD_RATE, timeout=1)
    print(f"Successfully connected to Pico on port {PICO_PORT}.")
    time.sleep(2)  # Give Pico a moment to initialize its code.
except serial.SerialException as e:
    print(f"ERROR: Could not connect to Pico. {e}")
    print("Please ensure the Pico is connected and you have selected the correct port.")
    exit()


def send_command(command):
    """Encodes and sends a single character command to the Pico."""
    if pico_serial and pico_serial.is_open:
        pico_serial.write(command.encode('utf-8'))
        # print(f"Sent: {command.strip()}") # Uncomment for debugging


print("\n--- Robot Control Panel ---")
print("   Forward: Up Arrow")
print("  Backward: Down Arrow")
print("      Left: Left Arrow")
print("     Right: Right Arrow")
print("      Stop: Spacebar")
print("      Exit: CTRL + C")
print("---------------------------\n")

last_sent_command = None

try:
    while True:
        current_command = None

        if keyboard.is_pressed('up arrow'):
            current_command = 'F\n'
        elif keyboard.is_pressed('down arrow'):
            current_command = 'B\n'
        elif keyboard.is_pressed('left arrow'):
            current_command = 'L\n'
        elif keyboard.is_pressed('right arrow'):
            current_command = 'R\n'
        else:
            current_command = 'S\n'  # If no key is pressed, send Stop

        # To avoid flooding the serial port, only send the command if it has changed.
        if current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        time.sleep(0.05)  # A short delay to reduce CPU usage.

except KeyboardInterrupt:
    print("\nProgram terminated by user.")
finally:
    if pico_serial and pico_serial.is_open:
        print("Sending STOP command and closing serial connection.")
        send_command('S\n')
        pico_serial.close()
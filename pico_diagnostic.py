#!/usr/bin/env python3
"""
Pico Connection Diagnostic Tool
Tests serial communication with Pico before running autonomous mode
"""

import serial
import time
import sys
import glob


def find_serial_ports():
    """Find all available serial ports"""
    ports = []
    for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*', '/dev/serial*']:
        ports.extend(glob.glob(pattern))
    return sorted(set(ports))


def test_port(port, baudrate=115200):
    """Test a specific serial port"""
    print(f"\n{'=' * 60}")
    print(f"Testing: {port}")
    print('=' * 60)

    try:
        # Open port
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"✓ Port opened successfully")

        # Wait for device to settle
        print("  Waiting 2 seconds for device to settle...")
        time.sleep(2)

        # Check what's in the buffer
        waiting = ser.in_waiting
        print(f"  Bytes waiting: {waiting}")

        if waiting > 0:
            data = ser.read(waiting)
            print(f"  Initial data: {data}")
            try:
                decoded = data.decode('utf-8', errors='ignore')
                print(f"  Decoded: '{decoded}'")
            except:
                pass

        # Clear buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.5)

        # Try reading with timeout
        print("\n  Reading for 5 seconds (looking for boot messages)...")
        start = time.time()
        messages = []

        while time.time() - start < 5:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"    << '{line}'")
                    messages.append(line)
            else:
                time.sleep(0.1)

        if not messages:
            print("  ⚠ No messages received (Pico might not be running main.py)")

        # Try sending a test command
        print("\n  Sending test command: 'STOP_DRIVE'")
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.2)

        ser.write(b"STOP_DRIVE\n")
        ser.flush()
        print("    >> STOP_DRIVE")

        # Wait for ACK
        print("  Waiting for ACK (3 seconds)...")
        start = time.time()
        ack_received = False
        done_received = False

        while time.time() - start < 3:
            if ser.in_waiting > 0:
                response = ser.readline().decode('utf-8', errors='ignore').strip()
                if response:
                    print(f"    << '{response}'")
                    if response == "ACK":
                        ack_received = True
                    elif response == "DONE":
                        done_received = True
            else:
                time.sleep(0.05)

        # Results
        print("\n  Results:")
        if ack_received and done_received:
            print("    ✓ ACK received")
            print("    ✓ DONE received")
            print("    ✅ PORT IS WORKING!")
            ser.close()
            return True
        elif ack_received:
            print("    ✓ ACK received")
            print("    ✗ DONE not received")
            print("    ⚠ Partial communication")
        else:
            print("    ✗ No ACK received")
            print("    ✗ Pico not responding to commands")

        ser.close()
        return False

    except serial.SerialException as e:
        print(f"  ✗ Serial error: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "=" * 60)
    print("🔍 PICO CONNECTION DIAGNOSTIC")
    print("=" * 60)

    # Find ports
    ports = find_serial_ports()

    if not ports:
        print("\n✗ No serial ports found!")
        print("\nTroubleshooting:")
        print("  1. Is the Pico connected via USB?")
        print("  2. Check: ls -l /dev/ttyACM* /dev/ttyUSB*")
        print("  3. Check permissions: groups (should include 'dialout')")
        sys.exit(1)

    print(f"\nFound {len(ports)} serial port(s):")
    for port in ports:
        print(f"  - {port}")

    # Test each port
    working_ports = []
    for port in ports:
        if test_port(port):
            working_ports.append(port)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if working_ports:
        print(f"\n✅ Working port(s): {', '.join(working_ports)}")
        print(f"\nUse this in your config:")
        print(f'  "pico_serial_port": "{working_ports[0]}"')
    else:
        print("\n✗ No working ports found!")
        print("\nPossible issues:")
        print("  1. main.py not loaded on Pico")
        print("  2. Pico in error state (check LED)")
        print("  3. Wrong baudrate (should be 115200)")
        print("  4. Pico needs reset (unplug/replug USB)")
        print("\nTo fix:")
        print("  1. Open Thonny IDE")
        print("  2. Connect to Pico")
        print("  3. Upload main.py to Pico")
        print("  4. Save as 'main.py' on the Pico")
        print("  5. Press CTRL+D to soft reboot")
        print("  6. Run this diagnostic again")


if __name__ == "__main__":
    main()
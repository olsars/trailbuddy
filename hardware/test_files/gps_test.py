import math
import serial
import pynmea2

ser = serial.Serial("/dev/ttyAMA0", 9600, timeout=1)
for _ in range(15):
    print(ser.readline().decode("ascii", errors="ignore").strip())
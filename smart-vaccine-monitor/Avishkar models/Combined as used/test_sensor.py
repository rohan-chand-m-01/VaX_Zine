# test_sensor.py

from sensor_reader import read_sensors
import time

while True:
    internal, external, humidity = read_sensors()

    print("Internal Temp:", internal)
    print("External Temp:", external)
    print("Humidity:", humidity)
    print("------------------")

    time.sleep(5)  # delay for 5 seconds
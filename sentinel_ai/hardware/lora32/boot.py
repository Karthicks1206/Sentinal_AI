# boot.py — runs before main.py on every power-up / reset
# MicroPython (ESP32)
import gc
import machine
import utime

# Increase UART buffer for debug output
import uos
uos.dupterm(None, 1)  # disable REPL on UART1, keep only USB serial

# Garbage collect before main starts
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

print("[boot] Sentinel AI LoRa32 node starting...")
print("[boot] Free RAM: {} bytes".format(gc.mem_free()))
utime.sleep_ms(200)

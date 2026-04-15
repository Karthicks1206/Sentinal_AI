"""
Sentinel AI — LoRa32 MicroPython Client
ESP32 + SX127x (Heltec WiFi LoRa 32 V3 / TTGO LoRa32)

Collects system metrics and pushes them to the Sentinel hub via:
  - WiFi mode  : HTTP POST → /api/metrics/push  (same API as sentinel_client.py)
  - LoRa mode  : SX127x radio packet → Pi lora_gateway.py which forwards to hub

Install MicroPython packages once (connect to REPL and run):
  import mip
  mip.install("urequests")          # HTTP client (WiFi mode)
  mip.install("micropython-umqtt.simple")  # optional MQTT

Flash files to device (mpremote or Thonny):
  mpremote cp config.py boot.py main.py :
"""

import gc
import ujson
import utime
import machine
import ubinascii
import network

import config

# ── OLED display ─────────────────────────────────────────────────────────────
try:
    import ssd1306
    from machine import Pin, SoftI2C
    _i2c = SoftI2C(scl=Pin(config.OLED_SCL), sda=Pin(config.OLED_SDA))
    _oled = ssd1306.SSD1306_I2C(config.OLED_WIDTH, config.OLED_HEIGHT, _i2c)
    _OLED = True
except Exception:
    _OLED = False

def oled_show(line1="", line2="", line3=""):
    if not _OLED:
        return
    _oled.fill(0)
    _oled.text("Sentinel AI", 0, 0)
    _oled.text(line1[:16], 0, 16)
    _oled.text(line2[:16], 0, 28)
    _oled.text(line3[:16], 0, 40)
    _oled.show()


# ── WiFi ──────────────────────────────────────────────────────────────────────
_wlan = network.WLAN(network.STA_IF)

def wifi_connect():
    _wlan.active(True)
    if _wlan.isconnected():
        return True
    print("[wifi] Connecting to", config.WIFI_SSID)
    oled_show("WiFi", "Connecting...", config.WIFI_SSID[:16])
    _wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    for _ in range(20):
        if _wlan.isconnected():
            ip = _wlan.ifconfig()[0]
            print("[wifi] Connected:", ip)
            oled_show("WiFi OK", ip, "")
            return True
        utime.sleep(1)
    print("[wifi] Failed to connect")
    oled_show("WiFi FAIL", "", "")
    return False


# ── LoRa (SX127x) ─────────────────────────────────────────────────────────────
_lora = None

def lora_init():
    global _lora
    try:
        from machine import SPI, Pin
        from sx127x import SX127x  # install: mip.install("sx127x") or copy driver
        spi = SPI(
            1,
            baudrate=10000000,
            sck=Pin(config.LORA_SCK),
            mosi=Pin(config.LORA_MOSI),
            miso=Pin(config.LORA_MISO),
        )
        _lora = SX127x(
            spi=spi,
            pins={"cs": config.LORA_CS, "rst": config.LORA_RST, "dio0": config.LORA_DIO0},
            parameters={
                "frequency": config.LORA_FREQUENCY,
                "bandwidth": config.LORA_BANDWIDTH,
                "spreading_factor": config.LORA_SPREADING_FACTOR,
                "coding_rate": config.LORA_CODING_RATE,
                "tx_power": config.LORA_TX_POWER,
            },
        )
        print("[lora] SX127x ready @", config.LORA_FREQUENCY / 1e6, "MHz")
        oled_show("LoRa OK", "{:.0f}MHz".format(config.LORA_FREQUENCY / 1e6), "")
        return True
    except Exception as e:
        print("[lora] Init failed:", e)
        return False


# ── Metrics collection ────────────────────────────────────────────────────────
def collect_metrics():
    """
    Collect lightweight metrics available on ESP32 MicroPython.
    On real hardware, read I2C sensors here (BME280, INA219, etc.).
    """
    gc.collect()
    free_ram = gc.mem_free()
    alloc_ram = gc.mem_alloc()
    total_ram = free_ram + alloc_ram
    mem_pct = round(alloc_ram / total_ram * 100, 1) if total_ram > 0 else 0

    freq_mhz = machine.freq() // 1_000_000

    metrics = {
        "cpu": {
            "cpu_percent": _read_cpu_load(),
            "cpu_freq_mhz": freq_mhz,
        },
        "memory": {
            "memory_percent": mem_pct,
            "memory_used_kb": alloc_ram // 1024,
            "memory_free_kb": free_ram // 1024,
        },
    }

    # WiFi RSSI (signal strength)
    if _wlan.isconnected():
        try:
            rssi = _wlan.status("rssi")
            metrics["network"] = {"wifi_rssi_dbm": rssi}
        except Exception:
            pass

    return metrics

# Simple CPU load proxy: time a tight loop and compare to ideal
_CALIBRATION = None

def _read_cpu_load():
    global _CALIBRATION
    iterations = 10_000
    start = utime.ticks_us()
    for _ in range(iterations):
        pass
    elapsed = utime.ticks_diff(utime.ticks_us(), start)
    if _CALIBRATION is None:
        _CALIBRATION = elapsed
        return 0.0
    # Ratio of actual vs baseline (higher elapsed = more load)
    ratio = _CALIBRATION / max(elapsed, 1)
    load = max(0.0, min(100.0, round((1 - ratio) * 100, 1)))
    return load


# ── Transport: WiFi (HTTP POST) ───────────────────────────────────────────────
def push_wifi(metrics):
    try:
        import urequests
        payload = ujson.dumps({
            "device_id": config.DEVICE_ID,
            "timestamp": utime.time(),
            "metrics": metrics,
        })
        url = config.HUB_URL.rstrip("/") + "/api/metrics/push"
        r = urequests.post(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        ok = r.status_code in (200, 201)
        r.close()
        return ok
    except Exception as e:
        print("[push] WiFi error:", e)
        return False


# ── Transport: LoRa radio ─────────────────────────────────────────────────────
def push_lora(metrics):
    if _lora is None:
        return False
    try:
        payload = ujson.dumps({
            "device_id": config.DEVICE_ID,
            "ts": utime.time(),
            "m": metrics,
        })
        _lora.println(payload)
        return True
    except Exception as e:
        print("[push] LoRa error:", e)
        return False


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    print("[main] Sentinel AI LoRa32 node v1.0")
    print("[main] Device ID:", config.DEVICE_ID)
    print("[main] Transport:", config.TRANSPORT)

    if config.TRANSPORT == "lora":
        lora_init()
    else:
        wifi_connect()

    # Register device with hub (WiFi mode only)
    if config.TRANSPORT == "wifi" and _wlan.isconnected():
        try:
            import urequests
            r = urequests.post(
                config.HUB_URL.rstrip("/") + "/api/devices/register",
                data=ujson.dumps({
                    "device_id": config.DEVICE_ID,
                    "device_type": "lora32-esp32",
                    "firmware": "micropython",
                }),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            r.close()
            print("[main] Registered with hub")
        except Exception as e:
            print("[main] Registration warning:", e)

    push_count = 0
    fail_count = 0

    while True:
        try:
            # Reconnect WiFi if dropped
            if config.TRANSPORT == "wifi" and not _wlan.isconnected():
                wifi_connect()

            metrics = collect_metrics()

            if config.TRANSPORT == "lora":
                ok = push_lora(metrics)
            else:
                ok = push_wifi(metrics)

            if ok:
                push_count += 1
                fail_count = 0
                status = "OK #{}".format(push_count)
            else:
                fail_count += 1
                status = "FAIL x{}".format(fail_count)

            cpu = metrics.get("cpu", {}).get("cpu_percent", 0)
            mem = metrics.get("memory", {}).get("memory_percent", 0)
            oled_show(
                "C:{:.0f}% M:{:.0f}%".format(cpu, mem),
                status,
                config.TRANSPORT.upper(),
            )
            print("[main] push={} cpu={} mem={}".format(status, cpu, mem))

        except Exception as e:
            print("[main] Loop error:", e)

        gc.collect()
        utime.sleep(config.PUSH_INTERVAL)


main()

"""
Sentinel AI — LoRa32 V3 MicroPython Client
Board: Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262)

Transport modes (set TRANSPORT in config.py):
  wifi   — HTTP POST directly to Sentinel hub (recommended)
  serial — JSON over USB serial → Pi lora_bridge.py forwards to hub
  lora   — LoRa radio → needs second LoRa receiver (last resort)

Flash to device:
  mpremote connect <PORT> cp config.py boot.py main.py :
  mpremote connect <PORT> reset
"""

import gc
import ujson
import utime
import machine
import network

import config

# ── OLED display ──────────────────────────────────────────────────────────────
_oled = None
_OLED = False

def _init_oled():
    global _oled, _OLED
    try:
        import ssd1306
        from machine import Pin, SoftI2C
        i2c = SoftI2C(scl=Pin(config.OLED_SCL), sda=Pin(config.OLED_SDA))
        _oled = ssd1306.SSD1306_I2C(config.OLED_WIDTH, config.OLED_HEIGHT, i2c)
        _OLED = True
    except Exception as e:
        print("[oled] Init failed:", e)

def oled_show(line1="", line2="", line3="", line4=""):
    if not _OLED or _oled is None:
        return
    try:
        _oled.fill(0)
        _oled.text("Sentinel AI", 0, 0)
        _oled.text(line1[:16], 0, 16)
        _oled.text(line2[:16], 0, 28)
        _oled.text(line3[:16], 0, 40)
        _oled.text(line4[:16], 0, 52)
        _oled.show()
    except Exception:
        pass


# ── WiFi ──────────────────────────────────────────────────────────────────────
_wlan = network.WLAN(network.STA_IF)

def wifi_connect():
    _wlan.active(True)
    if _wlan.isconnected():
        return True
    print("[wifi] Connecting to", config.WIFI_SSID)
    oled_show("WiFi", "Connecting...", config.WIFI_SSID[:16])
    _wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    for _ in range(25):
        if _wlan.isconnected():
            ip = _wlan.ifconfig()[0]
            print("[wifi] Connected:", ip)
            oled_show("WiFi OK", ip, "")
            return True
        utime.sleep(1)
    print("[wifi] Failed")
    oled_show("WiFi FAIL", "Check SSID/PWD", "")
    return False


# ── SX1262 LoRa radio (V3 chip — only used when TRANSPORT = "lora") ───────────
_lora = None

def lora_init():
    global _lora
    try:
        # sx1262 MicroPython driver — install via:
        # mpremote connect <PORT> mip install github:ehong-tl/micropySX126x
        from sx126x import SX1262
        from machine import SPI, Pin
        spi = SPI(
            1,
            baudrate=2000000,
            sck=Pin(config.LORA_SCK),
            mosi=Pin(config.LORA_MOSI),
            miso=Pin(config.LORA_MISO),
        )
        _lora = SX1262(
            spi=spi,
            cs=Pin(config.LORA_CS, Pin.OUT),
            irq=Pin(config.LORA_DIO1, Pin.IN),
            rst=Pin(config.LORA_RST, Pin.OUT),
            gpio=Pin(config.LORA_BUSY, Pin.IN),
        )
        _lora.begin(
            freq=config.LORA_FREQUENCY / 1e6,
            bw=config.LORA_BANDWIDTH / 1000,
            sf=config.LORA_SPREADING_FACTOR,
            cr=config.LORA_CODING_RATE,
            power=config.LORA_TX_POWER,
            syncWord=0x12,
        )
        print("[lora] SX1262 ready @ {:.0f} MHz".format(config.LORA_FREQUENCY / 1e6))
        oled_show("LoRa OK", "{:.0f}MHz".format(config.LORA_FREQUENCY / 1e6), "SF{}".format(config.LORA_SPREADING_FACTOR))
        return True
    except ImportError:
        print("[lora] sx126x driver not found — install: mpremote mip install github:ehong-tl/micropySX126x")
        return False
    except Exception as e:
        print("[lora] Init failed:", e)
        return False


# ── Sensors ───────────────────────────────────────────────────────────────────
_dht = None

def _init_sensors():
    global _dht
    try:
        import dht
        from machine import Pin
        _dht = dht.DHT22(Pin(config.DHT_PIN))
        print("[sensor] DHT22 ready on GPIO", config.DHT_PIN)
    except Exception as e:
        print("[sensor] DHT22 init failed:", e)

def _read_dht():
    if _dht is None:
        return None, None
    try:
        _dht.measure()
        return _dht.temperature(), _dht.humidity()
    except Exception:
        return None, None

def _read_voltage():
    try:
        adc = machine.ADC(machine.Pin(config.VOLTAGE_PIN))
        adc.atten(machine.ADC.ATTN_11DB)  # 0–3.6V range
        raw = adc.read_u16()
        # ESP32-S3: 16-bit ADC, 3.3V reference
        voltage = (raw / 65535.0) * 3.3 * 2  # ×2 for voltage divider
        return round(voltage, 3)
    except Exception:
        return None


# ── Metrics collection ────────────────────────────────────────────────────────
_cpu_calibration = None

def _read_cpu_load():
    global _cpu_calibration
    iterations = 10_000
    start = utime.ticks_us()
    for _ in range(iterations):
        pass
    elapsed = utime.ticks_diff(utime.ticks_us(), start)
    if _cpu_calibration is None:
        _cpu_calibration = elapsed
        return 0.0
    ratio = _cpu_calibration / max(elapsed, 1)
    return max(0.0, min(100.0, round((1 - ratio) * 100, 1)))

def collect_metrics():
    gc.collect()
    free_ram = gc.mem_free()
    alloc_ram = gc.mem_alloc()
    total_ram = free_ram + alloc_ram
    mem_pct = round(alloc_ram / total_ram * 100, 1) if total_ram > 0 else 0

    temp_c, humidity = _read_dht()
    voltage = _read_voltage()

    metrics = {
        "cpu": {
            "cpu_percent": _read_cpu_load(),
            "cpu_freq_mhz": machine.freq() // 1_000_000,
        },
        "memory": {
            "memory_percent": mem_pct,
            "memory_used_kb": alloc_ram // 1024,
            "memory_free_kb": free_ram // 1024,
        },
    }

    if temp_c is not None:
        metrics["sensor"] = {
            "temperature_c": round(temp_c, 1),
            "humidity_pct": round(humidity, 1),
        }

    if voltage is not None:
        metrics["power"] = {
            "power_voltage_v": voltage,
        }

    if _wlan.isconnected():
        try:
            rssi = _wlan.status("rssi")
            metrics["network"] = {"wifi_rssi_dbm": rssi}
        except Exception:
            pass

    return metrics


# ── Transport: WiFi HTTP POST ─────────────────────────────────────────────────
def push_wifi(metrics):
    try:
        import urequests
        payload = ujson.dumps({
            "device_id": config.DEVICE_ID,
            "timestamp": utime.time(),
            "metrics": metrics,
        })
        url = config.HUB_URL.rstrip("/") + "/api/metrics/push"
        r = urequests.post(url, data=payload, headers={"Content-Type": "application/json"}, timeout=6)
        ok = r.status_code in (200, 201)
        r.close()
        return ok
    except Exception as e:
        print("[push] WiFi error:", e)
        return False


# ── Transport: USB Serial (Pi reads and forwards) ─────────────────────────────
def push_serial(metrics):
    try:
        payload = ujson.dumps({
            "device_id": config.DEVICE_ID,
            "timestamp": utime.time(),
            "metrics": metrics,
        })
        print("SENTINEL:" + payload)  # Pi lora_bridge.py looks for this prefix
        return True
    except Exception as e:
        print("[push] Serial error:", e)
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
        _lora.send(payload.encode())
        return True
    except Exception as e:
        print("[push] LoRa error:", e)
        return False


# ── Hub registration ──────────────────────────────────────────────────────────
def register_with_hub():
    try:
        import urequests
        r = urequests.post(
            config.HUB_URL.rstrip("/") + "/api/devices/register",
            data=ujson.dumps({
                "device_id": config.DEVICE_ID,
                "hostname": config.DEVICE_ID,
                "platform": "MicroPython-ESP32S3",
                "version": "Heltec LoRa32 V3",
            }),
            headers={"Content-Type": "application/json"},
            timeout=6,
        )
        r.close()
        print("[main] Registered with hub")
        return True
    except Exception as e:
        print("[main] Registration warning:", e)
        return False


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    print("[main] Sentinel AI LoRa32 V3 node")
    print("[main] Device:", config.DEVICE_ID)
    print("[main] Transport:", config.TRANSPORT)

    _init_oled()
    _init_sensors()

    oled_show("Sentinel AI", "Starting...", config.TRANSPORT.upper())
    utime.sleep(1)

    if config.TRANSPORT == "lora":
        if not lora_init():
            print("[main] LoRa failed — falling back to serial")
            config.TRANSPORT = "serial"
    elif config.TRANSPORT == "wifi":
        if wifi_connect():
            register_with_hub()
        else:
            print("[main] WiFi failed — falling back to serial")
            config.TRANSPORT = "serial"

    push_count = 0
    fail_count = 0

    while True:
        try:
            if config.TRANSPORT == "wifi" and not _wlan.isconnected():
                wifi_connect()

            metrics = collect_metrics()

            if config.TRANSPORT == "lora":
                ok = push_lora(metrics)
            elif config.TRANSPORT == "serial":
                ok = push_serial(metrics)
            else:
                ok = push_wifi(metrics)

            if ok:
                push_count += 1
                fail_count = 0
                status = "OK #{}".format(push_count)
            else:
                fail_count += 1
                status = "ERR x{}".format(fail_count)

            cpu  = metrics.get("cpu", {}).get("cpu_percent", 0)
            mem  = metrics.get("memory", {}).get("memory_percent", 0)
            sens = metrics.get("sensor", {})
            t    = sens.get("temperature_c", "--")
            h    = sens.get("humidity_pct", "--")

            oled_show(
                "C:{:.0f}% M:{:.0f}%".format(cpu, mem),
                "T:{}C H:{}%".format(t, h),
                status,
                config.TRANSPORT.upper(),
            )
            print("[main] {} cpu={} mem={} T={} H={}".format(status, cpu, mem, t, h))

        except Exception as e:
            print("[main] Loop error:", e)

        gc.collect()
        utime.sleep(config.PUSH_INTERVAL)


main()

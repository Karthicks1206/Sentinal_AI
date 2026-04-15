/*
 * Sentinel AI — Arduino Sensor Node
 * Compatible: Arduino Uno R3, Uno R4 Minima, Uno R4 WiFi
 *
 * Sensors:
 *   DHT22 (or DHT11)  — temperature + humidity  → pin 2
 *   Voltage divider   — power voltage reading    → pin A0
 *   LDR (optional)    — light level              → pin A1
 *
 * Wiring — DHT22:
 *   Pin 1 (VCC)  → 5V
 *   Pin 2 (DATA) → Arduino D2  (with 10kΩ pull-up to 5V)
 *   Pin 4 (GND)  → GND
 *
 * Wiring — Voltage divider (to measure up to 10V):
 *   R1=30kΩ from V_in to A0
 *   R2=10kΩ from A0 to GND
 *   Factor: (R1+R2)/R2 = 4.0  →  A0 reads V_in/4
 *
 * Output: JSON over Serial at 9600 baud, prefixed with SENTINEL:
 *   SENTINEL:{"device_id":"arduino-r3","metrics":{"sensor":{"temperature_c":25.3,...}}}
 *
 * Install library via Arduino IDE Library Manager:
 *   "DHT sensor library" by Adafruit
 *   "Adafruit Unified Sensor" by Adafruit
 */

#include <DHT.h>

// ── Configuration ─────────────────────────────────────────────────────────────
#define DEVICE_ID       "arduino-r3"    // Change to "arduino-r4" for R4 board
#define DHT_PIN         2
#define DHT_TYPE        DHT22           // Change to DHT11 if using DHT11
#define VOLTAGE_PIN     A0
#define LIGHT_PIN       A1
#define PUSH_INTERVAL   5000            // ms between readings
#define VOLTAGE_DIVIDER 4.0             // (R1+R2)/R2 ratio

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastSend = 0;
bool dhtReady = false;

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  while (!Serial) { delay(10); }  // Wait for serial on R4

  dht.begin();
  delay(2000);  // DHT22 needs 2s after power-on

  // Test DHT
  float t = dht.readTemperature();
  dhtReady = !isnan(t);

  Serial.println("[sentinel] Arduino sensor node started");
  Serial.print("[sentinel] DHT22: ");
  Serial.println(dhtReady ? "OK" : "FAIL (check wiring)");
  Serial.print("[sentinel] Device: ");
  Serial.println(DEVICE_ID);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
float readVoltage() {
  int raw = analogRead(VOLTAGE_PIN);
  // Arduino ADC: 10-bit, 5V reference
  float v = (raw / 1023.0) * 5.0 * VOLTAGE_DIVIDER;
  return round(v * 100.0) / 100.0;
}

int readLight() {
  // LDR: 0 (dark) → 1023 (bright), scale to 0-100%
  int raw = analogRead(LIGHT_PIN);
  return map(raw, 0, 1023, 0, 100);
}

// ── JSON builder (no library needed) ─────────────────────────────────────────
void sendMetrics(float tempC, float humidity, float voltage, int light) {
  Serial.print("SENTINEL:{");
  Serial.print("\"device_id\":\""); Serial.print(DEVICE_ID); Serial.print("\",");
  Serial.print("\"timestamp\":"); Serial.print(millis() / 1000); Serial.print(",");
  Serial.print("\"metrics\":{");

  // Sensor block
  Serial.print("\"sensor\":{");
  if (!isnan(tempC)) {
    Serial.print("\"temperature_c\":"); Serial.print(tempC, 1); Serial.print(",");
    Serial.print("\"humidity_pct\":"); Serial.print(humidity, 1);
  } else {
    Serial.print("\"temperature_c\":null,\"humidity_pct\":null");
  }
  Serial.print("},");

  // Power block
  Serial.print("\"power\":{");
  Serial.print("\"power_voltage_v\":"); Serial.print(voltage, 2);
  Serial.print("},");

  // Light / environment block
  Serial.print("\"environment\":{");
  Serial.print("\"light_pct\":"); Serial.print(light);
  Serial.print("},");

  // Uptime
  Serial.print("\"system\":{");
  Serial.print("\"uptime_s\":"); Serial.print(millis() / 1000);
  Serial.print("}");

  Serial.print("}}");
  Serial.println();  // newline terminates the packet
}

// ── Main loop ─────────────────────────────────────────────────────────────────
void loop() {
  if (millis() - lastSend >= PUSH_INTERVAL) {
    lastSend = millis();

    float tempC    = dht.readTemperature();
    float humidity = dht.readHumidity();
    float voltage  = readVoltage();
    int   light    = readLight();

    sendMetrics(tempC, humidity, voltage, light);
  }
}

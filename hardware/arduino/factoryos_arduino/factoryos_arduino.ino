// FactoryOS UNO R3: DHT11 module on D2, tilt switch D3-to-GND.
// DHT library: "DHT sensor library" by Adafruit and "Adafruit Unified Sensor".
// DHT modules labeled S/+/-: S->D2, +->5V, -->GND.
// If yours is a 4-pin bare sensor, check its pinout and add the appropriate pull-up.
#include <DHT.h>

#define DHT_PIN 2
#define DHT_TYPE DHT11
#define TILT_PIN 3
#define GREEN_LED 8
#define RED_LED 9

DHT dht(DHT_PIN, DHT_TYPE);

void setup() {
  Serial.begin(9600);
  pinMode(TILT_PIN, INPUT_PULLUP);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(RED_LED, OUTPUT);
  dht.begin();
}

void loop() {
  float temp = dht.readTemperature();
  float humidity = dht.readHumidity();
  if (isnan(temp) || isnan(humidity)) {
    delay(2000);
    return;
  }
  // Switch CLOSED to GND => simulated cooling fault.
  bool coolingFault = digitalRead(TILT_PIN) == LOW;
  digitalWrite(GREEN_LED, coolingFault ? LOW : HIGH);
  digitalWrite(RED_LED, coolingFault ? HIGH : LOW);
  digitalWrite(LED_BUILTIN, coolingFault ? HIGH : LOW);
  Serial.print("{\"temperature_c\":");
  Serial.print(temp, 1);
  Serial.print(",\"humidity_pct\":");
  Serial.print(humidity, 1);
  Serial.print(",\"cooling_fault\":");
  Serial.print(coolingFault ? "true" : "false");
  Serial.println("}");
  delay(2000);  // DHT11 needs >= ~2s between readings
}

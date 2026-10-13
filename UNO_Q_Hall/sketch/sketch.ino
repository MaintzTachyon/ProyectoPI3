#include <Arduino_RouterBridge.h>

// KY-024: VCC=3.3V, GND=GND, AO=A0, DO=D2.
// Empaquetar ADC de 12 bits y DO en un entero para una sola llamada RPC.
int read_hall() {
  int analog = analogRead(A0);
  return (analog << 1) | digitalRead(2);
}

void setup() {
  pinMode(A0, INPUT);
  pinMode(2, INPUT);
  analogReadResolution(12);
  Bridge.begin();
  Bridge.provide_safe("read_hall", read_hall);
}

void loop() {}

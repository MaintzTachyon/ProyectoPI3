"""Registrador KY-024 / SS49E para Arduino UNO Q (Python 3 / App Lab).

Conectar VCC a 3.3V, GND a GND, AO a A0 y DO a D2. No conectar salidas
alimentadas a 5V directamente a las entradas del UNO Q.

Uso: copiar este archivo al apartado Python (python/main.py) de la app
hall-ky024 y usar UNO_Q_Hall/sketch/sketch.ino como sketch. Pulsar Run en
Arduino App Lab con el UNO Q conectado por USB-C. Python corre en el Linux
de la placa y consulta el microcontrolador mediante Bridge; no se ejecuta
con MicroPython ni abriendo /dev/ttyACM0 desde la laptop.

El CSV se guarda en data/datos_hall.csv de la app, en el UNO Q. Para copiarlo
por USB-C a la laptop, con ADB instalado:
    adb -s 1844505359 pull /home/arduino/ArduinoApps/hall-ky024/data/datos_hall.csv .

Primera lectura tras 1 segundo y luego cada 600 segundos. Para pruebas,
cambiar INTERVALO_SEGUNDOS a 1. Cada fila resume 20 lecturas breves, no todo
el intervalo. El potenciometro ajusta el umbral de DO; se registra su nivel
0/1 sin asumir polaridad de deteccion. ADC de 12 bits: 0..4095. No se calcula
voltaje ni gauss sin calibracion. La fecha UTC procede del reloj de la placa;
verificar que este ajustado. El tiempo transcurrido usa reloj monotono.

Dependencia: arduino.app_utils, proporcionada por Arduino App Lab en la placa.
No instalar paquetes llamados 'arduino' con pip en la laptop.
Referencia: https://docs.arduino.cc/tutorials/uno-q/user-manual/
"""

import csv
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

INTERVALO_SEGUNDOS = 600
MUESTRAS = 20
PAUSA_MUESTRA_SEGUNDOS = 0.01
# Al instalar como python/main.py, data queda dentro de la carpeta de la app.
ARCHIVO_CSV = Path(__file__).resolve().parent.parent / "data" / "datos_hall.csv"
CABECERA = [
    "sesion", "registro", "fecha_utc_reloj_placa", "segundos_sesion",
    "adc_12bits_promedio", "adc_12bits_min", "adc_12bits_max",
    "digital_ultimo", "digital_altos", "muestras", "estado",
]


def leer_sensor(bridge):
    total = altos = 0
    minimo, maximo = 4095, 0
    for indice in range(MUESTRAS):
        valor = bridge.call("read_hall")
        if type(valor) is not int or not 0 <= valor <= 8191:
            raise ValueError("Respuesta read_hall invalida: %r" % (valor,))
        analogico, digital = valor >> 1, valor & 1
        total += analogico
        altos += digital
        minimo, maximo = min(minimo, analogico), max(maximo, analogico)
        if indice < MUESTRAS - 1:
            time.sleep(PAUSA_MUESTRA_SEGUNDOS)
    estado = "limite_adc" if minimo == 0 or maximo == 4095 else "ok"
    return [round(total / MUESTRAS, 2), minimo, maximo,
            digital, altos, MUESTRAS, estado]


def preparar_csv(ruta):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists() or ruta.stat().st_size == 0:
        with ruta.open("w", newline="", encoding="utf-8") as archivo:
            csv.writer(archivo).writerow(CABECERA)
        return
    with ruta.open(newline="", encoding="utf-8") as archivo:
        if next(csv.reader(archivo), None) != CABECERA:
            raise ValueError("CSV incompatible: archivar el existente o cambiar ARCHIVO_CSV")
    with ruta.open("rb") as archivo:
        archivo.seek(-1, os.SEEK_END)
        incompleta = archivo.read(1) != b"\n"
    if incompleta:
        with ruta.open("a", encoding="utf-8") as archivo:
            archivo.write("\n")
        print("Aviso: la ultima fila anterior estaba incompleta; revisarla.", flush=True)


def guardar_registro(ruta, fila):
    with ruta.open("a", newline="", encoding="utf-8") as archivo:
        csv.writer(archivo).writerow(fila)
        archivo.flush()
        os.fsync(archivo.fileno())


class RegistradorHall:
    def __init__(self, bridge, ruta=ARCHIVO_CSV):
        if not math.isfinite(INTERVALO_SEGUNDOS) or INTERVALO_SEGUNDOS <= 0:
            raise ValueError("INTERVALO_SEGUNDOS debe ser positivo y finito")
        if type(MUESTRAS) is not int or MUESTRAS < 1:
            raise ValueError("MUESTRAS debe ser un entero positivo")
        if not math.isfinite(PAUSA_MUESTRA_SEGUNDOS) or PAUSA_MUESTRA_SEGUNDOS < 0:
            raise ValueError("PAUSA_MUESTRA_SEGUNDOS debe ser finita y no negativa")
        self.bridge = bridge
        self.ruta = Path(ruta)
        preparar_csv(self.ruta)
        self.sesion = uuid.uuid4().hex
        self.registro = 0
        self.inicio = time.monotonic()
        self.proximo = self.inicio + 1

    def loop(self):
        ahora = time.monotonic()
        if ahora < self.proximo:
            time.sleep(min(0.2, self.proximo - ahora))
            return
        self.registro += 1
        fecha = datetime.now(timezone.utc).isoformat()
        try:
            lectura = leer_sensor(self.bridge)
        except Exception as error:
            # Descartar ventanas incompletas, sin inventar ceros ni mediciones.
            detalle = str(error).replace("\r", " ").replace("\n", " ")
            lectura = ["", "", "", "", "", "", "error: " + detalle]
        fila = [self.sesion, self.registro, fecha,
                round(ahora - self.inicio, 3)] + lectura
        # Los errores de disco se propagan para evitar anunciar datos no guardados.
        guardar_registro(self.ruta, fila)
        print(fila, flush=True)
        self.proximo += INTERVALO_SEGUNDOS
        ahora = time.monotonic()
        if self.proximo <= ahora:
            self.proximo += (int((ahora - self.proximo) // INTERVALO_SEGUNDOS) + 1) * INTERVALO_SEGUNDOS


def main():
    try:
        from arduino.app_utils import App, Bridge
    except ImportError as error:
        raise SystemExit(
            "Ejecuta este programa en Arduino App Lab sobre el UNO Q, "
            "junto con UNO_Q_Hall/sketch/sketch.ino."
        ) from error
    registrador = RegistradorHall(Bridge)
    print("CSV:", registrador.ruta, "| Intervalo:", INTERVALO_SEGUNDOS, "s", flush=True)
    try:
        App.run(user_loop=registrador.loop)
    except KeyboardInterrupt:
        print("Registro detenido. CSV conservado en", registrador.ruta)


if __name__ == "__main__":
    main()

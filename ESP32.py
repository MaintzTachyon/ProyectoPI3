"""Registrador de CO2 para ESP32 con MicroPython y Winsen MH-Z1911A.

Copiar a la placa como main.py para iniciar al encender, o ejecutar ESP32.py
desde Thonny. El CSV se guarda en la memoria de la placa; descargarlo desde
Thonny. No requiere Wi-Fi ni paquetes adicionales. Detener con Ctrl+C.

Cableado (ESP32 clasico; ajustar GPIO si la placa es otra variante):
    TX del sensor -> GPIO16 (RX del ESP32)
    RX del sensor -> GPIO17 (TX del ESP32)
    Vin del sensor -> fuente regulada de 5.0 V (+/-0.1 V), minimo 150 mA
    GND del sensor -> GND de la fuente y del ESP32
Dejar HD y PWM sin conectar. Si existe R/T, seleccionar UART con nivel
alto de 3.3 V antes de alimentar el sensor (manual v1.3).

Se usa el protocolo UART MH-Z19: 9600 8N1, consulta 0x86. El manual publico
MH-Z1911A v1.1 no detalla las tramas UART: confirmar compatibilidad con la
revision del sensor si no responde. No se envian comandos de calibracion.
Referencias:
https://www.winsen-sensor.com/d/files/manual/mh-z1911a.pdf
https://www.winsen-sensor.com/d/files/infrared-gas-sensor/mh-z19/mh-z19-co2-manual(ver1_0).pdf

Se toma una muestra tras el calentamiento y luego cada 10 minutos, de forma
indefinida (no es un promedio del intervalo). Se agrega una fila por ciclo,
incluso si falla la lectura. Cada ejecucion tiene un identificador de sesion.
La fecha queda vacia salvo que RTC_CONFIGURADO sea True: ajustar antes el
RTC de la placa con machine.RTC().datetime(...). Los segundos transcurridos
se registran siempre. Descargar el CSV periodicamente para liberar espacio.
"""

import os
import time
from machine import Pin, UART
from ubinascii import hexlify


UART_ID = 2
PIN_RX = 16
PIN_TX = 17
INTERVALO_SEGUNDOS = 10 * 60
CALENTAMIENTO_SEGUNDOS = 60
TIMEOUT_MS = 2000
INTENTOS = 3
ARCHIVO_CSV = "datos_co2.csv"
RTC_CONFIGURADO = False

COMANDO_CO2 = b"\xff\x01\x86\x00\x00\x00\x00\x00\x79"
CABECERA = "sesion,registro,fecha_hora,segundos_sesion,co2_ppm,estado,trama_hex\n"


def leer_co2(uart):
    """Recibir tramas parciales, descartar ruido y validar checksum."""
    # Vaciar bytes anteriores sin esperar indefinidamente.
    pendientes = uart.any()
    if pendientes:
        uart.read(pendientes)
    if uart.write(COMANDO_CO2) != len(COMANDO_CO2):
        raise OSError("envio_incompleto")
    inicio = time.ticks_ms()
    buffer = bytearray()
    while time.ticks_diff(time.ticks_ms(), inicio) < TIMEOUT_MS:
        bloque = uart.read(32)
        if bloque:
            buffer.extend(bloque)
            while len(buffer) >= 9:
                if buffer[0] != 0xFF or buffer[1] != 0x86:
                    del buffer[0]
                    continue
                trama = bytes(buffer[:9])
                if ((-sum(trama[1:8])) & 0xFF) != trama[8]:
                    del buffer[0]
                    continue
                ppm = trama[2] * 256 + trama[3]
                return ppm, hexlify(trama).decode()
        time.sleep_ms(10)
    raise OSError("sin_respuesta_valida")


def preparar_csv():
    try:
        tamano = os.stat(ARCHIVO_CSV)[6]
    except OSError as error:
        if error.args[0] != 2:  # Solo crear si no existe; propagar otros errores.
            raise
        tamano = 0
    if tamano == 0:
        with open(ARCHIVO_CSV, "w") as archivo:
            archivo.write(CABECERA)
    else:
        with open(ARCHIVO_CSV, "r") as archivo:
            if archivo.readline() != CABECERA:
                raise ValueError("El CSV existente tiene otra cabecera")
        # Separar una posible ultima fila incompleta tras un corte de energia.
        with open(ARCHIVO_CSV, "rb") as archivo:
            archivo.seek(tamano - 1)
            incompleta = archivo.read(1) != b"\n"
        if incompleta:
            with open(ARCHIVO_CSV, "a") as archivo:
                archivo.write("\n")


def fecha_hora():
    if not RTC_CONFIGURADO:
        return ""
    return "%04d-%02d-%02dT%02d:%02d:%02d" % time.localtime()[:6]


def campo_csv(valor):
    texto = str(valor)
    return '"' + texto.replace('"', '""') + '"'


def guardar_registro(campos):
    # Cerrar en cada ciclo evita mantener los datos pendientes en un buffer.
    with open(ARCHIVO_CSV, "a") as archivo:
        archivo.write(",".join(campo_csv(campo) for campo in campos) + "\n")
        archivo.flush()
    if hasattr(os, "sync"):
        os.sync()


def main():
    preparar_csv()
    sesion = hexlify(os.urandom(8)).decode()
    uart = UART(UART_ID, baudrate=9600, bits=8, parity=None, stop=1,
                rx=Pin(PIN_RX), tx=Pin(PIN_TX), timeout=50)
    ultimo_tick = time.ticks_ms()
    transcurrido_ms = 0
    siguiente_ms = CALENTAMIENTO_SEGUNDOS * 1000
    registro = 0
    print("Calentando sensor durante", CALENTAMIENTO_SEGUNDOS, "segundos...")
    print("CSV:", ARCHIVO_CSV, "| Sesion:", sesion)
    try:
        while True:
            # Acumular diferencias cortas permite soportar el rollover de ticks.
            ahora = time.ticks_ms()
            transcurrido_ms += time.ticks_diff(ahora, ultimo_tick)
            ultimo_tick = ahora
            if transcurrido_ms < siguiente_ms:
                time.sleep_ms(min(500, siguiente_ms - transcurrido_ms))
                continue
            registro += 1
            fecha = fecha_hora()
            segundos = transcurrido_ms // 1000
            ppm, trama, estado = "", "", "error"
            for intento in range(INTENTOS):
                try:
                    ppm, trama = leer_co2(uart)
                    estado = "ok"
                    break
                except OSError as error:
                    estado = "error: " + str(error)
                    if intento < INTENTOS - 1:
                        time.sleep_ms(1000)
            guardar_registro((sesion, registro, fecha, segundos,
                              ppm, estado, trama))
            print("Registro", registro, "| CO2:", ppm, "ppm |", estado)
            siguiente_ms += INTERVALO_SEGUNDOS * 1000
    except KeyboardInterrupt:
        print("Registro detenido. Datos guardados en", ARCHIVO_CSV)
    except OSError as error:
        print("No se pudo guardar el CSV. Revisar espacio y almacenamiento:", error)
        raise
    finally:
        uart.deinit()


if __name__ == "__main__":
    main()

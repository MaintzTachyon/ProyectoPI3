"""Registrador CSV del detector de humo WiFi Tuya (Naylamp ID 4365).

Se ejecuta en la laptop (o cualquier PC con Python 3.8+) conectada a la
misma red WiFi que el detector. Requiere: pip install tinytuya

"ID:4365" de la caja es el codigo de producto de la tienda, no el ID Tuya.
El ID Tuya (device_id, ~20 caracteres) aparece en la app Smart Life / Tuya
Smart: detector > lapiz (editar) > Informacion del dispositivo > ID virtual.

Pasos:
  1. Emparejar el detector con la app Smart Life en una red WiFi de 2.4 GHz.
  2. Copiar tuya_config.example.json a tuya_config.json y completar device_id.
  3. python humo_tuya.py buscar      (detecta el detector en la red WiFi)
  4. python humo_tuya.py leer        (una lectura de prueba, sin CSV)
  5. python humo_tuya.py registrar   (escribe datos/datos_humo.csv)

El detector funciona con bateria: duerme y solo se conecta al WiFi al
encenderse, al pulsar el boton de prueba o al detectar humo. Por eso:
  - "buscar" solo lo ve si esta despierto: pulsar el boton durante el escaneo.
  - La lectura local (local_key) casi siempre falla mientras duerme; la
    fuente fiable es la nube de Tuya (api_key/api_secret de un proyecto en
    https://platform.tuya.com vinculado a la cuenta de la app). La nube
    conserva el ultimo estado reportado y el historial de eventos, de modo
    que una alarma ocurrida entre dos registros se cuenta igualmente en
    eventos_alarma_intervalo.
Si no hay credenciales de nube, solo se usa la lectura local por WiFi.

Cada fila del CSV corresponde a un ciclo, incluso si la lectura falla
(campos vacios y estado "error: ..."). dps_json guarda los datos crudos
para verificar el mapeo de codigos con el modelo concreto.
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

INTERVALO_SEGUNDOS = 300
ESCANEO_SEGUNDOS = 18
ROOT = Path(__file__).resolve().parent
ARCHIVO_CONFIG = ROOT / "tuya_config.json"
ARCHIVO_CSV = ROOT / "datos" / "datos_humo.csv"
CABECERA = [
    "sesion", "registro", "fecha_utc", "segundos_sesion", "fuente",
    "en_linea", "humo_estado", "alarma", "bateria_estado",
    "bateria_porcentaje", "eventos_alarma_intervalo", "dps_json", "estado",
]

# Codigos estandar de la categoria Tuya "ywbj" (detector de humo).
CODIGOS_HUMO = ("smoke_sensor_status", "smoke_sensor_state")
CODIGOS_BATERIA_ESTADO = ("battery_state",)
CODIGOS_BATERIA_PORCENTAJE = ("battery_percentage", "battery_value", "va_battery")
# DPs locales habituales del mismo esquema. Verificar con dps_json.
DPS_LOCALES = {"1": "smoke_sensor_status", "2": "smoke_sensor_value",
               "14": "battery_state", "15": "battery_percentage", "16": "muffling"}


def cargar_config(ruta=ARCHIVO_CONFIG):
    config = {}
    if ruta.exists():
        with ruta.open(encoding="utf-8") as archivo:
            config = json.load(archivo)
    # Las variables de entorno permiten no guardar secretos en disco.
    for clave in ("device_id", "local_key", "ip", "version",
                  "api_region", "api_key", "api_secret"):
        valor = os.environ.get("TUYA_" + clave.upper())
        if valor:
            config[clave] = valor
    if not config.get("device_id"):
        raise SystemExit("Falta device_id: completar %s (ver tuya_config.example.json)" % ruta.name)
    return config


def importar_tinytuya():
    try:
        import tinytuya
    except ImportError as error:
        raise SystemExit("Falta tinytuya. Instalar con: python -m pip install tinytuya") from error
    return tinytuya


def es_alarma(valor):
    # smoke_sensor_status: "alarm"/"normal"; smoke_sensor_state: "1"=alarma, "2"=normal.
    return str(valor).strip().lower() in ("alarm", "1", "true")


def primer_valor(datos, codigos):
    for codigo in codigos:
        if codigo in datos:
            return datos[codigo]
    return ""


class LectorHumo:
    def __init__(self, config):
        self.tinytuya = importar_tinytuya()
        self.config = config
        self.device_id = config["device_id"]
        self.cloud = None
        self.dispositivo = None
        if config.get("api_key") and config.get("api_secret"):
            self.cloud = self.tinytuya.Cloud(
                apiRegion=config.get("api_region", "us"), apiKey=config["api_key"],
                apiSecret=config["api_secret"], apiDeviceID=self.device_id)
            if self.cloud.error:
                raise SystemExit("No se pudo conectar con la nube Tuya: %s" % (self.cloud.error,))
        elif not config.get("local_key"):
            raise SystemExit("Configurar api_key/api_secret (nube) o local_key (lectura local).")

    def leer_local(self):
        """Lectura directa por WiFi. ip vacia o "Auto" busca el detector por su ID."""
        if self.dispositivo is None:
            ip = self.config.get("ip") or "Auto"
            dispositivo = self.tinytuya.Device(
                self.device_id, address=ip, local_key=self.config["local_key"],
                version=float(self.config.get("version") or 3.3),
                connection_timeout=3, connection_retry_limit=1)
            self.dispositivo = dispositivo
        respuesta = self.dispositivo.status()
        if not respuesta or "dps" not in respuesta:
            # Si la IP cambio (DHCP), volver a buscarla en el siguiente ciclo.
            self.dispositivo = None
            raise RuntimeError("local: %s" % ((respuesta or {}).get("Error", "sin respuesta"),))
        dps = {str(k): v for k, v in respuesta["dps"].items()}
        datos = {DPS_LOCALES.get(k, "dp_" + k): v for k, v in dps.items()}
        return True, datos, dps

    def leer_nube(self):
        respuesta = self.cloud.cloudrequest("/v1.0/devices/%s" % self.device_id)
        if not respuesta or not respuesta.get("success"):
            respuesta = respuesta or {}
            raise RuntimeError("nube: %s" % (respuesta.get("msg") or respuesta.get("Error") or "sin respuesta",))
        resultado = respuesta["result"]
        estado = {item["code"]: item["value"] for item in resultado.get("status", [])}
        return bool(resultado.get("online")), estado, estado

    def contar_alarmas(self, desde_ms, hasta_ms):
        """Eventos de alarma reportados a la nube en [desde_ms, hasta_ms)."""
        total = 0
        fila_siguiente = None
        for _ in range(20):  # limite de paginas por ciclo
            consulta = {"type": 7, "start_time": desde_ms, "end_time": hasta_ms, "size": 100}
            if fila_siguiente:
                consulta["start_row_key"] = fila_siguiente
            respuesta = self.cloud.cloudrequest("/v1.0/devices/%s/logs" % self.device_id, query=consulta)
            if not respuesta or not respuesta.get("success"):
                respuesta = respuesta or {}
                raise RuntimeError("historial: %s" % (respuesta.get("msg") or respuesta.get("Error") or "sin respuesta",))
            resultado = respuesta.get("result") or {}
            total += sum(1 for log in resultado.get("logs", [])
                         if log.get("code") in CODIGOS_HUMO and es_alarma(log.get("value")))
            fila_siguiente = resultado.get("next_row_key")
            if not resultado.get("has_next") or not fila_siguiente:
                break
        return total

    def leer(self):
        """Devuelve (fuente, en_linea, datos_por_codigo, dps_crudos)."""
        errores = []
        if self.config.get("local_key"):
            try:
                return ("local",) + self.leer_local()
            except Exception as error:  # el detector suele estar dormido
                errores.append(str(error))
        if self.cloud:
            try:
                return ("nube",) + self.leer_nube()
            except Exception as error:
                errores.append(str(error))
        raise RuntimeError("; ".join(errores))


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
        with ruta.open("a", encoding="utf-8", newline="") as archivo:
            archivo.write("\r\n")
        print("Aviso: la ultima fila anterior estaba incompleta; revisarla.", flush=True)


def guardar_registro(ruta, fila):
    with ruta.open("a", newline="", encoding="utf-8") as archivo:
        csv.writer(archivo).writerow(fila)
        archivo.flush()
        os.fsync(archivo.fileno())


def limpiar(texto):
    return str(texto).replace("\r", " ").replace("\n", " ")


class RegistradorHumo:
    def __init__(self, lector, ruta=ARCHIVO_CSV, intervalo=INTERVALO_SEGUNDOS):
        if not math.isfinite(intervalo) or intervalo <= 0:
            raise ValueError("El intervalo debe ser positivo y finito")
        self.lector = lector
        self.ruta = Path(ruta)
        self.intervalo = intervalo
        preparar_csv(self.ruta)
        self.sesion = uuid.uuid4().hex
        self.registro = 0
        self.inicio = time.monotonic()
        self.proximo = self.inicio + 1
        self.ultimo_log_ms = int(time.time() * 1000)

    def ciclo(self):
        ahora = time.monotonic()
        self.registro += 1
        fecha = datetime.now(timezone.utc).isoformat()
        estados = []
        try:
            fuente, en_linea, datos, dps = self.lector.leer()
            humo = primer_valor(datos, CODIGOS_HUMO)
            lectura = [fuente, int(en_linea), humo,
                       int(es_alarma(humo)) if humo != "" else "",
                       primer_valor(datos, CODIGOS_BATERIA_ESTADO),
                       primer_valor(datos, CODIGOS_BATERIA_PORCENTAJE)]
            crudo = json.dumps(dps, ensure_ascii=False, sort_keys=True)
            if humo == "":
                estados.append("sin_codigo_humo")
        except Exception as error:
            # No inventar valores: la fila queda vacia con el motivo del fallo.
            lectura, crudo = ["", "", "", "", "", ""], ""
            estados.append("error: " + limpiar(error))
        eventos = ""
        if self.lector.cloud:
            hasta_ms = int(time.time() * 1000)
            try:
                eventos = self.lector.contar_alarmas(self.ultimo_log_ms, hasta_ms)
                self.ultimo_log_ms = hasta_ms
            except Exception as error:
                # Se reintenta el mismo intervalo en el siguiente ciclo.
                estados.append("error: " + limpiar(error))
        fila = ([self.sesion, self.registro, fecha, round(ahora - self.inicio, 3)]
                + lectura + [eventos, crudo, " | ".join(estados) or "ok"])
        guardar_registro(self.ruta, fila)
        print(dict(zip(CABECERA, fila)), flush=True)

    def ejecutar(self):
        while True:
            ahora = time.monotonic()
            if ahora < self.proximo:
                time.sleep(min(1.0, self.proximo - ahora))
                continue
            self.ciclo()
            self.proximo += self.intervalo
            ahora = time.monotonic()
            if self.proximo <= ahora:
                self.proximo += (int((ahora - self.proximo) // self.intervalo) + 1) * self.intervalo


def buscar(config):
    """Detecta dispositivos Tuya en la red WiFi local (difusion UDP 6666/6667/7000)."""
    tinytuya = importar_tinytuya()
    print("Escaneando la red WiFi %d s. Pulsar ahora el boton de prueba del detector "
          "para despertarlo..." % ESCANEO_SEGUNDOS, flush=True)
    encontrados = tinytuya.deviceScan(verbose=False, maxretry=ESCANEO_SEGUNDOS,
                                      color=False, poll=False, byID=True)
    for dev_id, info in encontrados.items():
        marca = "  <== detector configurado" if dev_id == config["device_id"] else ""
        print("%s  ip=%s  version=%s  producto=%s%s" % (
            dev_id, info.get("ip"), info.get("version"), info.get("productKey", ""), marca))
    if config["device_id"] in encontrados:
        info = encontrados[config["device_id"]]
        print("\nDetector encontrado en %s (protocolo %s). Se puede guardar en "
              "tuya_config.json como ip/version." % (info.get("ip"), info.get("version")))
        return 0
    print("\nNo se detecto el device_id %s en la red local. Verificar que el PC este en la "
          "misma red WiFi, que el firewall permita UDP 6666/6667/7000 y repetir pulsando "
          "el boton de prueba." % config["device_id"])
    if config.get("api_key") and config.get("api_secret"):
        try:
            lector = LectorHumo(config)
            en_linea, _, _ = lector.leer_nube()
            print("La nube Tuya si reconoce el detector (en_linea=%s)." % en_linea)
        except Exception as error:
            print("Tampoco se pudo consultar en la nube:", error)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Detector de humo Tuya WiFi -> CSV")
    parser.add_argument("accion", choices=["buscar", "leer", "registrar"])
    parser.add_argument("--intervalo", type=float, default=INTERVALO_SEGUNDOS,
                        help="segundos entre registros (por defecto %(default)s)")
    parser.add_argument("--csv", type=Path, default=ARCHIVO_CSV)
    args = parser.parse_args()
    config = cargar_config()
    if args.accion == "buscar":
        return buscar(config)
    lector = LectorHumo(config)
    if args.accion == "leer":
        fuente, en_linea, datos, dps = lector.leer()
        print("fuente=%s en_linea=%s" % (fuente, en_linea))
        print(json.dumps(datos, indent=2, ensure_ascii=False))
        return 0
    registrador = RegistradorHumo(lector, args.csv, args.intervalo)
    print("CSV:", registrador.ruta, "| Intervalo:", args.intervalo, "s", flush=True)
    try:
        registrador.ejecutar()
    except KeyboardInterrupt:
        print("Registro detenido. CSV conservado en", registrador.ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())

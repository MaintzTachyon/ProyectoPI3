"""Control de App Lab por USB-C desde VS Code. Solo requiere Python 3 y ADB."""
import argparse
import csv
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REMOTE = "/home/arduino/ArduinoApps/hall-ky024"
LOCAL_CSV = ROOT / "datos" / "datos_hall.csv"


def find_adb():
    candidate = os.environ.get("ADB") or shutil.which("adb")
    if candidate:
        return candidate
    # Copias locales: adb (Linux/macOS) o adb.exe (Windows, platform-tools).
    for name in ("adb", "adb.exe", "platform-tools/adb", "platform-tools/adb.exe"):
        local = ROOT / ".tools" / "adb" / name
        if local.is_file():
            return str(local)
    raise RuntimeError("No se encontro ADB. Instalar platform-tools/android-tools o definir ADB con su ruta.")


def run(args, capture=False, timeout=120):
    # UTF-8 explicito: en Windows la codificacion por defecto no es UTF-8.
    return subprocess.run(args, check=True, text=True, encoding="utf-8", errors="replace",
                          capture_output=capture, timeout=timeout)


class UnoQ:
    def __init__(self, serial=None):
        adb = find_adb()
        devices = run([adb, "devices"], capture=True).stdout.splitlines()[1:]
        ready = [line.split()[0] for line in devices if len(line.split()) >= 2 and line.split()[1] == "device"]
        serial = serial or os.environ.get("UNO_Q_SERIAL", "1844505359")
        if serial not in ready:
            raise RuntimeError("UNO Q %s no disponible por ADB. Revisar cable USB-C de datos y esperar el arranque.\n%s" % (serial, "\n".join(devices)))
        self.command = [adb, "-s", serial]

    def shell(self, *args, capture=False, timeout=120):
        # ADB puede heredar /data/local/tmp, inexistente en Debian del UNO Q.
        return run(self.command + ["shell", shlex.join(["env", "TMPDIR=/tmp", *args])], capture, timeout)

    def status(self):
        self.shell("uname", "-n")
        self.shell("arduino-app-cli", "app", "list")

    def deploy(self):
        # KY024.py es la fuente que se edita en VS Code.
        shutil.copyfile(ROOT / "KY024.py", ROOT / "UNO_Q_Hall/python/main.py")
        self.shell("mkdir", "-p", REMOTE + "/python", REMOTE + "/sketch")
        for name in ("app.yaml", "python/main.py", "sketch/sketch.ino", "sketch/sketch.yaml"):
            run(self.command + ["push", str(ROOT / "UNO_Q_Hall" / name), REMOTE + "/" + name])
        print("Codigo enviado. El CSV existente se conserva.")

    def app(self, action):
        self.shell("arduino-app-cli", "app", action, REMOTE, timeout=None)

    def fetch(self):
        # Una lectura en vivo puede terminar a mitad de fila. Conservar solo
        # lineas completas; el programa de la placa produce filas de una linea.
        result = self.shell("cat", REMOTE + "/data/datos_hall.csv", capture=True)
        text = result.stdout
        text = text[:text.rfind("\n") + 1]
        rows = list(csv.reader(io.StringIO(text)))
        if not rows or rows[0][:2] != ["sesion", "registro"]:
            raise RuntimeError("CSV remoto incompleto o incompatible; se conserva la copia local.")
        # Una fila cortada por un apagon no debe bloquear la copia para siempre:
        # se omiten las filas con otra cantidad de columnas (y lineas vacias).
        header, data = rows[0], rows[1:]
        valid = [r for r in data if len(r) == len(header)]
        skipped = len(data) - len(valid)
        LOCAL_CSV.parent.mkdir(exist_ok=True)
        temporary = LOCAL_CSV.with_suffix(".csv.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as archivo:
            csv.writer(archivo).writerows([header] + valid)
        temporary.replace(LOCAL_CSV)
        aviso = " | %d filas incompletas omitidas" % skipped if skipped else ""
        print("CSV local: %s | %d registros%s" % (LOCAL_CSV, len(valid), aviso), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=["estado", "enviar", "compilar", "iniciar", "detener", "logs", "descargar", "seguir"])
    parser.add_argument("--serial", help="Identificador ADB de otra placa UNO Q")
    args = parser.parse_args()
    try:
        board = UnoQ(args.serial)
        if args.accion == "estado":
            board.status()
        elif args.accion == "enviar":
            board.deploy()
        elif args.accion == "compilar":
            board.deploy()
            board.shell("arduino-cli", "compile", REMOTE + "/sketch", timeout=None)
        elif args.accion == "iniciar":
            board.deploy()
            board.app("start")
        elif args.accion in ("detener", "logs"):
            board.app({"detener": "stop", "logs": "logs"}[args.accion])
        elif args.accion == "descargar":
            board.fetch()
        else:
            print("Copiando CSV cada 5 s. Ctrl+C detiene la copia; la placa sigue registrando.")
            while True:
                try:
                    board.fetch()
                except (subprocess.SubprocessError, RuntimeError) as error:
                    print("Esperando CSV/conexion:", error, flush=True)
                time.sleep(5)
    except KeyboardInterrupt:
        print("Comando local detenido. Usar 'detener' para parar la app del UNO Q.")
    except (subprocess.SubprocessError, RuntimeError, OSError) as error:
        print("Error:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

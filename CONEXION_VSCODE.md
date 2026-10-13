# UNO Q + App Lab desde VS Code

VS Code edita los archivos locales. `uno_q.py` los envia por ADB/USB-C y
ejecuta `arduino-app-cli` en la placa, el entorno de ejecucion de App Lab.
No necesita una extension de VS Code ni mantener abierta la ventana de
App Lab. La app se llama `hall-ky024` y tambien aparece en App Lab.

## Uso

1. Conectar el UNO Q por USB-C y esperar a que arranque.
2. Conectar KY-024: VCC a **3.3V**, GND a **GND**, AO a **A0**, DO a **D2**.
3. En VS Code abrir **Terminal > Ejecutar tarea > UNO Q: Verificar conexion**.
4. Editar `KY024.py`. El intervalo actual es 600 segundos; para pruebas
   cambiar `INTERVALO_SEGUNDOS` a 1. El sketch esta en
   `UNO_Q_Hall/sketch/sketch.ino`.
5. Ejecutar **UNO Q: Enviar e iniciar registro**. Compila y carga el sketch
   en el microcontrolador e inicia Python en la placa.
6. Ejecutar **UNO Q: Sincronizar CSV en vivo** en otra terminal. El archivo
   local aparece en `datos/datos_hall.csv` cuando hay un CSV remoto disponible.
7. Para terminar, ejecutar **UNO Q: Detener registro** y luego
   **UNO Q: Descargar CSV** para obtener la ultima copia completa.

Detener la sincronizacion con Ctrl+C solo detiene la copia a la laptop;
la aplicacion sigue registrando en el UNO Q mientras este encendido.
La sincronizacion copia cada 5 segundos; el muestreo sigue el intervalo
definido en `KY024.py`. No abrir simultaneamente dos sincronizadores.
Para cambiar el codigo de una app en marcha, detenerla, editar y volver
a iniciar desde VS Code. No editar a la vez en App Lab: el envio desde
VS Code reemplaza los archivos de codigo de `hall-ky024` en la placa.

## Comandos equivalentes

```bash
python3 uno_q.py estado
python3 uno_q.py compilar
python3 uno_q.py iniciar
python3 uno_q.py logs
python3 uno_q.py seguir
python3 uno_q.py detener
python3 uno_q.py descargar
```

`compilar` envia y verifica el sketch sin cargarlo en el microcontrolador.
Los CSV existentes se conservan. La copia local refleja el CSV de la placa;
archivarla con otro nombre antes de borrar o reiniciar el archivo remoto.

## Herramientas y conexion

Se incluyo ADB oficial para Linux en `.tools/adb/adb` (excluido de Git).
Tambien se puede instalar `android-tools` o definir `ADB` con la ruta del
ejecutable. No hay dependencias pip para `uno_q.py`.

La placa de esta sesion tiene identificador `1844505359`. Para otra placa:

```bash
python3 uno_q.py --serial IDENTIFICADOR estado
```

El puerto USB-C de la laptop es el transporte fisico; se usa ADB, no una
conexion serie directa a `/dev/ttyACM0`. Si ADB no detecta la placa, esperar
el arranque y revisar el cable de datos y los permisos USB.

El CSV remoto esta en:
`/home/arduino/ArduinoApps/hall-ky024/data/datos_hall.csv`.
La fecha depende del reloj del UNO Q. Un valor ADC numerico no demuestra
que el sensor este conectado: comprobar que cambia al acercar un iman.

Referencia: https://docs.arduino.cc/tutorials/uno-q/debian-guide/

## Comprobaciones realizadas

Conexion ADB, envio de archivos y consulta de App Lab probados con la placa
`1844505359`. Sketch compilado correctamente en el UNO Q. La copia del CSV
se probo con datos simulados, incluyendo filas incompletas y errores.
El inicio de la app y la lectura fisica del sensor siguen pendientes.

## Copia automatica en segundo plano

Se puede ejecutar `uno_q.py seguir` como proceso independiente de VS Code.
El proceso iniciado durante esta sesion guarda su identificador en
`datos/sincronizacion.pid` y su salida en `datos/sincronizacion.log`.
Requiere mantener la laptop encendida y el USB conectado; no se configura
autoarranque al reiniciar la laptop. La placa conserva su CSV aunque la
copia local se interrumpa.

Para detener solo esa copia desde la terminal de la laptop:

```bash
kill "$(cat datos/sincronizacion.pid)"
```

Para detener la recoleccion en la placa: `python3 uno_q.py detener`.
Antes de usar el PID guardado despues de un reinicio, comprobar que aun
corresponda al proceso `uno_q.py seguir`.

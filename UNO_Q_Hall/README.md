# Registro Hall KY-024 para Arduino UNO Q

Para controlar App Lab desde VS Code por USB-C, ver
[CONEXION_VSCODE.md](../CONEXION_VSCODE.md). Ya hay tareas en `.vscode/tasks.json`.

El programa Python corre en el Linux del UNO Q. El sketch lee el sensor
y entrega los valores mediante Bridge. La conexion USB-C permite usar
Arduino App Lab y descargar el CSV a la laptop.

## Cableado

| KY-024 | UNO Q |
| --- | --- |
| VCC / + | 3.3V |
| GND / - | GND |
| AO | A0 |
| DO | D2 |

## Ejecucion

1. Abrir o crear `hall-ky024` en Arduino App Lab.
2. Pegar `python/main.py` en Python y `sketch/sketch.ino` en el sketch.
   `python/main.py` contiene la misma adaptacion que `../KY024.py`.
3. Verificar el cableado y pulsar Run. La placa necesita tener las dependencias
   del sketch disponibles; si faltan, App Lab debe poder descargarlas.
4. Revisar la consola: `ok` indica una ventana completa de lecturas;
   `limite_adc` indica al menos una lectura en un extremo del ADC;
   `error` indica que no se obtuvo una ventana valida.

El intervalo es de 600 segundos. Para pruebas con un iman, cambiar
`INTERVALO_SEGUNDOS = 1`. Cada fila resume 20 muestras breves de AO y DO,
no todo el intervalo. Una entrada desconectada puede devolver numeros:
un estado `ok` de software no demuestra que el sensor este conectado.
No se calculan gauss ni voltaje sin calibracion.

## CSV

Se conserva en `data/datos_hall.csv` de la aplicacion, dentro del UNO Q.
Incluye sesion, numero de registro, fecha UTC del reloj de la placa, tiempo
transcurrido, promedio/minimo/maximo del ADC, ultimo nivel digital,
numero de niveles altos, cantidad de muestras y estado.

Para descargarlo por USB-C, detener la app y ejecutar en la laptop:

```bash
adb -s 1844505359 pull /home/arduino/ArduinoApps/hall-ky024/data/datos_hall.csv ./datos_hall.csv
```

Si `adb` no esta instalado pero sigue disponible la descarga temporal de
esta sesion, usar `/tmp/proyectoPI3-adb/platform-tools/adb` en su lugar.

## Validacion realizada

Conexion ADB con el UNO Q comprobada. Pruebas simuladas de Python correctas.
La dependencia `ArxTypeTraits@0.3.1` se transfirio por USB y la compilacion
del sketch en el UNO Q termino correctamente (19240 bytes de programa).
Envio de codigo y consulta de estado mediante `uno_q.py` verificados.
No se ha iniciado un registro real del sensor.

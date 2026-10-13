# Control de ventiladores

Daemon en C++ (wiringPi, PWM por software) que ajusta los ventiladores de la Raspberry Pi 5 según la temperatura del CPU, más un monitor Tkinter para la pantalla táctil de 3.5".

## Conexión

Los ventiladores van unidos en un solo canal, en la esquina inferior derecha del GPIO:

| Cable | Pin físico | Señal |
|---|---|---|
| Rojo | 37 | GPIO 26 (PWM) |
| Negro | 39 | GND |

Para controlar velocidad de verdad hace falta un transistor NPN (ej. 2N2222) entre el GPIO y el ventilador; el GPIO no da la corriente del motor.

## Instalación (en la Pi)

```bash
make setup                      # dependencias + compilación + instalación
sudo systemctl enable --now fan-control
make setup-display              # opcional: driver LCD35, reinicia la Pi
```

`INSTALL_DIR` asume el usuario `pi` (`/home/pi/fan_control`); ajústalo en el `Makefile` y en `fan-control.service` si la Pi usa otro.

## Uso

```bash
echo "fan:75" > /tmp/fan_control   # velocidad fija
echo "auto"   > /tmp/fan_control   # modo automático
echo "stop"   > /tmp/fan_control   # detener daemon
cat /tmp/fan_status                # estado actual
python3 /home/pi/fan_control/simple_monitor.py
```

Rangos de temperatura: `updateFanSpeeds()` en `fan_daemon.cpp` (0% bajo 40 °C, 100% sobre 80 °C). Después de editar: `make install && sudo systemctl restart fan-control`.

## Problemas

- Logs: `sudo journalctl -u fan-control -f`
- Diagnóstico: `make info`, `gpio readall`
- La pantalla ocupa los pines 1 a 26; el ventilador usa 37/39 para no chocar.

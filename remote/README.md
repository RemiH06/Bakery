# Acceso remoto a Pixilate

Aerilate entra a Pixilate por SSH dentro de Tailscale: sin abrir puertos en el router, funciona con CGNAT, en redes ajenas (escuela, cafeterías) y también en casa (en la misma red Tailscale conecta directo por la LAN, sin dar la vuelta por internet).

```
Aerilate ──Tailscale + SSH :22──▶ Pixilate (RTX 3060)
```

Más adelante (opcional): una Raspberry siempre encendida despierta a Pixilate por Wake-on-LAN si está apagada.

## 1. Pixilate (una vez)

1. Clonar este repo en Pixilate. `remote/aerilate.pub` es la llave pública de Aerilate (pública por diseño: sin ella no se puede entrar a nada).
2. PowerShell como administrador, desde la raíz del repo:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\remote\pixilate-setup.ps1
   ```
   Abre la URL que imprime Tailscale e inicia sesión. Anota el usuario SSH del resumen.

## 2. Aerilate

```powershell
winget install --id Tailscale.Tailscale -e
```

Inicia sesión con la misma cuenta de Tailscale y agrega a `~/.ssh/config` (fuera del repo):

```
Host pixilate
    HostName pixilate
    User <usuario que imprimió el script>
```

Prueba: `ssh pixilate nvidia-smi`.

## 3. Wake-on-LAN (opcional, cuando el clúster esté armado)

El script ya deja lista la tarjeta de red si Pixilate tiene cable. Falta el BIOS (Asus B550, `Supr` al arrancar): `Advanced > APM Configuration`: `ErP Ready = Disabled`, `Power On By PCI-E = Enabled`. En la Pi:

```bash
./pi-setup.sh AA:BB:CC:DD:EE:FF   # la MAC del resumen
```

Desde Aerilate: `ssh <pi> wake-pixilate`, esperar ~1 min, `ssh pixilate`. Apagar al terminar: `ssh pixilate "shutdown /s /t 0"`.

## Seguridad

- sshd solo acepta llave (sin contraseña) y el firewall solo deja pasar 100.64.0.0/10 (Tailscale): desde la LAN por IP normal o desde internet no responde.
- Si Aerilate se pierde: quitarla del panel de Tailscale y borrar su línea en `C:\ProgramData\ssh\administrators_authorized_keys` de Pixilate.

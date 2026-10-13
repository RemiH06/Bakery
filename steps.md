# Pendientes

## Siguiente sesión

Hecho (2026-10-13): limpieza del repo (`fan/` con Makefile corregido y `fan-control.service`, `CLAUDE.md` desde `BAKERY_CONTEXTO.md`); scripts de acceso remoto en `remote/` (sin correr todavía).

1. Clonar el repo en Pixilate y correr `remote/pixilate-setup.ps1`; Tailscale en Aerilate. WoL queda para después (BIOS + Pi). Probar `ssh pixilate nvidia-smi` desde fuera de casa (datos del celular o ITESO).
2. Trabajos que sobrevivan a la desconexión: OpenSSH en Windows mata los procesos de la sesión al cerrarla. Decidir entre WSL2 + tmux (CUDA funciona en WSL2) o tareas programadas de Windows.
3. Armar el clúster: Raspberry Pi OS en `frambuesa-yi`, llave de Aerilate desde el Imager, `remote/pi-setup.sh`, agregar `Host frambuesa-yi` a `~/.ssh/config`.
4. Skill `bakery` en `48.SkillShot` (cómo llegar a Pixilate, despertarla, correr modelos remotos) una vez que lo anterior funcione. Registrar sshd :22 de Pixilate en `PORTS.md` si se decide que el registro cubre servicios de sistema.

## Otros

- `BAKERY_CONTEXTO.md` sigue suelto: la sección de proyectos hermanos (100%, Bentos, Nine of Hearts, Tacology) no pasó a `CLAUDE.md` porque no es de Bakery. Moverla a sus notas de la bóveda y borrar el archivo.
- `fan/`: `make setup-display` usa LCD-show, que no está probado en Pi 5 con Bookworm. Verificar al armar el clúster.
- La skill `hardware` no lista el switch de 7 puertos ni el SSD externo del clúster; agregarlos ahí y en `Comps.md`.

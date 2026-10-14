# Pendientes

## Siguiente sesión

Hecho (2026-10-13): limpieza del repo (`fan/` con Makefile corregido y `fan-control.service`, `CLAUDE.md` desde `BAKERY_CONTEXTO.md`); acceso SSH a Pixilate funcionando (`ssh pixilate`, nombre en Tailscale `pixilate2`; RTX 3060 12 GB, driver 591.86); `remote/job.ps1` para trabajos largos (tarea programada S4U, probado: sobrevive al cerrar SSH, ve la GPU, `stop` mata a los hijos); skill `bakery` creada; key expiry de Tailscale deshabilitado en `pixilate2`; `sshd` y Tailscale arrancan solos tras reiniciar (Automatic + modo desatendido, sin reinicio real probado).

Antes de usar `job.ps1` desde la skill: commit y push de este repo, `git pull` en el clon de Pixilate.

**Prioridad nueva (2026-10-13): preparar Pixilate para hostear proyectos de la BAKERY WAITLIST antes del clúster.** Skills `hosteo` y `ciberseguridad` creadas en `48.SkillShot` para esto. Orden, aplicando con el usuario y explicando cada paso:

1. Auditoría de Pixilate con `ciberseguridad` (sección "Auditar una máquina"): cuentas maestras con MFA, qué escucha, firewall, cuentas locales, Defender, software, cifrado. Aerilate también, al menos cuentas y firewall.
2. ACL de Tailscale con `tag:server` para Pixilate (`ciberseguridad/references/red.md`).
3. Preparación de `hosteo/references/pixilate.md`: WSL2 + Ubuntu, systemd, Docker Engine, `.wslconfig`, energía. Agregar a `job.ps1` un disparador al arranque y verificar que WSL arranca desde S4U sin sesión; probar un reinicio real.
4. Primer proyecto: decidir con el usuario destino y publicación (Cloudflare Tunnel necesita dominio en Cloudflare), checklist de exposición, publicar.

Después:

1. Armar el clúster: Raspberry Pi OS en `frambuesa-yi`, llave de Aerilate desde el Imager, `remote/pi-setup.sh`, agregar `Host frambuesa-yi` a `~/.ssh/config`.
2. Ampliar la skill `bakery` (ya existe en `48.SkillShot`) cuando haya WoL y clúster. Registrar sshd :22 de Pixilate en `PORTS.md` si se decide que el registro cubre servicios de sistema.

## Otros

- `BAKERY_CONTEXTO.md` sigue suelto: la sección de proyectos hermanos (100%, Bentos, Nine of Hearts, Tacology) no pasó a `CLAUDE.md` porque no es de Bakery. Moverla a sus notas de la bóveda y borrar el archivo.
- `fan/`: `make setup-display` usa LCD-show, que no está probado en Pi 5 con Bookworm. Verificar al armar el clúster.
- La skill `hardware` no lista el switch de 7 puertos ni el SSD externo del clúster; agregarlos ahí y en `Comps.md`.

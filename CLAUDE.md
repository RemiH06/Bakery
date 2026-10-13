# Bakery

Infraestructura propia para hostear y correr los proyectos de iroFactory: un clúster de Raspberry Pi 5 como servidores siempre encendidos, más Pixilate como nodo de GPU accesible desde fuera de casa. Se llama Bakery porque ahí se hacen los "pays" (Pi's). Slogan: *"Pi caliente de frutas todos los días, a todas horas"*.

Nota de proyecto en la bóveda: `15.LambdasVault/vault/proyectos/Hardware/Bakery.md`. Lista de proyectos que esperan hosteo: sección "BAKERY WAITLIST" de `15.LambdasVault/vault/proyectos/Inventario.md`.

Roadmap y traspaso entre sesiones: `steps.md`.

## Máquinas

Inventario completo en la skill `hardware`. Lo que importa aquí:

| Nombre | Rol en Bakery |
|---|---|
| **Aerilate** (laptop, Windows, i3, sin GPU dedicada) | Cliente. Donde corre Claude Code; viaja a ITESO. |
| **Pixilate** (escritorio, Windows, Ryzen 7 5700X, 48 GB, RTX 3060) | Nodo de GPU: modelos locales, entrenamiento, render. Se queda en casa. |
| **2x Raspberry Pi 5 8 GB** | Clúster siempre encendido: hosteo, bastión de red, Wake-on-LAN. |
| Switch de 7 puertos, SSD externo | Red y almacenamiento del clúster. |

Una GPU para el clúster se evaluó pero no se compró: no dar por hecho que existe.

## Estructura

- `fan/`: daemon de ventiladores y monitor de temperatura de la Pi (ver `fan/README.md`).
- `remote/`: acceso SSH a Pixilate por Tailscale y Wake-on-LAN desde una Pi (ver `remote/README.md`).

## Reglas

- Skills que aplican: `ponytail` antes de cada pieza de código, `hardware` antes de proponer equipo, `port-registry` antes de exponer un puerto, `stack-selection` y `planeacion` al arrancar un servicio nuevo, `commit-checkpoints`, `session-hygiene`, `redaccion-espanol-mx`. Para documentación visual, tema `forge` de `37.iroFactory` (hardware y firmware) vía `frontend-design`.
- Seguridad antes que comodidad: nada expuesto a internet sin llave y sin necesidad. Nunca contraseñas en el repo.
- Sin guion largo en ningún texto.

## Iniciativas del hub de Claude.ai

El proyecto Bakery en Claude.ai fue además una sala de scoping de ideas que correrían sobre esta infraestructura. Lo que no se deduce del código:

1. **Editor de video promptable** (prioridad uno), para reels de Instagram/TikTok.
   - Palmier Pro (GPLv3, Mac): referencia de arquitectura, expone la timeline como servidor MCP local para que un agente edite. Su pipeline generativo es propietario: solo se reusa la idea del MCP.
   - Filtros tipo Higgsfield/Skinz2000: son presets de prompt y parámetros sobre modelos de video existentes, no modelos propios. Se replican con ComfyUI o APIs y una librería de presets propia.
   - Yapper (`artificialisabel/yapper`, Python, Whisper on-device): corte base de talking heads (silencios, retakes) antes de la capa generativa.
   - El trabajo con GPU va a Pixilate, no al clúster.
2. **Mapeo 3D de campos de golf** en Guadalajara (satélite, planos e IA). Solo ideación.
3. **Plataforma de reseñas** de restaurantes/hoteles en Guadalajara, monetizada. Pariente de `18.Tacology`.
4. **Quetzbeats**: vive en `2.QuetzBeats`, aquí solo como concepto.
5. **Sistema de escritura crítica**, acompañante del punto 3.

![Made with Python](https://forthebadge.com/images/badges/made-with-python.svg)
![PowerShell](https://img.shields.io/badge/-PowerShell-5391FE?style=for-the-badge&logoColor=white)
![Bash](https://img.shields.io/badge/-Bash-4EAA25?style=for-the-badge&logo=gnubash&logoColor=white)
![Docker](https://img.shields.io/badge/-Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/-Raspberry%20Pi-A22846?style=for-the-badge&logo=raspberrypi&logoColor=white)
![Cloudflare](https://img.shields.io/badge/-Cloudflare-F38020?style=for-the-badge&logo=cloudflare&logoColor=white)
![Debian](https://img.shields.io/badge/-Debian-A81D33?style=for-the-badge&logo=debian&logoColor=white)
![Built with Love](https://forthebadge.com/images/badges/built-with-love.svg)

```ascii
██████╗  █████╗ ██╗  ██╗███████╗██████╗ ██╗   ██╗
██╔══██╗██╔══██╗██║ ██╔╝██╔════╝██╔══██╗╚██╗ ██╔╝
██████╔╝███████║█████╔╝ █████╗  ██████╔╝ ╚████╔╝
██╔══██╗██╔══██║██╔═██╗ ██╔══╝  ██╔══██╗  ╚██╔╝
██████╔╝██║  ██║██║  ██╗███████╗██║  ██║   ██║
╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝   ╚═╝

  Pi caliente de frutas todos los días, a todas horas

       by RemLam (@RemiH06)          version 1.0.0
```

![Maintained](https://img.shields.io/badge/Maintained%3F-yes-green.svg?style=for-the-badge)
![AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg?style=for-the-badge)

## Bakery

### Descripción general

**Bakery** es la infraestructura propia donde se hostean y corren los proyectos de [iroFactory](https://github.com/RemiH06/iroFactory): un clúster de Raspberry Pi 5 siempre encendido, más un escritorio con GPU (Pixilate, RTX 3060) que sirve modelos de lenguaje locales y se puede usar a distancia. El nombre viene de los "pays" (Pi's) que salen del horno.

Todo lo privado vive dentro de una red de Tailscale: nada abre puertos en el router y cada servicio escucha solo en `127.0.0.1` hasta que algo lo publica a propósito. Lo que sí es público sale por Cloudflare Tunnel bajo `remlam.dev`, empezando por [Mapo](https://mapo.remlam.dev).

```
Dentro del tailnet (Tailscale)
  Laptop: Claude Code (MCP) / CLI baker
     └── gateway ──HTTPS + llave──▶ Pixilate (RTX 3060)
                                     ├─ llama-swap: Bonsai, Qwen, visión, whisper
                                     └─ Docker en WSL: apps, Open WebUI, cloudflared
  Raspberry Pi 5 ──▶ Wake-on-LAN y respaldos de Pixilate

Desde internet
  visitante ──▶ Cloudflare ──▶ cloudflared (túnel saliente) ──▶ solo los hostnames públicos
```

La pieza central son los **Bakers**: modelos locales que leen material voluminoso (logs, documentos, reels) en lugar de Claude y devuelven JSON corto y validado. Claude Code orquesta y paga solo por el pedido y la respuesta. Un Baker no tiene herramientas ni bucle, así que una instrucción inyectada en un archivo no puede escribir, borrar ni salir a la red.

```diff
- Hecho a la medida de mis máquinas: los scripts asumen Windows en el nodo de GPU y Debian en las Pi; adaptarlos a otro equipo pide revisar rutas y nombres.
- Los modelos no vienen en el repo: se descargan aparte (ver bakers/MODELOS.md).
- El nodo de GPU también es de juegos: con un juego abierto, los Bakers bajan de marcha o responden error.
- Cloudflare termina el TLS y ve el tráfico de lo publicado: solo pasa por ahí lo que de todos modos es público.
```

## Instalación

Requisitos: una cuenta de Tailscale, [uv](https://docs.astral.sh/uv/) en la laptop y en el nodo de modelos, y Docker para lo publicado.

1. Clonar el repo en el nodo de GPU y en la laptop:
   ```bash
   git clone https://github.com/RemiH06/Bakery.git
   ```
2. Acceso remoto al nodo de GPU (PowerShell de administrador, desde la raíz del clon). Deja SSH solo con llave y solo desde el tailnet. Detalle en [`remote/README.md`](remote/README.md).
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\remote\windows\pixilate-setup.ps1
   ```
3. Servidor de modelos. En Windows (máquina compartida, con vigilante de VRAM):
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File bakers\servidor\windows\setup.ps1
   ```
   En Debian (servidor propio, WSL o una Pi):
   ```bash
   bash bakers/servidor/debian/setup.sh                     # marcha alta fija
   BAKERS_VIGILANTE=1 bash bakers/servidor/debian/setup.sh  # máquina compartida
   ```
4. Cliente en la laptop: variables de entorno y servidor MCP para Claude Code. Detalle en [`bakers/README.md`](bakers/README.md#aerilate).
   ```powershell
   cd bakers; uv sync
   setx BAKERS_URL "https://<nodo en Tailscale>:8090"
   setx BAKERS_API_KEY "<contenido de ~\bakers\api-key.txt en el nodo>"
   claude mcp add --scope user bakers -- uv run --project "<ruta a Bakery\bakers>" bakers-mcp
   ```
5. Raspberry Pi al tailnet, con Wake-on-LAN hacia el nodo de GPU:
   ```bash
   remote/debian/pi-setup.sh AA:BB:CC:DD:EE:FF   # la MAC que imprime el paso 2
   ```
6. Publicación (opcional). Con el token del túnel en `~/.config/cloudflared-tunel.env` (permisos 600, nunca en el repo) y los hostnames dados de alta en el panel de Cloudflare:
   ```bash
   docker compose -f publicacion/compose.yml up -d
   ```

## Argumentos de ejecución

CLI `baker` (desde `bakers/`, con `uv run`):

- `baker status` marcha activa y modelos cargados en el nodo
- `baker log [--desde AAAA-MM-DD]` llamadas por Baker y modelo: % ok, reintentos, mediana y p90 de segundos
- `baker run <baker> -f <archivo> -t <tarea> [-c <categoría>]` corre un Baker sobre archivos locales
- `baker reel <enlace o video> [-d <carpeta>] [-m <modelo>]` convierte un reel o video corto en una nota
- `baker cola agregar|bajar|estado|reintentar|analizar` cola de descargas para lotes grandes, con topes contra bloqueos

Trabajos largos en Windows que sobreviven al cerrar SSH:

- `job.ps1 start <nombre> <carpeta> "<comando>" [-AtStartup]` lo lanza como tarea programada
- `job.ps1 list | log <nombre> | stop <nombre>`

## Funcionalidades

- **Bakers por MCP y CLI:** `resumidor`, `fichero`, `clasificador`, `reel` y `chat`, con salida validada por esquemas de Pydantic y reintento si el modelo se sale del formato.
- **Marchas por VRAM:** un vigilante elige cada 5 s qué modelo atiende según lo que deja libre un juego (`alta` con Bonsai, `media` con Qwen y expertos en RAM, `ninguna`).
- **Visión y transcripción locales:** whisper.cpp y Qwen con `mmproj` para reels, carruseles y videos de hasta 10 min, sin mandar material a terceros.
- **Acceso remoto sin puertos abiertos:** SSH por Tailscale, trabajos que sobreviven al cerrar la sesión y Wake-on-LAN desde una Pi.
- **Publicación controlada:** Cloudflare Tunnel en Docker con imagen fija, solo lectura, sin capacidades y métricas en loopback; todo lo no declarado responde 404.
- **Arranque en frío:** tras un apagón, el nodo de GPU, WSL, Docker, el túnel y los servicios vuelven solos sin nadie en casa.
- **Llaves por cliente:** una API key por máquina, revocables por separado, y una ACL de Tailscale con pruebas que limita a cada nodo a lo que necesita.
- **Banco de carga y set de evaluación:** latencia por número de conversaciones y un set con preguntas respondibles, no respondibles e intentos de inyección.

## Funcionalidades futuras

- Nube propia para fotos, videos y archivos, con dos copias en lugares distintos.
- Segunda Raspberry Pi y switch gigabit con VLAN.
- Nodo de modelos en Debian dedicado, fuera de la máquina de juegos.
- Kubernetes (k3s) como laboratorio cuando haya tres o más nodos siempre encendidos.
- Página de documentación en un subdominio de `remlam.dev`.

## Autoría

por RemLam ([@RemiH06](https://github.com/RemiH06))

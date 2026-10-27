# Bakers

Modelos locales en Pixilate que leen por Claude. Claude Code orquesta; un Baker recibe rutas de archivos, los lee en local y devuelve JSON corto y validado. El ahorro sale de que Claude no lea material voluminoso.

```
Aerilate                                         Pixilate (RTX 3060)
Claude Code ─MCP─┐                               llama-swap 127.0.0.1:8090
                 ├─ gateway (este paquete) ─HTTPS, tailnet, API key─▶ ├─ bonsai (llama.cpp-prism)
Remi ─── CLI ────┘   lee archivos, valida,       tailscale serve :8090 ├─ qwen   (llama.cpp)
                     yt-dlp y ffmpeg (reel)                           ├─ vision (qwen + mmproj)
                                                                      └─ whisper (whisper.cpp)
                     log ~/.bakers/log.jsonl                          vigilante.ps1 elige la marcha
```

Un Baker no tiene herramientas ni bucle: no puede escribir, borrar ni salir a la red aunque un archivo le inyecte instrucciones. Si una tarea pide varios pasos, Claude hace varias llamadas.

## Bakers

Viven en [`src/bakers/bakers.toml`](src/bakers/bakers.toml). Agregar uno con un esquema existente es agregar una entrada; un esquema nuevo es un modelo de Pydantic en [`schemas.py`](src/bakers/schemas.py) y su rama en `core.bake`.

| Baker | Devuelve |
|---|---|
| `resumidor` | `resumen`, `puntos`, `alertas` |
| `clasificador` | cada línea no vacía en una de las categorías dadas, en lotes de 40: `conteo` y `por_categoria` (archivo → números de línea) |
| `reel` | por cada reel o video corto: `tema`, `idea_central`, `recursos`, `citas`, `texto_en_pantalla`, `visual`, `afirmaciones` y la ruta de un borrador `nota.md` |

### `reel`

Herramienta aparte (`reel(fuentes)` en el MCP, `baker reel` en la CLI) porque no lee texto: recibe enlaces o rutas de video de hasta 10 min. En Aerilate, `yt-dlp` baja el video con la sesión de Firefox (las cookies se leen al momento, no se guardan) y `ffmpeg` saca el audio (WAV de 16 kHz) y hasta 8 fotogramas parejos a 540 px. En Pixilate, `whisper` transcribe y `vision` (el mismo Qwen con su `mmproj`) recibe caption, transcripción y fotogramas en una sola llamada. Todo queda en `~/.bakers/reels/<id>/` (video, audio, fotogramas, `transcripcion.json`, `nota.md`), fuera de cualquier repo.

La nota sigue el formato de la skill `inspiracion`, con dos huecos a propósito: los recursos salen como no verificados y la sección Aplicación queda pendiente, porque el modelo no conoce los proyectos. Eso lo completa Claude. Solo piezas que Remi comparte, una por enlace: nada de rastrear cuentas ni guardados.

`whisper` y `vision` forman el grupo `reel` de llama-swap: se cargan juntos (~6 GB) y sacan a `bonsai` mientras dure el lote. No pasan por las marchas; con la marcha `ninguna` el gateway se niega antes de bajar nada.

## Marchas

Los Bakers piden el modelo virtual `principal`; el perfil activo de llama-swap decide quién lo atiende. `vigilante.ps1` mira la VRAM cada 5 s y elige la marcha más alta que cabe dejando 1 GB libre:

| Marcha | `principal` es | VRAM propia (contexto 32k) | Cabe si lo demás usa |
|---|---|---|---|
| `alta` | `bonsai` | ~9.5 GB con el escritorio (9.1 propios) | hasta ~2.1 GB |
| `media` | `qwen`, expertos en RAM | ~3.8 GB con el escritorio (3.35 propios) | hasta ~7.9 GB |
| `ninguna` | nada: el Baker responde error y Claude delega en otro lado | 0 | lo que sea |

Baja al momento, sube solo tras un minuto cabiendo y descarga un modelo que ya no cabe solo cuando no está respondiendo. Probar sin abrir un juego: `vigilante.ps1 -Extra 3000 -Duracion 30` simula 3 GB ocupados.

## Pixilate (una vez)

Necesita `~\bakers\` con los dos llama.cpp y los modelos de 1.0a. Para `reel`, además: whisper.cpp b5454 (`whisper-bin-win-cuda-12.4.0-x64.zip` descomprimido en `whisper.cpp\`), `models\ggml-large-v3-turbo-q8_0.bin` y `models\mmproj-Qwen3.6-35B-A3B-F16.gguf` (es `mmproj-F16.gguf` de `unsloth/Qwen3.6-35B-A3B-GGUF`, renombrado). Desde la raíz del clon:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bakers\pixilate\setup.ps1
```

Descarga llama-swap v264 (verifica el checksum), genera `~\bakers\api-key.txt` legible solo por la cuenta, lanza con `remote/job.ps1 -AtStartup` los trabajos `bakers` (llama-swap) y `bakers-vigilante`, y publica al tailnet con `tailscale serve --https=8090`. Volver a correrlo es el reinicio limpio (mata también los `llama-server` hijos). La configuración ([`pixilate/llama-swap.yaml`](pixilate/llama-swap.yaml)) se lee del clon y se recarga sola al cambiar (`-watch-config`); la recarga regresa a la marcha `alta` y el vigilante la corrige en el siguiente ciclo.

## Aerilate

```powershell
cd bakers; uv sync
setx BAKERS_URL "https://<nombre de Pixilate en Tailscale>:8090"
setx BAKERS_API_KEY "<contenido de ~\bakers\api-key.txt en Pixilate>"
# terminal nueva para que lleguen las variables
claude mcp add --scope user bakers -- uv run --project "<ruta a 29.Bakery\bakers>" bakers-mcp
```

## Uso

```powershell
uv run baker status
uv run baker run resumidor -f build.log -t "por qué falla el build"
uv run baker run clasificador -f issues.txt -t "tipo de issue" -c bug -c idea -c duda
uv run baker reel https://www.instagram.com/reel/<id>/ video.mp4
```

Desde Claude Code: herramientas `bake(baker, tarea, rutas, categorias)`, `reel(fuentes)` y `bakers_status()`. Cada llamada deja una línea en `~/.bakers/log.jsonl` (Baker, modelo que respondió, tokens que leyó y escribió el Baker, `claude_chars` = caracteres del pedido más la respuesta que paga Claude, intentos, segundos, error). Referencia medida: 1.7k tokens en 21 s con carga del modelo incluida; 30k tokens en 66 s.

**Límite:** 32k tokens por llamada. Texto normal da ~3.5 caracteres por token; algo con hashes (un lockfile) da ~1.5. Si se pasa, el Baker responde "parte la tarea".

**Cuándo conviene:** si lo que lee el Baker supera por 5 a 1 lo que Claude gasta en pedirlo y leer la respuesta. Del log sale directo: `entrada` contra `claude_chars / 3.5` (aproximado; la telemetría de Claude Code, `CLAUDE_CODE_ENABLE_TELEMETRY=1`, da el gasto exacto de la sesión).

## Seguridad

- llama-swap y cada llama-server escuchan solo en `127.0.0.1`; afuera solo llega `tailscale serve`, que exige estar en el tailnet. La ACL deja a los invitados solo en el 443.
- Sin `Authorization: Bearer <llave>` llama-swap no responde. La llave no está en el repo; si se filtra, borrar `api-key.txt`, volver a correr `setup.ps1` y actualizar `BAKERS_API_KEY`.
- Cortar todo: `ssh pixilate "tailscale serve --https=8090 off"`.
- La llave en Pixilate solo la lee la cuenta (`icacls` con `EQUIPO\cuenta`: si la cuenta se llama igual que el equipo, el nombre a secas resuelve al equipo).

## Tests

```powershell
uv run pytest
```

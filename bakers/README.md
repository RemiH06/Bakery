# Bakers

Modelos locales en Pixilate que leen por Claude. Claude Code orquesta; un Baker recibe rutas de archivos, los lee en local y devuelve JSON corto y validado. El ahorro sale de que Claude no lea material voluminoso.

```
Aerilate                                         Pixilate (RTX 3060)
Claude Code ─MCP─┐                               llama-swap 127.0.0.1:8090
                 ├─ gateway (este paquete) ─HTTPS, tailnet, API key─▶ ├─ bonsai (llama.cpp-prism)
Remi ─── CLI ────┘   lee archivos, valida,       tailscale serve :8090 └─ qwen   (llama.cpp)
                     log ~/.bakers/log.jsonl
```

Un Baker no tiene herramientas ni bucle: no puede escribir, borrar ni salir a la red aunque un archivo le inyecte instrucciones. Si una tarea pide varios pasos, Claude hace varias llamadas.

## Bakers

Viven en [`src/bakers/bakers.toml`](src/bakers/bakers.toml). Agregar uno con un esquema existente es agregar una entrada; un esquema nuevo es un modelo de Pydantic en [`schemas.py`](src/bakers/schemas.py) y su rama en `core.bake`.

| Baker | Devuelve |
|---|---|
| `resumidor` | `resumen`, `puntos`, `alertas` |
| `clasificador` | cada línea no vacía en una de las categorías dadas, en lotes de 40: `conteo` y `por_categoria` (archivo → números de línea) |

## Pixilate (una vez)

Necesita `~\bakers\` con los dos llama.cpp y los modelos de 1.0a. Desde la raíz del clon:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bakers\pixilate\setup.ps1
```

Descarga llama-swap v264 (verifica el checksum), genera `~\bakers\api-key.txt` legible solo por la cuenta, lo lanza con `remote/job.ps1 -AtStartup` (trabajo `bakers`) y lo publica al tailnet con `tailscale serve --https=8090`. La configuración ([`pixilate/llama-swap.yaml`](pixilate/llama-swap.yaml)) se lee del clon y se recarga sola al hacer `git pull`.

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
```

Desde Claude Code: herramientas `bake(baker, tarea, rutas, categorias)` y `bakers_status()`. Cada llamada deja una línea en `~/.bakers/log.jsonl` (Baker, modelo, tokens de entrada y salida, intentos, segundos, error).

**Cuándo conviene:** si lo que lee el Baker supera por 5 a 1 lo que Claude gasta en pedirlo y leer la respuesta. Para comparar, la telemetría de Claude Code (`CLAUDE_CODE_ENABLE_TELEMETRY=1`).

## Seguridad

- llama-swap y cada llama-server escuchan solo en `127.0.0.1`; afuera solo llega `tailscale serve`, que exige estar en el tailnet. La ACL deja a los invitados solo en el 443.
- Sin `Authorization: Bearer <llave>` llama-swap no responde. La llave no está en el repo; si se filtra, borrar `api-key.txt`, volver a correr `setup.ps1` y actualizar `BAKERS_API_KEY`.
- Cortar todo: `ssh pixilate "tailscale serve --https=8090 off"`.

## Tests

```powershell
uv run pytest
```

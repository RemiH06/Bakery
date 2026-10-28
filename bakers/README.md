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
| `fichero` | ficha de especie desde varias fuentes: nombres, `descripcion`, `datos` y `ubicaciones_iteso` con fuente, `interacciones`, `contradicciones` (solo entre fuentes) y `faltantes` |
| `clasificador` | cada línea no vacía en una de las categorías dadas, en lotes de 40: `conteo` y `por_categoria` (archivo → números de línea) |
| `reel` | por cada reel o video corto: `tema`, `idea_central`, `recursos`, `citas`, `texto_en_pantalla`, `visual`, `afirmaciones` y la ruta de un borrador `nota.md` |
| `chat` | por turno de una conversación con un cliente: `respuesta` y `escalar` |

### `chat`

Atención a clientes de un negocio o un Airbnb, de varios turnos y de cara a terceros. No es para Claude: no está en el MCP y `bake` lo rechaza. Cada conversación se liga a un producto y lleva su hoja (`~/.bakers/chat/hojas/<producto>.md`, Markdown libre: horarios, reglas, FAQ) al final del `sistema`, más el historial de esa conversación (los últimos 12k caracteres). Solo responde con la hoja; si no alcanza, o si piden precios, descuentos, excepciones o reservas que la hoja no trae, marca `escalar` y el cliente recibe un texto fijo de traspaso (`chat.TRASPASO`): una escalada nunca lleva datos del modelo. Con Pixilate apagado, en marcha `ninguna` o sin respuesta en 60 s, también recibe el traspaso, no un error.

Lo que escribe el cliente es entrada no confiable: llega solo como turnos de usuario, el JSON forzado no lo deja salirse del formato, una respuesta que cite el `sistema` se descarta y se reintenta, y el Baker no tiene herramientas, así que lo peor que puede pasar es una respuesta mala, nunca una acción. Límites: 1,000 caracteres por mensaje, 40 mensajes del cliente por conversación, 512 tokens por respuesta.

El historial vive en `~/.bakers/chat/chat.db` (SQLite) y las conversaciones sin mensajes en 30 días se borran solas. Las hojas reales y el historial son datos de terceros: nunca en un repo. El log guarda tiempos, tokens y si escaló, pero no el texto del cliente.

```powershell
uv run baker chat hablar casa-jacaranda          # conversación nueva en la terminal; vacío para salir
uv run baker chat pendientes [producto]          # escaladas al dueño, con todos sus mensajes
uv run baker chat eval tests/chat/casa-jacaranda.toml
```

El set de evaluación ([`tests/chat/`](tests/chat/), con una hoja ficticia) tiene 22 preguntas respondibles (aciertan si no escala y traen el dato esperado), 10 no respondibles (aciertan si escala) y 15 intentos de inyección (aciertan si no traen nada de `prohibido`). Corre en una base aparte. Con Bonsai (2026-10-28): 100 % en las tres en las dos últimas corridas, ~1.2 a 2 s por turno. Las reglas que hicieron falta: escalar en vez de deducir "no hay" de lo que la hoja no menciona, y el texto fijo de traspaso (antes el modelo lo redactaba cada vez distinto y a veces mencionaba "la información disponible"). Un acierto por subcadena no prueba que no haya inventado nada: después de cambiar el `sistema`, leer las respuestas completas.

**Capacidad** ([`pixilate/carga.py`](pixilate/carga.py), 2026-10-28): con Bonsai y `-np 1`, los turnos se forman en la cola de llama-server y cada conversación activa suma ~1.4 s. p95 de 6.4 s con 4 conversaciones escribiendo sin pausa y 12.5 s con 8; unos 40 turnos por minuto en total, así que con huéspedes que escriben cada 30 a 60 s aguanta decenas de conversaciones abiertas. `-np 4 --kv-unified` no ayuda con Bonsai (cada conversación baja a 12 tok/s y el p95 sube). En la marcha `media`, Qwen relee el prompt con los expertos en RAM: 1 o 2 conversaciones activas, y si no, el traspaso a los 60 s. Tabla completa en `history.md`.

### `reel`

Herramienta aparte (`reel(fuentes)` en el MCP, `baker reel` en la CLI) porque no lee texto: recibe enlaces o rutas de video de hasta 10 min. En Aerilate, `yt-dlp` baja el video con la sesión de Firefox (las cookies se leen al momento, no se guardan) y `ffmpeg` saca el audio (WAV de 16 kHz) y hasta 8 fotogramas parejos a 540 px. En Pixilate, `whisper` transcribe y `vision` (el mismo Qwen con su `mmproj`) recibe caption, transcripción y fotogramas en una sola llamada. El material queda en `~/.bakers/reels/<id>/` (video, audio, fotogramas, `transcripcion.json`, `nota.md`), fuera de cualquier repo. Con `destino` (`-d` en la CLI), la nota también se escribe en esa carpeta como `AAAA-MM-DD-<cuenta>-<tema>.md` y enlaza al material; qué carpeta toca a cada proyecto lo dice la tabla de la skill `inspiracion`. En este repo, `docs/inspiracion/` (gitignorado).

La nota sigue el formato de la skill `inspiracion`, con dos huecos a propósito: los recursos salen como no verificados y la sección Aplicación queda pendiente, porque el modelo no conoce los proyectos. Eso lo completa Claude. Solo piezas que Remi comparte, una por enlace: nada de rastrear cuentas ni guardados.

El log trae `pasos` (segundos de descarga, whisper, fotogramas y visión). En 8 reels de 14 s a 3 min (2026-10-27): 80 a 120 s por reel, de los que la visión se lleva 73 a 110 s; lo demás suma ~10 s. Los segmentos de whisper con `avg_logprob` menor a −1 se descartan (sin VAD, whisper.cpp inventa letra sobre la música y eso metió a la visión en un bucle) y los repetidos seguidos se colapsan.

### Cola de descargas

Para lotes grandes (cientos de reels), bajar y analizar van separados: Instagram mandó un aviso de actividad automatizada tras ~11 descargas seguidas (2026-10-27). El estado vive en `~/.bakers/cola/cola.json` (fuera del repo) y los errores en `errores.jsonl`, junto a él.

```powershell
uv run baker cola agregar links.txt                # uno por renglón; quita el ?stkn=, guarda "Etiqueta: " y el último "# Sección"
uv run baker cola bajar                            # solo descarga; corre días seguidos
uv run baker cola estado                           # bajados, pendientes, fallidos y próximo intento
uv run baker cola analizar -d <carpeta de notas> [-m vision-abliterado]   # `reel` sobre lo ya bajado, de 5 en 5
```

`agregar` ignora repetidos y lo que ya está en `~/.bakers/reels/`. `bajar` descarga uno a la vez con 1 a 4 min al azar entre descargas, de 9:00 a 22:59 y hasta 30 por día (`--tope`). Ante un error de Instagram (400, 401, 403, 429, login, checkpoint) para entre 2 y 3 h al azar y luego prueba primero un enlace que no haya fallado: si baja, la cuenta ya está libre. yt-dlp da el mismo mensaje para un post privado que para el límite de la cuenta, así que un enlace que falla así 3 veces queda como fallido. Un enlace borrado, demasiado largo o de un sitio que yt-dlp no entiende se marca y sigue; sin red (al despertar de la suspensión) espera 5 min sin contar intento. Todas las esperas se guardan como hora de reloj: matar el proceso o apagar la laptop no pierde nada, y al volver respeta la pausa que quedaba. Un candado impide dos `bajar` a la vez.

**Por qué 30 al día:** el aviso llegó tras ~11 descargas en pocos minutos (2 s entre peticiones). Con 1 a 4 min entre una y otra, 30 son ~75 min de actividad repartidos en un día de 14 h, cerca de lo que alguien abre a mano, y 200 reels tardan unos 7 días. Si en una semana no hay otro aviso, se puede subir a 50; si llega, bajar a 15.

`analizar` no descarga nunca: con un enlace de Instagram cuyo video falta, lo regresa a pendiente. Corre solo con la marcha `alta`; con otra espera 5 min y vuelve a mirar, porque con un juego abierto el grupo `reel` (~6 GB) no cabe. Un reel que falla dos veces el análisis queda como fallido. `analizar` termina cuando no queda nada bajado, así que se vuelve a correr conforme `bajar` avanza (de noche, por ejemplo); `-m` cambia el modelo de `bakers.toml` solo para esa corrida. Ojo: los enlaces que no son de Instagram (TikTok, Facebook) sí se vuelven a bajar al analizar, porque `_obtener` solo reconoce como ya bajados los códigos de Instagram.

**Días seguidos en Aerilate.** Tiene que correr ahí porque ahí están las cookies de Firefox. Con [`remote/job.ps1`](../remote/job.ps1) (tarea programada S4U: sigue con la terminal o VS Code cerrados y vuelve a arrancar con Windows), desde `bakers/` en una PowerShell **de administrador** (registrar una tarea S4U o de arranque lo pide; sin eso, `Register-ScheduledTask` da "Acceso denegado"). La tarea corre igual con la cuenta de Remi, no como administrador:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ..\remote\job.ps1 start cola . "uv run baker cola bajar" -AtStartup
powershell -NoProfile -ExecutionPolicy Bypass -File ..\remote\job.ps1 log cola
powershell -NoProfile -ExecutionPolicy Bypass -File ..\remote\job.ps1 stop cola
```

Las tareas pueden arrancar y seguir con batería. Al suspender la laptop el proceso se congela, no muere; al despertar, la espera sigue por reloj, así que si la pausa ya venció descarga enseguida, y si la red tarda en volver espera los 5 min de "sin red". No hay `WakeToRun`: la laptop no se despierta sola para bajar. Si Firefox pierde la sesión de Instagram, todo cuenta como bloqueo; `cola estado` lo muestra en `motivo` y `fallidos`.

`whisper` y `vision` forman el grupo `reel` de llama-swap: se cargan juntos (~6 GB) y sacan a `bonsai` mientras dure el lote. No pasan por las marchas; con la marcha `ninguna` el gateway se niega antes de bajar nada.

## Marchas

Los Bakers piden el modelo virtual `principal`; el perfil activo de llama-swap decide quién lo atiende. `vigilante.ps1` mira la VRAM cada 5 s y elige la marcha más alta que cabe dejando 1 GB libre:

| Marcha | `principal` es | VRAM propia (contexto 32k) | Cabe si lo demás usa |
|---|---|---|---|
| `alta` | `bonsai` | ~9.5 GB con el escritorio (9.1 propios) | hasta ~2.1 GB |
| `media` | `qwen`, expertos en RAM | ~3.8 GB con el escritorio (3.35 propios) | hasta ~7.9 GB |
| `ninguna` | nada: el Baker responde error y Claude delega en otro lado | 0 | lo que sea |

`whisper`, `vision`, `abliterado`, `vision-abliterado` y `qwen-gpu` no son marchas, pero su VRAM cuenta como nuestra, no como de un juego. Baja al momento, sube solo tras un minuto cabiendo y descarga un modelo que ya no cabe solo cuando no está respondiendo. Probar sin abrir un juego: `vigilante.ps1 -Extra 3000 -Duracion 30` simula 3 GB ocupados.

## Pixilate (una vez)

Necesita `~\bakers\` con los dos llama.cpp y los modelos de 1.0a. Para `reel`, además: whisper.cpp b5454 (`whisper-bin-win-cuda-12.4.0-x64.zip` descomprimido en `whisper.cpp\`), `models\ggml-large-v3-turbo-q8_0.bin` y `models\mmproj-Qwen3.6-35B-A3B-F16.gguf` (es `mmproj-F16.gguf` de `unsloth/Qwen3.6-35B-A3B-GGUF`, renombrado). Desde la raíz del clon:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bakers\pixilate\setup.ps1
```

Descarga llama-swap v264 (verifica el checksum), genera `~\bakers\api-key.txt` legible solo por la cuenta, lanza con `remote/job.ps1 -AtStartup` los trabajos `bakers` (llama-swap) y `bakers-vigilante`, y publica al tailnet con `tailscale serve --https=8090`. Volver a correrlo es el reinicio limpio (mata también los `llama-server` hijos). La configuración ([`pixilate/llama-swap.yaml`](pixilate/llama-swap.yaml)) se lee del clon y se recarga sola al cambiar (`-watch-config`); la recarga regresa a la marcha `alta` y el vigilante la corrige en el siguiente ciclo. **Ojo:** recargar apaga todos los modelos y solo espera 30 s a las respuestas en curso (`shutdownTimeout` de llama-swap); una más larga se corta. Hacer `git pull` de un cambio a `llama-swap.yaml` con los Bakers quietos (`baker status` sin nada en `cargados`, o sin otra sesión usándolos).

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

**Varias sesiones a la vez:** no hace falta cola propia. El planificador FIFO de llama-swap (desde v264) deja esperando una petición que sacaría a un modelo que está respondiendo y la atiende al terminar (probado el 2026-10-27: `qwen` llegó a media respuesta de `bonsai`, esperó 42 s y respondió). Las peticiones al modelo ya cargado pasan primero, así que una sesión con muchas llamadas seguidas puede hacer esperar a otra.

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

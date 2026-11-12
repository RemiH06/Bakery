# Bakers

Modelos locales en Pixilate que leen por Claude. Claude Code orquesta; un Baker recibe rutas de archivos, los lee en local y devuelve JSON corto y validado. El ahorro sale de que Claude no lea material voluminoso.

```
Aerilate                                         Pixilate (RTX 3060)
Claude Code ─MCP─┐                               llama-swap 127.0.0.1:8090
                 ├─ gateway (este paquete) ─HTTPS, tailnet, API key─▶ ├─ bonsai (llama.cpp-prism)
Remi ─── CLI ────┘   lee archivos, valida,       tailscale serve :8090 ├─ qwen   (llama.cpp)
                     yt-dlp y ffmpeg (reel)                           ├─ vision (qwen + mmproj)
                                                                      └─ whisper (whisper.cpp)
                     log ~/.bakers/log.jsonl                          vigilante.py elige la marcha
```

Un Baker no tiene herramientas ni bucle: no puede escribir, borrar ni salir a la red aunque un archivo le inyecte instrucciones. Si una tarea pide varios pasos, Claude hace varias llamadas.

## Bakers

Viven en [`src/bakers/bakers.toml`](src/bakers/bakers.toml). Agregar uno con un esquema existente es agregar una entrada; un esquema nuevo es un modelo de Pydantic en [`schemas.py`](src/bakers/schemas.py) y su rama en `core.bake`.

| Baker | Qué hace | Para qué sirve y quién lo usa | Modelo | Devuelve |
|---|---|---|---|---|
| `resumidor` | Lee archivos largos (logs, documentos, código) y los reduce a lo que pide la tarea | Que Claude no gaste contexto leyendo material voluminoso: le llega el resumen y las alertas de lo que sí hay que revisar. Por el MCP, desde cualquier proyecto | `principal` | `resumen`, `puntos`, `alertas` |
| `clasificador` | Pone cada línea no vacía de los archivos en una de las categorías dadas, en lotes de 40, sin saltarse ninguna | Ordenar listas largas sin que Claude las lea. Lo usa la cola de reels para darle a cada pieza su clase de inspiración (`clases.py`) | `principal` | `conteo` y `por_categoria` (archivo → números de línea) |
| `fichero` | Junta varias fuentes sobre una especie en una sola ficha y marca dónde se contradicen entre sí | Fichas de especies de Campus Lab ITESO (incluye ubicaciones en el campus); sirve igual para LinNeo | `principal` | nombres, `descripcion`, `datos` y `ubicaciones_iteso` con fuente, `interacciones`, `contradicciones` y `faltantes` |
| `doll` | Responde una pregunta solo con fragmentos de notas, citando textual | La capa de respuesta del RAG de [Doll](https://github.com/RemiH06/Doll), que recupera los fragmentos y verifica por código que cada cita exista | `principal` | `citas`, `no_encontrado`, `respuesta` |
| `reel` | Baja un reel o video corto, lo transcribe y mira sus fotogramas | Convertir lo que Remi guarda en redes en notas de inspiración para la bóveda, solo o en lote con la [cola de descargas](#cola-de-descargas). Herramienta propia (`reel` en el MCP, `baker reel`) | `vision` y `whisper` | `tema`, `idea_central`, `recursos`, `citas`, `texto_en_pantalla`, `visual`, `afirmaciones`, `pasos` y la ruta de un borrador `nota.md` |
| `chat` | Atiende a los clientes de un negocio o un Airbnb con solo la hoja del producto, y escala lo que no sabe | Atención a terceros, varios turnos. No es para Claude: no está en el MCP (`baker chat`) | `principal` | por turno: `respuesta` y `escalar` |

`principal` sigue la marcha del vigilante (Bonsai en `alta`, Qwen en `media`; ver [Marchas](#marchas)).

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

**Capacidad** ([`banco/carga.py`](banco/carga.py), 2026-10-28): con Bonsai y `-np 1`, los turnos se forman en la cola de llama-server y cada conversación activa suma ~1.4 s. p95 de 6.4 s con 4 conversaciones escribiendo sin pausa y 12.5 s con 8; unos 40 turnos por minuto en total, así que con huéspedes que escriben cada 30 a 60 s aguanta decenas de conversaciones abiertas. `-np 4 --kv-unified` no ayuda con Bonsai (cada conversación baja a 12 tok/s y el p95 sube). En la marcha `media`, Qwen relee el prompt con los expertos en RAM: 1 o 2 conversaciones activas, y si no, el traspaso a los 60 s. Tabla completa en `history.md`.

### `reel`

Herramienta aparte (`reel(fuentes)` en el MCP, `baker reel` en la CLI) porque no lee texto: recibe enlaces o rutas de video de hasta 10 min. En Aerilate, `yt-dlp` baja el video con la sesión de Firefox (las cookies se leen al momento, no se guardan) y `ffmpeg` saca el audio (WAV de 16 kHz) y hasta 8 fotogramas parejos a 540 px. En Pixilate, `whisper` transcribe y `vision` (el mismo Qwen con su `mmproj`) recibe caption, transcripción y fotogramas en una sola llamada. El material queda en `~/.bakers/reels/<id>/` (video, audio, fotogramas, `transcripcion.json`, `nota.md` y `reel.json`, las secciones ya en Markdown para reescribir la nota con otra plantilla sin volver a la visión), fuera de cualquier repo.

Los posts de fotos y carruseles (Instagram `/p/`, fotos de TikTok) no los baja yt-dlp ("No video formats found", "Unsupported URL"); en ese caso entra `gallery-dl` (`pip install gallery-dl`, misma sesión de Firefox) y baja las piezas a `~/.bakers/reels/<código>/` (o `g-<hash>/` fuera de Instagram) con su `info.json`. Baja a `<carpeta>.part` y renombra al terminar, así que una galería cortada no cuenta como bajada. La visión recibe hasta 8 piezas parejas, con la primera y la última, etiquetadas `[3/10]`; de un video dentro del carrusel, su segundo 1. Sin whisper: el audio de un post de fotos de TikTok es música. Sin habla no hay citas (la visión copiaba el texto de las diapositivas como citas, así que el código las vacía); ese texto queda en "Texto en pantalla". Un carrusel de 8 fotos de TikTok tardó 2 min 36 s con descarga (2026-10-29). Con `destino` (`-d` en la CLI), la nota también se escribe en esa carpeta como `AAAA-MM-DD-<cuenta>-<tema>.md` y enlaza al material; qué carpeta toca a cada proyecto lo dice la tabla de la skill `inspiracion`. En este repo, `docs/inspiracion/` (gitignorado).

La nota sigue el formato de la skill `inspiracion`, con dos huecos a propósito: los recursos salen como no verificados y la sección Aplicación queda pendiente, porque el modelo no conoce los proyectos. Eso lo completa Claude. Solo piezas que Remi comparte, una por enlace: nada de rastrear cuentas ni guardados.

El log trae `pasos` (segundos de descarga, whisper, fotogramas y visión). En 8 reels de 14 s a 3 min (2026-10-27): 80 a 120 s por reel, de los que la visión se lleva 73 a 110 s; lo demás suma ~10 s. Los segmentos de whisper con `avg_logprob` menor a −1 se descartan (sin VAD, whisper.cpp inventa letra sobre la música y eso metió a la visión en un bucle) y los repetidos seguidos se colapsan. Si la visión llega al tope de 4096 tokens (bucle), el esquema se parte en dos llamadas, cada una con su propio tope: lo que se oye (tema, idea, recursos, citas, afirmaciones) y lo que se ve (texto en pantalla, visual, pasos).

### Cola de descargas

Para lotes grandes (cientos de reels), bajar y analizar van separados: Instagram mandó un aviso de actividad automatizada tras ~11 descargas seguidas (2026-10-27). El estado vive en `~/.bakers/cola/cola.json` (fuera del repo) y los errores en `errores.jsonl`, junto a él.

```powershell
uv run baker cola agregar links.txt                # uno por renglón; quita el ?stkn=, guarda "Etiqueta: " y el último "# Sección"
uv run baker cola bajar                            # solo descarga; corre días seguidos
uv run baker cola estado                           # bajados, pendientes, fallidos y próximo intento
uv run baker cola reintentar [--tipo enlace|bloqueo|analisis]   # fallidos de vuelta a la cola, intentos en cero
uv run baker cola analizar -d <carpeta de notas> [-m vision-abliterado] [--min-libre 30]   # `reel` sobre lo ya bajado y clase a cada pieza
uv run baker cola reclasificar -d <carpeta de notas>   # clase y plantilla para las notas que no tienen clase
```

`agregar` ignora repetidos y lo que ya está en `~/.bakers/reels/`. `bajar` descarga uno a la vez con 5 a 15 min al azar entre descargas, de 9:00 a 22:59 y hasta 100 por día (`--tope`). Ante un error de Instagram (400, 401, 403, 429, login, checkpoint; de yt-dlp o de gallery-dl) para entre 2 y 3 h al azar y luego prueba primero un enlace que no haya fallado: si baja, la cuenta ya está libre. yt-dlp da el mismo mensaje para un post privado que para el límite de la cuenta, así que un enlace que falla así 3 veces queda como fallido. Un enlace borrado, demasiado largo o de un sitio que yt-dlp no entiende se marca y sigue; sin red (al despertar de la suspensión) espera 5 min sin contar intento. Todas las esperas se guardan como hora de reloj: matar el proceso o apagar la laptop no pierde nada, y al volver respeta la pausa que quedaba. Un candado impide dos `bajar` a la vez.

**Por qué así:** el aviso llegó tras ~11 descargas en pocos minutos (2 s entre peticiones). Del 2026-10-28 al 2026-11-10 fueron 30 al día con 1 a 4 min entre una y otra: el tope se llenaba en hora y cuarto, en ráfaga, y hubo un solo bloqueo (2026-11-08). Desde el 2026-11-10 el tope es 100 con 5 a 15 min entre descargas (~10 en promedio): repartidas en el día parecen alguien que abre reels de vez en cuando. Las 100 no caben en las 14 h de la ventana, así que en la práctica son ~80 a 85 al día y el número varía (la ventana corta a las 23:00); es a propósito, para no alargar el horario. Si llegan bloqueos seguidos, bajar el tope.

`analizar` no descarga nunca, de ningún sitio: le pasa a `reel` el video (o la carpeta de la galería) que dejó `bajar`, con sus metadatos al lado, y si ya no está regresa el enlace a pendiente. `bajar` acepta cualquier enlace que entiendan yt-dlp (Instagram, TikTok, YouTube, Facebook) o gallery-dl (fotos y carruseles); lo que tiene DRM (Spotify) queda como fallido. `reintentar` regresa los fallidos: `enlace` y `bloqueo` a pendiente, `analisis` (bajados, pero la visión falló dos veces) a bajado; el tipo sale del último error guardado. Es una tarea de fondo: sale sin hacer nada si no hay piezas bajadas ni por clasificar, y se interrumpe a media pieza si la marcha deja de ser `alta` (con un juego abierto el grupo `reel`, ~6 GB, no cabe), si quedan menos de 30 GB libres (`--min-libre`) o si llama-swap no responde; la siguiente vuelta retoma sin gastar intentos. Un hilo lo revisa cada 5 s y, al cortar, descarga de llama-swap los modelos del paso en curso (whisper y la visión, o el del clasificador), porque soltar la petición no basta: el servidor la terminaría ocupando la VRAM. `reel` revisa el corte entre pasos para no volver a cargar un modelo. Matarlo (`job.ps1 stop analizar`) también es seguro: cada pieza cambia de estado solo con su paso terminado, y el material se borra después de escribir la nota y anotarla en la cola. Un reel que falla dos veces el análisis queda como fallido. `-m` cambia el modelo de `bakers.toml` solo para esa corrida.

**Clases** ([`clases.py`](src/bakers/clases.py)): la visión deja cada pieza en `clasificar` y, al vaciar lo bajado, el Baker `clasificador` les pone clase a todas juntas, de 40 en 40 (usa `principal`: cambiar de modelo en cada reel costaría una carga cada vez). Lee el tema, la idea central, la cuenta, los recursos y, como pista, la sección y la etiqueta con que Remi guardó el enlace. La clase decide la plantilla de la nota ([`plantillas/`](src/bakers/plantillas/), una por clase; una sección cuyos huecos quedan vacíos no sale), el `[[destino]]` que enlaza y si el material se conserva o se borra al escribirla. `ruido` no deja nota, solo el ID en la cola; `revisar` (no encaja en ninguna) conserva el material hasta que Remi decida. Las clases no viven en este repo: se leen de la tabla de `0. Clases de inspiración.md` en la carpeta de notas (`--clases` para otra ruta), y sin esa nota las piezas esperan su clase. Una clase nueva se agrega en la nota y con su plantilla aquí. `reclasificar` hace lo mismo con las notas escritas antes de las clases: las reescribe con su plantilla (lo agregado a mano se queda al final), saca el texto completo de `transcripcion.json` si el material sigue en esa máquina y salta las que ya tienen `clase:`. Con `--revisar` también vuelve a pasar las que quedaron en `revisar`, tras agregar una clase.

**La inspo se consume:** cuando una nota se usa en un proyecto, la idea pasa al proyecto como propia y la nota se borra de la bóveda (skill `inspiracion`, "Usar inspo en un proyecto"). Al empezar cada vuelta, `analizar` busca las piezas analizadas cuya nota ya no está en la carpeta de notas, borra su material y las marca `usado`; el ID se queda en la cola para no volver a bajarlas. Si en la carpeta falta la nota de clases no toca nada, para que una carpeta vacía o mal montada no cuente como "todo usado".

**La cola vive en Pixilate** (desde el 2026-11-05; antes en Aerilate): siempre está prendida y ahí corren los modelos, así que la laptop puede dormir. Necesita Firefox con la sesión de Instagram iniciada (las cookies se leen del perfil aunque Firefox esté cerrado), `ffmpeg`, `yt-dlp` y `gallery-dl`. Dos tareas de [`remote/windows/job.ps1`](../remote/windows/job.ps1), registradas desde PowerShell de administrador o por SSH con una cuenta de administrador (S4U lo pide):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ..\remote\windows\job.ps1 start cola . "uv run baker cola bajar" -AtStartup
powershell -NoProfile -ExecutionPolicy Bypass -File ..\remote\windows\job.ps1 start analizar . "<script local>" -Cada 10 -Baja
powershell -NoProfile -ExecutionPolicy Bypass -File ..\remote\windows\job.ps1 log cola
```

`bajar` corre de 9:00 a 22:59. `analizar` se despierta cada 10 min, todo el día, con la prioridad más baja (`-Baja`: clase inactiva, que heredan uv, Python y ffmpeg, así que solo usa el CPU que nadie más pide) y corre solo si toca. Lo que lo pausa es lo de arriba: un juego o cualquier programa que ocupe la GPU baja la marcha y lo corta a media pieza; al despejarse, la siguiente vuelta retoma, a lo más 10 min después. El script local revisa `cola.json` antes de tocar git, así que una vuelta sin piezas no cuesta nada; si la vuelta anterior sigue corriendo, el programador se salta la nueva, y un candado impide dos `analizar` a la vez.

La tarea `analizar` necesita `BAKERS_URL` (`http://127.0.0.1:8090`) y `BAKERS_API_KEY`, y las notas van a un clon parcial de la bóveda con una llave de despliegue que solo sirve para ese repo; el script que hace eso vive en `~\bakers\` de Pixilate, fuera de este repo porque nombra la bóveda. Para leer las notas desde otra máquina, `git pull` en la bóveda.

**Panel de control** (`baker cola panel`, [`panel.py`](src/bakers/panel.py), página en [`web/`](src/bakers/web/)): un cuaderno con una hoja por sección. Arriba, el horno: la marcha de Pixilate (caliente en `alta`, tibio en `media`, apagado en `ninguna`).

- **Inspo** ([`notas.py`](src/bakers/notas.py)), con `--notas <carpeta de inspiración>` y la bandeja de `--bandeja`. Un filtro literal busca el texto tal cual en cualquier parte de la nota, frontmatter incluido, sin distinguir mayúsculas ni acentos, y el fragmento sale con sus acentos. Hay pestañas por grupo, según el `[[destino]]` de la nota (AyP, 100, iroFactory para cualquier `[[N.Proyecto]]`, AduSI, otros; en la bandeja, según la `pista`), y filtros por clase y por mes. Cada pestaña cuenta con los demás filtros puestos. El visor muestra la nota completa con las coincidencias resaltadas y navegables, el estado de la pieza en la cola, la fuente original y un botón para copiar el enlace de Obsidian. El estado vive en la URL (`#inspo?q=…&g=…&n=…`): se comparte, se recarga y el botón de atrás cierra la nota. Las notas se leen una vez y se cachean por `mtime`; una nota se pide por nombre y solo se sirve si está en la carpeta. El Markdown se pinta con nodos del DOM, nunca con `innerHTML`: las notas traen texto de terceros, y una etiqueta o un enlace `javascript:` dentro de una transcripción salen como texto.
- **Cola**: el panel de antes.

Sin dependencias ni nada externo: las fuentes (Fraunces, Inter y Azeret Mono, OFL, en `web/fuentes/`) van en el paquete, y la CSP solo deja cargar y ejecutar lo de `web/`, que el servidor sirve desde una lista blanca. La hoja de la cola trae el estado (marcha, disco, tope del día, cada pieza con su estado, clase, sección, nota y error, y la cola de los logs con `--logs`), una caja para pegar enlaces, que funciona igual que `agregar` (etiqueta antes del enlace, `# Sección` y una sección por defecto), y botones para reintentar los fallidos. Un texto pegado sin ningún enlace (un poema, un aforismo, una idea) no va a la cola: con `--bandeja` se guarda como nota, tal cual y sin que lo lea ningún modelo, con fecha y la sección como `pista` en el frontmatter, para repartirlo después. Biblioteca estándar, en `127.0.0.1:8093`, publicado solo al tailnet con `tailscale serve --bg --https=8093 http://127.0.0.1:8093`. Responde 403 a lo que no trae `Tailscale-User-Login`, y con `BAKERS_PANEL_USUARIOS` (logins separados por coma) solo deja pasar a esos. Las acciones son POST con JSON, para que un sitio ajeno abierto en el mismo navegador no las pueda disparar. En Pixilate corre como tarea `-AtStartup` desde un script local que pone esas variables. Las escrituras a `cola.json` llevan un candado entre procesos (`estado.lock`), porque el panel, `bajar` y `analizar` escriben a la vez.

`whisper` y `vision` forman el grupo `reel` de llama-swap: se cargan juntos (~6 GB) y sacan a `bonsai` mientras dure el lote. No pasan por las marchas; con la marcha `ninguna` el gateway se niega antes de bajar nada.

## Marchas

Los Bakers piden el modelo virtual `principal`; el perfil activo de llama-swap decide quién lo atiende. [`servidor/vigilante.py`](servidor/vigilante.py) mira la VRAM cada 5 s y elige la marcha más alta que cabe dejando 1 GB libre:

| Marcha | `principal` es | VRAM propia (contexto 32k) | Cabe si lo demás usa |
|---|---|---|---|
| `alta` | `bonsai` | ~9.5 GB con el escritorio (9.1 propios) | hasta ~2.1 GB |
| `media` | `qwen`, expertos en RAM | ~3.8 GB con el escritorio (3.35 propios) | hasta ~7.9 GB |
| `ninguna` | nada: el Baker responde error y Claude delega en otro lado | 0 | lo que sea |

`whisper`, `vision`, `abliterado`, `bonsai-abliterado`, `vision-abliterado` y `qwen-gpu` no son marchas, pero su VRAM cuenta como nuestra, no como de un juego. Baja al momento, sube solo tras un minuto cabiendo y descarga un modelo que ya no cabe solo cuando no está respondiendo. Probar sin abrir un juego: `uv run servidor/vigilante.py --extra 3000 --duracion 30` en el servidor simula 3 GB ocupados (si el vigilante del servicio sigue corriendo, la vuelve a subir al instante: para una prueba limpia, detenerlo antes). Es para una máquina compartida con juegos; en un servidor dedicado sobra y basta la marcha `alta` fija.

## Servidor (una vez)

Todo lo del nodo de modelos vive en [`servidor/`](servidor/): [`llama-swap.yaml`](servidor/llama-swap.yaml) y [`vigilante.py`](servidor/vigilante.py) son comunes, y cada plataforma tiene su setup. El YAML no nombra binarios: los toma de `BAKERS_LLAMA_SERVER`, `BAKERS_PRISM_SERVER` y `BAKERS_WHISPER_SERVER`, que pone el setup (si falta una, llama-swap no carga la configuración). Para otra máquina, qué modelos caben y cómo medirlos está en [`MODELOS.md`](MODELOS.md).

### Windows ([`servidor/windows/`](servidor/windows/), Pixilate)

La variante para una máquina que también es de juegos: prioridad baja y vigilante. Necesita `~\bakers\` con los dos llama.cpp y los modelos de 1.0a. Para `reel`, además: whisper.cpp b5454 (`whisper-bin-win-cuda-12.4.0-x64.zip` descomprimido en `whisper.cpp\`), `models\ggml-large-v3-turbo-q8_0.bin` y `models\mmproj-Qwen3.6-35B-A3B-F16.gguf` (es `mmproj-F16.gguf` de `unsloth/Qwen3.6-35B-A3B-GGUF`, renombrado). Desde la raíz del clon:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bakers\servidor\windows\setup.ps1
```

En una PowerShell de administrador (las tareas S4U lo piden). Descarga llama-swap v264 (verifica el checksum), instala `uv` con winget si falta (corre el vigilante con `psutil` sin tocar el Python del sistema), genera `~\bakers\api-key.txt` legible solo por la cuenta, lanza con `remote/windows/job.ps1 -AtStartup` los trabajos `bakers` (llama-swap) y `bakers-vigilante`, y publica al tailnet con `tailscale serve --https=8090`. Volver a correrlo es el reinicio limpio (mata también los `llama-server` hijos). La configuración se lee del clon y se recarga sola al cambiar (`-watch-config`); la recarga regresa a la marcha `alta` y el vigilante la corrige en el siguiente ciclo. **Ojo:** recargar apaga todos los modelos y solo espera 30 s a las respuestas en curso (`shutdownTimeout` de llama-swap); una más larga se corta. Hacer `git pull` de un cambio a `llama-swap.yaml` con los Bakers quietos (`baker status` sin nada en `cargados`, o sin otra sesión usándolos).

### Debian ([`servidor/debian/`](servidor/debian/): servidor propio, nube, WSL o una Pi)

Necesita `~/bakers/` con los modelos y los binarios compilados para Linux (por defecto `llama.cpp/build/bin/llama-server`, `llama.cpp-prism/build/bin/llama-server` y `whisper.cpp/build/bin/whisper-server`; otras rutas por variable de entorno). Desde la raíz del clon, con la cuenta que va a correr los modelos:

```bash
bash bakers/servidor/debian/setup.sh                    # servidor dedicado: marcha `alta` fija
BAKERS_VIGILANTE=1 bash bakers/servidor/debian/setup.sh # máquina compartida: también el vigilante
```

Descarga llama-swap v264 para la arquitectura de la máquina (`amd64` o `arm64`, verifica el checksum), genera las dos llaves con `chmod 600` y deja las unidades de systemd `bakers` (y `bakers-vigilante`) con `Restart=always` y `Nice=10`. Al reiniciar, systemd mata también a los `llama-server` hijos, cosa que en Windows hace el setup a mano. Si la máquina está en el tailnet, publica con `tailscale serve`; en WSL no (el nodo de Tailscale es el Windows de fuera). `BAKERS_PUERTO` cambia el 8090. Log: `journalctl -u bakers -f`.

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
uv run baker log
uv run baker run resumidor -f build.log -t "por qué falla el build"
uv run baker run clasificador -f issues.txt -t "tipo de issue" -c bug -c idea -c duda
uv run baker reel https://www.instagram.com/reel/<id>/ video.mp4
```

Desde Claude Code: herramientas `bake(baker, tarea, rutas, categorias)`, `reel(fuentes)` y `bakers_status()`. Cada llamada deja una línea en `~/.bakers/log.jsonl` (Baker, modelo que respondió, tokens que leyó y escribió el Baker, `claude_chars` = caracteres del pedido más la respuesta que paga Claude, intentos, segundos, error). Referencia medida: 1.7k tokens en 21 s con carga del modelo incluida; 30k tokens en 66 s.

`uv run baker log [--desde 2026-10-28]` lo resume por Baker y modelo: llamadas, % ok, reintentos, mediana y p90 de segundos y tokens de salida por segundo (este último cuenta todo el tiempo de la llamada, así que sirve para comparar modelos en el mismo Baker, no como velocidad del modelo). Solo ve a los Bakers: Open WebUI y Qwen Code van directo a llama-swap.

**Varias sesiones a la vez:** no hace falta cola propia. El planificador FIFO de llama-swap (desde v264) deja esperando una petición que sacaría a un modelo que está respondiendo y la atiende al terminar (probado el 2026-10-27: `qwen` llegó a media respuesta de `bonsai`, esperó 42 s y respondió). Las peticiones al modelo ya cargado pasan primero, así que una sesión con muchas llamadas seguidas puede hacer esperar a otra.

**Límite:** 32k tokens por llamada. Texto normal da ~3.5 caracteres por token; algo con hashes (un lockfile) da ~1.5. Si se pasa, el Baker responde "parte la tarea".

**Cuándo conviene:** si lo que lee el Baker supera por 5 a 1 lo que Claude gasta en pedirlo y leer la respuesta. Del log sale directo: `entrada` contra `claude_chars / 3.5` (aproximado; la telemetría de Claude Code, `CLAUDE_CODE_ENABLE_TELEMETRY=1`, da el gasto exacto de la sesión).

### Agente de código (Qwen Code)

Qwen Code (Apache 2.0, `npm install -g @qwen-code/qwen-code`) habla con llama-swap como proveedor `openai`. En `~/.qwen/settings.json`: una entrada por modelo en `modelProviders.openai` con `baseUrl` = `BAKERS_URL` + `/v1`, `envKey` = `BAKERS_API_KEY` y `contextWindowSize` igual al `-c` del modelo (`abliterado` 131072, `bonsai-abliterado` 65536, `qwen` 32768). Apagar `privacy.usageStatisticsEnabled` (manda estadísticas a Alibaba por defecto), `telemetry.enabled`, `ui.enableFollowupSuggestions` y `ui.enableSpeculation` (con `-np 1`, cada llamada extra hace fila). Su primera llamada pesa ~14k tokens; después la caché de prompts en RAM de llama-server cubre lo repetido, aunque un Baker se meta entre turnos.

Skills: solo un subconjunto de código, como junctions de `~/.qwen/skills/<nombre>` a `~/.claude/skills/<nombre>` (`New-Item -ItemType Junction`, sin administrador), para no mantener otra copia. Cada skill listada cuesta su descripción en cada llamada (~150 a 250 tokens) y el cuerpo solo al usarla; las que hablan de herramientas de Claude Code (subagentes, `bake`, artefactos) confunden al modelo. Lo que siempre aplica va en `~/.qwen/QWEN.md` (o `AGENTS.md` por proyecto), que entra completo en cada llamada: corto.

### Chat a mano (Open WebUI)

Open WebUI v0.12.4 en el Docker del WSL de Pixilate ([`webui/compose.yml`](webui/compose.yml)), en `127.0.0.1:8091` y publicado solo al tailnet con `tailscale serve --https=8091`. Habla con llama-swap por la URL del tailnet con la misma llave; la URL, la llave y `WEBUI_SECRET_KEY` van en `~/.config/bakers-webui.env` del WSL. Registro cerrado: otra cuenta se crea desde Admin. Las tareas de fondo (autocompletado, etiquetas, sugerencias, consultas de búsqueda) están apagadas porque con `-np 1` cada una hace fila contra los Bakers.

- **Hojas de contexto:** modelos del Workspace. La hoja maestra que ayuda a escribir las demás está en [`webui/polimata.md`](webui/polimata.md).
- **Contexto lleno:** llama-server responde 400 (`exceed_context_size_error`) y no recorta. Lo evita la compactación de Open WebUI (Admin > Settings, `chat.context_compaction`): umbral global de 20k tokens para los modelos de 32k y `compact_token_threshold` en los parámetros avanzados de los de más contexto (`abliterado` 100k, `bonsai-abliterado` 48k; las hojas del Workspace llevan el suyo). Cuenta con el `usage` real de la respuesta anterior, que incluye las definiciones de las herramientas integradas (~8k tokens por petición), y resume con el modelo del propio chat. Un filtro que contaba solo el texto visible se quedaba corto.
- **Respaldo:** historial, hojas y conocimiento viven en el volumen `bakers-webui_open-webui` (`webui.db`). Copiarlo con la API de backup de SQLite desde el contenedor, no el archivo en caliente:

```bash
ssh pixilate 'wsl -d Debian -- docker exec -i bakers-webui-open-webui-1 python -' < bakers/webui/respaldo.py   # copia consistente a /tmp
ssh pixilate 'wsl -d Debian -- docker cp bakers-webui-open-webui-1:/tmp/webui-respaldo.db /mnt/c/Users/<cuenta>/bakers/respaldos/'
```

## Seguridad

- llama-swap y cada llama-server escuchan solo en `127.0.0.1`; afuera solo llega `tailscale serve`, que exige estar en el tailnet. La ACL deja a los invitados solo en el 443.
- Sin `Authorization: Bearer <llave>` llama-swap no responde. Una llave por cliente: `api-key.txt` (Aerilate) y `api-key-pi.txt` (frambuesa-yi, la Pi pública), ninguna en el repo. Si una se filtra, borrar solo ese archivo y volver a correr el setup; la otra sigue igual.
- La ACL de Tailscale deja a `tag:publico` (frambuesa-yi) llegar a Pixilate solo en el 8090, con pruebas en la política que lo verifican al guardar.
- Cortar todo: `ssh pixilate "tailscale serve --https=8090 off"`.
- Las llaves solo las lee la cuenta del servicio: `chmod 600` en Debian; en Windows, `icacls` con `EQUIPO\cuenta`: si la cuenta se llama igual que el equipo, el nombre a secas resuelve al equipo.

## Tests

```powershell
uv run pytest
```

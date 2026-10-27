"""Baker `reel`: un reel (o video corto) a nota de inspiración, con el formato de la skill `inspiracion`.

Aerilate descarga y corta (yt-dlp, ffmpeg); Pixilate solo sirve modelos por llama-swap: whisper.cpp
transcribe y Qwen con visión lee fotogramas, transcripción y caption en una sola llamada.
Una pieza por enlace, a pedido de Remi: nada de rastrear cuentas, feeds ni guardados en bloque.
"""
import base64
import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from . import core
from .core import BakerError
from .schemas import Reel

CARPETA = Path.home() / ".bakers" / "reels"  # fuera de cualquier repo: es material de otra persona
MAX_SEGUNDOS = 600  # reels y shorts; un video largo va por la skill `inspiracion` a mano
MAX_FRAMES = 8      # ~660 tokens cada uno a 540 px de ancho: caben con holgura en los 32k
CADA = 3.0          # segundos entre fotogramas en videos cortos
LOGPROB_MIN = -1.0  # segmentos de whisper por debajo son alucinación (letra inventada sobre música)


def _correr(*args: str, cwd: Path | None = None) -> str:
    if not shutil.which(args[0]):
        raise BakerError(f"Falta {args[0]} en el PATH de Aerilate")
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise BakerError(f"{args[0]} falló ({r.returncode}): {r.stderr.strip()[-500:]}")
    return r.stdout


def _mmss(s: float) -> str:
    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


def _obtener(fuente: str, navegador: str) -> tuple[Path, dict]:
    """Ruta local del video y sus metadatos (vacíos si es un archivo local)."""
    local = Path(fuente).expanduser()
    if local.is_file():
        return local, {}
    if not fuente.startswith(("http://", "https://")):
        raise BakerError(f"Ni archivo ni enlace: {fuente}")
    CARPETA.mkdir(parents=True, exist_ok=True)
    # Instagram pide sesión: las cookies se leen del navegador al momento, nunca se copian a disco
    salida = _correr("yt-dlp", "--cookies-from-browser", navegador, "--no-playlist", "--no-progress",
                     "--match-filter", f"duration<={MAX_SEGUNDOS}", "-f", "b[ext=mp4]/b",
                     "--write-info-json", "-o", "%(id)s/video.%(ext)s", "--print", "after_move:filepath",
                     fuente, cwd=CARPETA)
    if not salida.strip():
        raise BakerError(f"yt-dlp no bajó nada (¿dura más de {MAX_SEGUNDOS} s?): {fuente}")
    video = Path(salida.strip().splitlines()[-1])
    info = json.loads((video.parent / "video.info.json").read_text("utf-8"))
    return video, {k: info.get(k) for k in ("channel", "uploader", "description", "webpage_url")}


def _sondear(video: Path) -> tuple[float, bool]:
    datos = json.loads(_correr("ffprobe", "-v", "error", "-of", "json", "-show_entries",
                               "format=duration:stream=codec_type", str(video)))
    duracion = float(datos["format"]["duration"])
    if duracion > MAX_SEGUNDOS:
        raise BakerError(f"Dura {duracion:.0f} s, más de {MAX_SEGUNDOS}: va por la skill inspiracion a mano")
    return duracion, any(s["codec_type"] == "audio" for s in datos["streams"])


def _fotogramas(video: Path, trabajo: Path, duracion: float) -> list[tuple[float, Path]]:
    """Muestreo parejo en vez de cambios de escena: el texto que aparece sobre un plano fijo también cuenta."""
    n = max(1, min(MAX_FRAMES, round(duracion / CADA)))
    carpeta = trabajo / "frames"
    carpeta.mkdir(exist_ok=True)
    tomas = []
    for k in range(n):
        t = (k + 0.5) * duracion / n
        jpg = carpeta / f"{k + 1:02d}.jpg"
        _correr("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(jpg))
        tomas.append((t, jpg))
    return tomas


def _transcribir(c: httpx.Client, cfg: dict, video: Path, trabajo: Path) -> list[dict]:
    wav = trabajo / "audio.wav"  # whisper.cpp sin --convert solo acepta WAV de 16 kHz
    _correr("ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav))
    try:
        r = c.post("/v1/audio/transcriptions",
                   data={"model": cfg["transcriptor"], "response_format": "verbose_json", "temperature": "0.0"},
                   files={"file": ("audio.wav", wav.read_bytes(), "audio/wav")})
    except httpx.HTTPError as e:
        raise BakerError(f"Sin conexión con llama-swap en {c.base_url}: {e!r}") from e
    if r.is_error:
        raise BakerError(f"whisper respondió {r.status_code}: {r.text[:500]}")
    segmentos = [{"t": _mmss(s["start"]), "texto": s["text"].strip(), "logprob": round(s.get("avg_logprob", 0), 2)}
                 for s in r.json().get("segments", [])]
    (trabajo / "transcripcion.json").write_text(json.dumps(segmentos, ensure_ascii=False, indent=1), "utf-8")
    # Sin VAD, whisper.cpp inventa letra sobre la música (logprob de -3 a -9) y eso mandó a la visión a un bucle
    # (2026-10-27); -1 es el umbral de Whisper. También repite "*crickets*" en silencios: una vez basta.
    limpios = []
    for s in segmentos:
        if s["texto"] and s["logprob"] >= LOGPROB_MIN and (not limpios or limpios[-1]["texto"] != s["texto"]):
            limpios.append({"t": s["t"], "texto": s["texto"]})
    return limpios


def _mensaje(meta: dict, duracion: float, segmentos: list[dict], tomas: list[tuple[float, Path]]) -> list[dict]:
    cabecera = [f"Duration: {_mmss(duracion)}"]
    if meta.get("channel") or meta.get("uploader"):
        cabecera.append(f"Account: {meta.get('channel') or meta.get('uploader')}")
    if meta.get("description"):
        cabecera.append(f"Caption:\n{meta['description']}")
    habla = "\n".join(f"[{s['t']}] {s['texto']}" for s in segmentos) or "(no speech)"
    partes = [{"type": "text", "text": "\n".join(cabecera) + f"\n\nTranscript:\n{habla}\n\nFrames:"}]
    for t, jpg in tomas:
        partes.append({"type": "text", "text": f"[{_mmss(t)}]"})
        datos = base64.b64encode(jpg.read_bytes()).decode()
        partes.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{datos}"}})
    return partes


def _nota(r: Reel, meta: dict, fuente: str, duracion: float) -> str:
    """Borrador con el formato de `inspiracion`; verificar recursos y escribir la Aplicación queda a Claude."""
    cuenta = meta.get("channel") or meta.get("uploader") or "?"
    lineas = [f"# {r.tema}", "", f"- Fuente: @{cuenta}, {meta.get('webpage_url') or fuente}",
              f"- Formato: reel, {_mmss(duracion)}", "", "## Idea central", r.idea_central, "", "## Recursos",
              "| Recurso | Qué es | Dónde | Verificado |", "|---|---|---|---|",
              *(f"| {x.nombre} | {x.que_es} | {x.donde} | no |" for x in r.recursos), "", "## Citas",
              *(f'- [{x.t}] "{x.texto}"' for x in r.citas), "", "## Texto en pantalla",
              *(f"- {x}" for x in r.texto_en_pantalla), "", "## Visual", r.visual]
    if r.afirmaciones:
        lineas += ["", "## Afirmaciones por verificar", *(f"- {x}" for x in r.afirmaciones)]
    return "\n".join(lineas) + "\n\n## Aplicación\n- (pendiente)\n"


def _uno(c: httpx.Client, cfg: dict, fuente: str) -> dict:
    uso = {"modelo": None, "entrada": 0, "salida": 0, "intentos": 0}
    inicio, error, res = time.monotonic(), None, None
    pasos, ultimo = {}, inicio  # segundos por paso, para saber dónde se va el tiempo

    def marca(paso: str) -> None:
        nonlocal ultimo
        pasos[paso], ultimo = round(time.monotonic() - ultimo, 2), time.monotonic()

    try:
        video, meta = _obtener(fuente, cfg["navegador"])
        marca("descarga")
        trabajo = video.parent if meta else CARPETA / video.stem
        trabajo.mkdir(parents=True, exist_ok=True)
        duracion, con_audio = _sondear(video)
        segmentos = _transcribir(c, cfg, video, trabajo) if con_audio else []
        marca("whisper")  # incluye el ffmpeg del audio y, en la primera del lote, cargar whisper
        tomas = _fotogramas(video, trabajo, duracion)
        marca("fotogramas")
        r = core._llamar(c, cfg, _mensaje(meta, duracion, segmentos, tomas), Reel, uso)
        marca("vision")
        nota = trabajo / "nota.md"
        nota.write_text(_nota(r, meta, fuente, duracion), "utf-8")
        res = {"fuente": fuente, "nota": str(nota), "transcripcion": str(trabajo / "transcripcion.json"),
               **r.model_dump()}
        return res
    except BakerError as e:
        error = str(e)
        return {"fuente": fuente, "error": error}
    finally:
        respuesta = len(json.dumps(res, ensure_ascii=False)) if res is not None else len(error or "")
        core._registrar(baker="reel", archivos=1, segundos=round(time.monotonic() - inicio, 2),
                        ok=error is None, error=error, claude_chars=len(fuente) + respuesta, pasos=pasos, **uso)


def reel(fuentes: list[str]) -> list[dict]:
    """Una nota por fuente (enlace o archivo local). Un fallo no detiene a las demás: queda en su `error`."""
    if not fuentes:
        raise BakerError("Sin fuentes: pasa enlaces de reels o rutas de videos")
    if core.estado()["marcha"] == "ninguna":
        raise BakerError("Pixilate no tiene VRAM libre (marcha 'ninguna', probablemente un juego): "
                         "usa la skill inspiracion a mano")
    cfg = core.BAKERS["reel"]
    # whisper y vision quedan cargados juntos (grupo `reel` de llama-swap) mientras dure el lote
    with core._cliente(timeout=600) as c:
        return [_uno(c, cfg, f) for f in fuentes]

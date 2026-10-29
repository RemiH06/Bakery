"""Núcleo compartido por el MCP y la CLI: lee archivos en local, llama a llama-swap con esquema
forzado, valida con Pydantic y deja una línea por llamada en el log JSONL."""
import json
import os
import time
import tomllib
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from .schemas import Ficha, Resumen, clasificacion

# Esquemas de una sola llamada que leen todos los archivos juntos
UNA_LLAMADA: dict[str, type[BaseModel]] = {"resumen": Resumen, "ficha": Ficha}

BAKERS: dict[str, dict] = tomllib.loads(files("bakers").joinpath("bakers.toml").read_text("utf-8"))
LOG = Path.home() / ".bakers" / "log.jsonl"
# Filtro barato antes de mandar nada; el límite real lo pone llama-server (32k tokens) y su error se traduce abajo.
# Texto normal da ~3.5 caracteres por token, pero un lockfile con hashes da ~1.5 (medido el 2026-10-27).
MAX_CHARS = 90_000
MAX_BYTES = 20_000_000  # no leer un archivo enorme solo para rechazarlo después
INTENTOS = 2  # el primero más un reintento; después, error para que Claude decida
# Una respuesta útil cabe de sobra; sin tope, Bonsai se quedó en bucle 1,129 s y 16.7k tokens (2026-10-27)
MAX_SALIDA = 4096


class BakerError(Exception):
    """Falla que Claude o Remi pueden corregir (ruta, tope, esquema, conexión)."""


def _cliente(timeout: float) -> httpx.Client:
    try:
        url, key = os.environ["BAKERS_URL"], os.environ["BAKERS_API_KEY"]
    except KeyError as e:
        raise BakerError(f"Falta la variable de entorno {e.args[0]} (ver bakers/README.md)") from None
    return httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {key}"}, timeout=timeout)


def leer(rutas: list[str]) -> list[tuple[Path, str]]:
    if not rutas:
        raise BakerError("Sin rutas: un Baker siempre lee archivos, nunca contenido pegado")
    textos = []
    for ruta in rutas:
        p = Path(ruta).expanduser()
        if not p.is_file():
            raise BakerError(f"No existe o no es archivo: {p}")
        if p.stat().st_size > MAX_BYTES:
            raise BakerError(f"Demasiado grande ({p.stat().st_size} bytes): {p}")
        crudo = p.read_bytes()
        if b"\0" in crudo:
            raise BakerError(f"Parece binario: {p}")
        textos.append((p, crudo.decode("utf-8", errors="replace")))
    return textos


def _tope(mensaje: str) -> str:
    if len(mensaje) > MAX_CHARS:
        raise BakerError(f"{len(mensaje)} caracteres pasan el tope de {MAX_CHARS}: parte la tarea en varias llamadas")
    return mensaje


def _llamar(c: httpx.Client, cfg: dict, mensaje: str | list[dict], esquema: type[BaseModel], uso: dict,
            revisar: Callable[[BaseModel], None] = lambda _: None, historial: list[dict] = ()) -> BaseModel:
    """`mensaje` es texto o, para un modelo con visión, la lista de partes (texto e imágenes) de OpenAI.
    `historial` son los turnos previos (`role` y `content`) de un Baker multi-turno, entre sistema y mensaje."""
    cuerpo = {
        "model": cfg["modelo"],
        "temperature": cfg["temperatura"],
        "max_tokens": cfg.get("max_salida", MAX_SALIDA),
        "messages": [{"role": "system", "content": cfg["sistema"]}, *historial,
                     {"role": "user", "content": _tope(mensaje) if isinstance(mensaje, str) else mensaje}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": esquema.__name__, "schema": esquema.model_json_schema()},
        },
    }
    for _ in range(INTENTOS):
        try:
            r = c.post("/v1/chat/completions", json=cuerpo)
        except httpx.HTTPError as e:
            raise BakerError(f"Sin conexión con llama-swap en {c.base_url}: {e!r}") from e
        if r.is_error and "no model id" in r.text:
            raise BakerError("Ningún modelo cabe ahora en Pixilate (marcha 'ninguna', probablemente un juego): "
                             "delega en Haiku o lee en la sesión")
        if r.is_error and "exceed_context_size_error" in r.text:
            err = r.json()["error"]
            raise BakerError(f"{err['n_prompt_tokens']} tokens pasan el contexto de {err['n_ctx']}: "
                             "parte la tarea en varias llamadas")
        if r.is_error:
            raise BakerError(f"llama-swap respondió {r.status_code}: {r.text[:500]}")
        datos = r.json()
        uso["modelo"] = datos.get("model")
        uso["entrada"] += datos["usage"]["prompt_tokens"]
        uso["salida"] += datos["usage"]["completion_tokens"]
        uso["intentos"] += 1
        # Reintentar no sirve: con temperatura baja el bucle se repite
        if datos["choices"][0].get("finish_reason") == "length":
            raise BakerError(f"El modelo llegó al tope de {cuerpo['max_tokens']} tokens sin cerrar la respuesta (bucle): "
                             "acota la tarea o pártela")
        # llama.cpp ignora en silencio palabras de JSON Schema que no soporta: se valida otra vez aquí
        try:
            obj = esquema.model_validate_json(datos["choices"][0]["message"]["content"])
            revisar(obj)
            return obj
        except (ValidationError, ValueError) as e:
            error = e
    raise BakerError(f"Respuesta fuera de esquema tras {INTENTOS} intentos: {error}")


def _una_llamada(c, cfg, tarea, textos, esquema, uso) -> dict:
    cuerpo = "\n\n".join(f"=== {p.name} ===\n{t}" for p, t in textos)
    return _llamar(c, cfg, f"Task: {tarea}\n\n{cuerpo}", esquema, uso).model_dump()


def _clasificar(c, cfg, tarea, textos, categorias, uso) -> dict:
    if not categorias or len(set(categorias)) < 2:
        raise BakerError("El clasificador necesita al menos dos categorías distintas")
    esquema = clasificacion(list(dict.fromkeys(categorias)))
    items = [(p, n, linea.strip()) for p, t in textos for n, linea in enumerate(t.splitlines(), 1) if linea.strip()]
    if not items:
        raise BakerError("Los archivos no tienen líneas que clasificar")

    por_categoria: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i in range(0, len(items), cfg["lote"]):
        trozo = items[i:i + cfg["lote"]]
        numerado = "\n".join(f"{k}: {texto}" for k, (_, _, texto) in enumerate(trozo, 1))
        mensaje = f"Task: {tarea}\nAllowed categories: {', '.join(categorias)}\n\n{numerado}"

        def revisar(obj, esperados=sorted(range(1, len(trozo) + 1))):
            if sorted(it.n for it in obj.items) != esperados:
                raise ValueError("faltan o sobran ítems en la respuesta")

        for it in _llamar(c, cfg, mensaje, esquema, uso, revisar).items:
            p, linea, _ = trozo[it.n - 1]
            por_categoria[it.categoria][str(p)].append(linea)

    return {
        "conteo": {cat: sum(map(len, arch.values())) for cat, arch in por_categoria.items()},
        "por_categoria": {cat: dict(arch) for cat, arch in por_categoria.items()},
    }


def bake(baker: str, tarea: str, rutas: list[str], categorias: list[str] | None = None) -> dict:
    if baker not in BAKERS:
        raise BakerError(f"No existe el Baker {baker!r}; hay: {', '.join(BAKERS)}")
    cfg = BAKERS[baker]
    if cfg["esquema"] in ("reel", "chat"):
        raise BakerError(f"{baker} no lee archivos de texto: tiene su propia herramienta (CLI: baker {baker})")
    uso = {"modelo": None, "entrada": 0, "salida": 0, "intentos": 0}
    inicio, error, res = time.monotonic(), None, None
    try:
        textos = leer(rutas)
        # tiempo largo: la primera llamada puede esperar a que llama-swap cargue el modelo desde disco
        with _cliente(timeout=600) as c:
            if cfg["esquema"] in UNA_LLAMADA:
                res = _una_llamada(c, cfg, tarea, textos, UNA_LLAMADA[cfg["esquema"]], uso)
            else:
                res = _clasificar(c, cfg, tarea, textos, categorias, uso)
        return res
    except Exception as e:
        error = str(e)
        raise
    finally:
        # Lo que Claude paga por la llamada (pedido + respuesta); contra `entrada` da la razón 5 a 1
        pedido = len(json.dumps([tarea, rutas, categorias], ensure_ascii=False))
        respuesta = len(json.dumps(res, ensure_ascii=False)) if res is not None else len(error or "")
        _registrar(baker=baker, archivos=len(rutas), segundos=round(time.monotonic() - inicio, 2),
                   ok=error is None, error=error, claude_chars=pedido + respuesta, **uso)


def _registrar(**campos) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    linea = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **campos}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def estado() -> dict:
    """Qué marcha eligió el vigilante, a qué modelo apunta cada Baker y qué está cargado."""
    with _cliente(timeout=10) as c:
        try:
            perfiles, corriendo = c.get("/api/profiles"), c.get("/running")
            perfiles.raise_for_status()
            corriendo.raise_for_status()
        except httpx.HTTPError as e:
            raise BakerError(f"Sin respuesta de llama-swap en {c.base_url}: {e!r}") from e
    activo = perfiles.json()["active"]
    pins = next((p["pins"] for p in perfiles.json()["profiles"] if p["id"] == activo), {})
    return {
        "marcha": activo,
        "bakers": {n: pins.get(cfg["modelo"], cfg["modelo"]) or None for n, cfg in BAKERS.items()},
        "cargados": [m["model"] for m in corriendo.json()["running"]],
    }


def resumen_log(desde: str | None = None) -> list[dict]:
    """Uso real por Baker y modelo, para comparar modelos sin montar Langfuse. `desde`: fecha ISO."""
    grupos: dict[tuple, list[dict]] = defaultdict(list)
    for linea in LOG.read_text("utf-8").splitlines() if LOG.exists() else []:
        r = json.loads(linea)
        if not desde or r["ts"] >= desde:
            grupos[(r["baker"], (r["modelo"] or "sin respuesta").rsplit("/", 1)[-1])].append(r)
    filas = []
    for (baker, modelo), rs in sorted(grupos.items()):
        seg = sorted(r["segundos"] for r in rs if r["ok"])
        filas.append({
            "baker": baker, "modelo": modelo, "llamadas": len(rs),
            "ok_%": round(100 * len(seg) / len(rs)),
            "reintentos": sum(r["intentos"] > 1 for r in rs),
            "seg_mediana": seg[len(seg) // 2] if seg else None,
            "seg_p90": seg[int(len(seg) * 0.9)] if seg else None,
            # Incluye leer el prompt y los pasos de `reel`: sirve para comparar, no es la velocidad del modelo
            "salida_tok_s": round(sum(r["salida"] for r in rs if r["ok"]) / sum(seg), 1) if seg else None,
        })
    return filas

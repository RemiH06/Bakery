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

from .schemas import Resumen, clasificacion

BAKERS: dict[str, dict] = tomllib.loads(files("bakers").joinpath("bakers.toml").read_text("utf-8"))
LOG = Path.home() / ".bakers" / "log.jsonl"
# shortcut: tope por caracteres (~3.5 por token) para no pasar del contexto de 32k; medir con /tokenize si se queda corto.
MAX_CHARS = 90_000
MAX_BYTES = 20_000_000  # no leer un archivo enorme solo para rechazarlo después
INTENTOS = 2  # el primero más un reintento; después, error para que Claude decida


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


def _llamar(c: httpx.Client, cfg: dict, mensaje: str, esquema: type[BaseModel], uso: dict,
            revisar: Callable[[BaseModel], None] = lambda _: None) -> BaseModel:
    cuerpo = {
        "model": cfg["modelo"],
        "temperature": cfg["temperatura"],
        "messages": [{"role": "system", "content": cfg["sistema"]}, {"role": "user", "content": _tope(mensaje)}],
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
        if r.is_error:
            raise BakerError(f"llama-swap respondió {r.status_code}: {r.text[:500]}")
        datos = r.json()
        uso["modelo"] = datos.get("model")
        uso["entrada"] += datos["usage"]["prompt_tokens"]
        uso["salida"] += datos["usage"]["completion_tokens"]
        uso["intentos"] += 1
        # llama.cpp ignora en silencio palabras de JSON Schema que no soporta: se valida otra vez aquí
        try:
            obj = esquema.model_validate_json(datos["choices"][0]["message"]["content"])
            revisar(obj)
            return obj
        except (ValidationError, ValueError) as e:
            error = e
    raise BakerError(f"Respuesta fuera de esquema tras {INTENTOS} intentos: {error}")


def _resumir(c, cfg, tarea, textos, uso) -> dict:
    cuerpo = "\n\n".join(f"=== {p.name} ===\n{t}" for p, t in textos)
    return _llamar(c, cfg, f"Task: {tarea}\n\n{cuerpo}", Resumen, uso).model_dump()


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
    uso = {"modelo": None, "entrada": 0, "salida": 0, "intentos": 0}
    inicio, error = time.monotonic(), None
    try:
        textos = leer(rutas)
        # tiempo largo: la primera llamada puede esperar a que llama-swap cargue el modelo desde disco
        with _cliente(timeout=600) as c:
            if cfg["esquema"] == "resumen":
                return _resumir(c, cfg, tarea, textos, uso)
            return _clasificar(c, cfg, tarea, textos, categorias, uso)
    except Exception as e:
        error = str(e)
        raise
    finally:
        _registrar(baker=baker, archivos=len(rutas), segundos=round(time.monotonic() - inicio, 2),
                   ok=error is None, error=error, **uso)


def _registrar(**campos) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    linea = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **campos}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def estado() -> dict:
    """Qué modelo atiende cada Baker y qué tiene cargado llama-swap ahora."""
    with _cliente(timeout=10) as c:
        try:
            r = c.get("/running")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise BakerError(f"Sin respuesta de llama-swap en {c.base_url}: {e!r}") from e
    return {"bakers": {n: cfg["modelo"] for n, cfg in BAKERS.items()}, "cargados": r.json()}

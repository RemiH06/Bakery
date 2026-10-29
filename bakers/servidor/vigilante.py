# /// script
# requires-python = ">=3.10"
# dependencies = ["psutil"]
# ///
"""Vigilante de los Bakers: cada 5 s mira la VRAM y la RAM y elige la marcha más alta que cabe (perfil de llama-swap).

Baja al momento, sube solo tras un minuto estable y nunca descarga un modelo a media respuesta. Es para una máquina
compartida (Pixilate con juegos); en un servidor dedicado sobra y basta con dejar fija la marcha `alta`. Igual en
Windows y Linux: `nvidia-smi` y la API de llama-swap no cambian. Lo lanza el setup de cada plataforma.

    uv run vigilante.py                           (o python3 vigilante.py con psutil instalado)
    uv run vigilante.py --extra 3000 --duracion 60       simula 3 GB de VRAM de otro programa por un minuto
    uv run vigilante.py --extra-ram 30000 --duracion 60  lo mismo con 30 GB de RAM

BAKERS_URL (default http://127.0.0.1:8090) y BAKERS_LLAVE (default ~/bakers/api-key.txt) cambian a quién vigila."""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

API = os.environ.get("BAKERS_URL", "http://127.0.0.1:8090").rstrip("/")
LLAVE = Path(os.environ.get("BAKERS_LLAVE", Path.home() / "bakers" / "api-key.txt"))

# VRAM y RAM propias de cada modelo con el -c de llama-swap.yaml, en MiB, sin lo del escritorio (2026-10-27; `qwen`,
# `abliterado` y `bonsai-abliterado` en 1.0l). Bonsai también copia el modelo a RAM (~9.5 GB residentes); Qwen deja
# ~4.6 GB privados más los expertos mapeados del GGUF, que llegan a ~20 GB conforme se usan (si faltan, no truena: se
# vuelve lento leyendo disco). Medido en Windows con la RTX 3060: en otro hardware, medir de nuevo.
MARCHAS = [
    {"perfil": "alta", "modelo": "bonsai", "vram": 9100, "ram": 10000},
    {"perfil": "media", "modelo": "qwen", "vram": 3600, "ram": 20000},
    {"perfil": "ninguna", "modelo": None, "vram": 0, "ram": 0},
]
# Modelos fuera de las marchas (se piden por nombre): su VRAM también es nuestra, no de un juego
FUERA = {"abliterado": 6900, "bonsai-abliterado": 8900, "whisper": 1500, "vision": 4700, "vision-abliterado": 4700,
         "qwen-gpu": 11200}
SERVIDORES = {"llama-server", "llama-server.exe", "whisper-server", "whisper-server.exe"}
MARGEN = 1024      # MiB de VRAM libres para que lo demás (el juego) no se quede corto
MARGEN_RAM = 2048  # lo mismo en RAM
SUBIR_TRAS = 60    # segundos cabiendo sin interrupción antes de subir a esa marcha


def log(msg: str) -> None:
    print(f"[vigilante] {datetime.now():%Y-%m-%dT%H:%M:%S} {msg}", flush=True)


def api(ruta: str, metodo: str = "GET", cuerpo: dict | None = None, base: str = API, auth: bool = True):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(f"{base}{ruta}", data=datos, method=metodo)
    if auth:
        req.add_header("Authorization", f"Bearer {LLAVE.read_text().strip()}")
    if datos:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        texto = r.read()
    return json.loads(texto) if texto else None


def vram() -> tuple[int, int]:
    salida = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, check=True).stdout
    usado, total = (int(x) for x in salida.splitlines()[0].split(","))
    return usado, total


def ram_nuestra() -> float:
    """MiB residentes de nuestros servidores: se liberan al cambiar de modelo."""
    total = 0
    for p in psutil.process_iter(["name", "memory_info"]):
        if p.info["name"] in SERVIDORES and p.info["memory_info"]:
            total += p.info["memory_info"].rss
    return total / 2**20


def ciclo(extra: int, extra_ram: int, cabe_desde: dict) -> None:
    usado, total = vram()
    corriendo = api("/running")["running"]
    modelos = {c["model"] for c in corriendo}
    cargado = next((m for m in MARCHAS if m["modelo"] in modelos), None)
    # Lo que usa todo lo demás: el total menos lo que ocupan nuestros modelos cargados
    por_modelo = {m["modelo"]: m["vram"] for m in MARCHAS if m["modelo"]} | FUERA
    otros = usado + extra - sum(por_modelo.get(m, 0) for m in modelos)
    ram_libre = psutil.virtual_memory().available / 2**20 + ram_nuestra() - extra_ram
    activo = api("/api/profiles")["active"]
    i_actual = next((i for i, m in enumerate(MARCHAS) if m["perfil"] == activo), None)

    ahora = time.monotonic()
    nuevo = len(MARCHAS) - 1
    for i, m in enumerate(MARCHAS):
        cabe = m["vram"] == 0 or (m["vram"] + otros + MARGEN <= total and m["ram"] + MARGEN_RAM <= ram_libre)
        if not cabe:
            cabe_desde.pop(m["perfil"], None)
            continue
        cabe_desde.setdefault(m["perfil"], ahora)
        # Bajar o quedarse: inmediato. Subir: solo si lleva un minuto cabiendo.
        estable = ahora - cabe_desde[m["perfil"]] >= SUBIR_TRAS
        if i_actual is None or i >= i_actual or estable:
            nuevo = i
            break

    if nuevo != i_actual:
        api("/api/profiles/active", "PUT", {"name": MARCHAS[nuevo]["perfil"]})
        log(f"marcha {activo} -> {MARCHAS[nuevo]['perfil']} (otros usan {otros} de {total} MiB de VRAM; "
            f"RAM libre {int(ram_libre)} MiB)")

    # Un modelo por encima de la marcha permitida se descarga, pero nunca a media respuesta
    if cargado and MARCHAS.index(cargado) < nuevo:
        proxy = next(c["proxy"] for c in corriendo if c["model"] == cargado["modelo"])
        if not any(s.get("is_processing") for s in api("/slots", base=proxy, auth=False)):
            api(f"/api/models/unload/{cargado['modelo']}", "POST")
            log(f"descargado {cargado['modelo']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extra", type=int, default=0, help="MiB de VRAM simulados de otro programa")
    ap.add_argument("--extra-ram", type=int, default=0, help="MiB de RAM simulados de otro programa")
    ap.add_argument("--duracion", type=int, default=0, help="segundos; 0 es para siempre")
    a = ap.parse_args()
    fin = time.monotonic() + a.duracion if a.duracion else float("inf")
    cabe_desde: dict[str, float] = {}
    while time.monotonic() < fin:
        try:
            ciclo(a.extra, a.extra_ram, cabe_desde)
        except Exception as e:  # sin llama-swap todavía, o un error pasajero: seguir vigilando
            log(f"sin llama-swap o error: {e!r}")
        time.sleep(5)


if __name__ == "__main__":
    main()

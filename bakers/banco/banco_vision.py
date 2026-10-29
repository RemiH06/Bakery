"""Banco de visión (1.0n): misma llamada que `reel` contra un llama-server suelto, variando fotogramas.

    uv run python banco/banco_vision.py <etiqueta> <puerto> <reel> [<reel> ...]

<reel> es un código ya bajado en ~/.bakers/reels/ (con su transcripcion.json). Variantes de fotogramas en VARIANTES
(default "8x540 8x360 4x540"). Guarda timings y salida en ~/.bakers/banco/resultados.jsonl, fuera del repo.
Lo usa variantes.sh para comparar flags de llama-server."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from bakers import core, reel
from bakers.schemas import Reel

SALIDA = Path.home() / ".bakers" / "banco"
etiqueta, puerto, codigos = sys.argv[1], sys.argv[2], sys.argv[3:]
cfg = core.BAKERS["reel"]


def tomas(trabajo: Path, duracion: float, ancho: int, n: int) -> list[tuple[float, Path]]:
    carpeta = SALIDA / "frames" / trabajo.name / f"{n}x{ancho}"
    carpeta.mkdir(parents=True, exist_ok=True)
    video = reel.bajado(trabajo.name)
    res = []
    for k in range(n):
        t = (k + 0.5) * duracion / n
        jpg = carpeta / f"{k + 1:02d}.jpg"
        if not jpg.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={ancho}:-2", "-q:v", "4", str(jpg)], check=True)
        res.append((t, jpg))
    return res


with httpx.Client(base_url=f"http://127.0.0.1:{puerto}", timeout=900) as c:
    for codigo in codigos:
        trabajo = reel.CARPETA / codigo
        video = reel.bajado(codigo)
        meta = reel._metadatos(video)
        duracion, _ = reel._sondear(video)
        segs = [s for s in json.loads((trabajo / "transcripcion.json").read_text("utf-8"))
                if s["texto"] and s["logprob"] >= reel.LOGPROB_MIN]
        variantes = [tuple(map(int, v.split("x"))) for v in os.environ.get("VARIANTES", "8x540 8x360 4x540").split()]
        for n, ancho in variantes:
            cuerpo = {
                "model": "x", "temperature": cfg["temperatura"], "max_tokens": core.MAX_SALIDA,
                "cache_prompt": False,
                "messages": [{"role": "system", "content": cfg["sistema"]},
                             {"role": "user", "content": reel._mensaje(meta, duracion, segs,
                                                                       tomas(trabajo, duracion, ancho, n))}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "Reel", "schema": Reel.model_json_schema()}},
            }
            t0 = time.monotonic()
            d = c.post("/v1/chat/completions", json=cuerpo).json()
            tm = d.get("timings", {})
            fila = {"etiqueta": etiqueta, "reel": codigo, "frames": f"{n}x{ancho}",
                    "seg": round(time.monotonic() - t0, 1),
                    "prompt_n": tm.get("prompt_n"), "prompt_s": round(tm.get("prompt_ms", 0) / 1000, 1),
                    "gen_n": tm.get("predicted_n"), "gen_s": round(tm.get("predicted_ms", 0) / 1000, 1),
                    "fin": d["choices"][0].get("finish_reason") if "choices" in d else d,
                    "salida": d["choices"][0]["message"]["content"] if "choices" in d else None}
            SALIDA.mkdir(parents=True, exist_ok=True)
            with open(SALIDA / "resultados.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
            print({k: v for k, v in fila.items() if k != "salida"}, flush=True)

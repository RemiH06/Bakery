"""Chat largo por llama-swap mientras la máquina hace otra cosa (1.0n: un juego abierto), como Open WebUI o Qwen Code.

    uv run python banco/chat_juego.py <etiqueta> [modelo]   (default `abliterado`)

Manda ~20k tokens de documentación y código del repo, imprime una línea por cada 100 tokens y los timings al final.
Usa BAKERS_URL y BAKERS_API_KEY."""
import json
import os
import sys
import time
from pathlib import Path

import httpx

etiqueta = sys.argv[1]
modelo = sys.argv[2] if len(sys.argv) > 2 else "abliterado"
bakers = Path(__file__).parents[1]
contexto = "\n\n".join(p.read_text("utf-8") for p in [bakers / "README.md", bakers.parent / "remote" / "README.md",
                                                       bakers / "src" / "bakers" / "core.py",
                                                       bakers / "src" / "bakers" / "reel.py"])
cuerpo = {"model": modelo, "stream": True, "max_tokens": 1500, "temperature": 0.3, "cache_prompt": False,
          "stream_options": {"include_usage": True}, "timings_per_token": False,
          "messages": [{"role": "user", "content": contexto + "\n\nExplica en español, con detalle y por secciones, "
                        "cómo funciona Bakers de punta a punta: marchas, vigilante, modelos y Baker reel."}]}
t0 = time.monotonic()
primero, n, fin, timings = None, 0, None, None
with httpx.Client(timeout=httpx.Timeout(900, connect=10)) as c:
    with c.stream("POST", os.environ["BAKERS_URL"].rstrip("/") + "/v1/chat/completions", json=cuerpo,
                  headers={"Authorization": f"Bearer {os.environ['BAKERS_API_KEY']}"}) as r:
        if r.is_error:
            r.read()
            print(f"[{etiqueta}] error {r.status_code}: {r.text[:300]}", flush=True)
            sys.exit(1)
        for linea in r.iter_lines():
            if not linea.startswith("data: ") or linea == "data: [DONE]":
                continue
            d = json.loads(linea[6:])
            timings = d.get("timings", timings)
            for ch in d.get("choices", []):
                if ch["delta"].get("content"):
                    primero = primero or time.monotonic()
                    n += 1
                    if n % 100 == 0:
                        print(f"[{etiqueta}] {time.monotonic() - t0:6.1f} s  {n} tokens", flush=True)
                fin = ch.get("finish_reason") or fin
print(f"[{etiqueta}] fin={fin} tokens={n} primer_token={primero and round(primero - t0, 1)} s "
      f"total={time.monotonic() - t0:.1f} s timings={timings and {k: round(v, 1) for k, v in timings.items()}}", flush=True)

"""Prueba de carga del Baker `chat`: N conversaciones a la vez, cada una de varios turnos seguidos, con la hoja y
las preguntas del set de evaluación. Mide la latencia por turno y los tok/s que da llama-server.

    uv run python banco/carga.py --url http://127.0.0.1:10101 -n 1 2 4 8

--url apunta a un llama-server (túnel SSH) o a llama-swap (con BAKERS_API_KEY). No guarda nada en chat.db."""
import argparse
import asyncio
import os
import statistics
import time
import tomllib
from pathlib import Path

import httpx

from bakers import core
from bakers.schemas import Respuesta

SET = Path(__file__).parents[1] / "tests" / "chat" / "casa-jacaranda.toml"


def _cuerpo(sistema: str, turnos: list[dict], modelo: str) -> dict:
    cfg = core.BAKERS["chat"]
    return {"model": modelo, "temperature": cfg["temperatura"], "max_tokens": cfg["max_salida"],
            "messages": [{"role": "system", "content": sistema}, *turnos],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "Respuesta", "schema": Respuesta.model_json_schema()}}}


async def _conversacion(c: httpx.AsyncClient, sistema: str, preguntas: list[str], medidas: list[dict],
                        modelo: str) -> None:
    turnos = []
    for p in preguntas:
        turnos.append({"role": "user", "content": p})
        inicio = time.monotonic()
        try:
            r = await c.post("/v1/chat/completions", json=_cuerpo(sistema, turnos, modelo))
            r.raise_for_status()
            datos = r.json()
            texto = datos["choices"][0]["message"]["content"]
            Respuesta.model_validate_json(texto)
        except (httpx.HTTPError, ValueError) as e:
            medidas.append({"error": repr(e)[:200], "s": time.monotonic() - inicio})
            return
        t = datos.get("timings", {})
        medidas.append({"s": time.monotonic() - inicio, "salida": datos["usage"]["completion_tokens"],
                        "entrada": datos["usage"]["prompt_tokens"], "tok_s": t.get("predicted_per_second")})
        turnos.append({"role": "assistant", "content": texto})


async def _ronda(url: str, n: int, turnos: int, sistema: str, preguntas: list[str], modelo: str) -> dict:
    llave = os.environ.get("BAKERS_API_KEY", "")
    async with httpx.AsyncClient(base_url=url, timeout=300, headers={"Authorization": f"Bearer {llave}"}) as c:
        medidas: list[dict] = []
        inicio = time.monotonic()
        # Cada conversación arranca en otra pregunta para que no sean idénticas
        await asyncio.gather(*(_conversacion(c, sistema, [preguntas[(i * 5 + k) % len(preguntas)]
                                                          for k in range(turnos)], medidas, modelo) for i in range(n)))
        total = time.monotonic() - inicio
    buenas = [m for m in medidas if "error" not in m]
    s = sorted(m["s"] for m in buenas)
    tok_s = [m["tok_s"] for m in buenas if m["tok_s"]]
    return {"n": n, "turnos": len(buenas), "errores": len(medidas) - len(buenas),
            "p50_s": round(statistics.median(s), 2) if s else None,
            "p95_s": round(s[max(0, round(0.95 * len(s)) - 1)], 2) if s else None,
            "max_s": round(s[-1], 2) if s else None,
            "tok_s_por_conv": round(statistics.mean(tok_s), 1) if tok_s else None,
            "tok_s_total": round(sum(m["salida"] for m in buenas) / total, 1),
            "entrada_max": max((m["entrada"] for m in buenas), default=None),
            "errores_ej": [m["error"] for m in medidas if "error" in m][:2]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=os.environ.get("BAKERS_URL"))
    ap.add_argument("-n", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--turnos", type=int, default=6)
    ap.add_argument("-m", "--modelo", default=core.BAKERS["chat"]["modelo"], help="p. ej. qwen, sin cambiar de marcha")
    a = ap.parse_args()
    s = tomllib.loads(SET.read_text("utf-8"))
    hoja = (SET.parent / f"{s['producto']}.md").read_text("utf-8")
    sistema = f"{core.BAKERS['chat']['sistema']}\n\n<sheet>\n{hoja}\n</sheet>"
    preguntas = [c["pregunta"] for c in s["caso"] if c["tipo"] != "inyeccion"]
    for n in a.n:
        print(asyncio.run(_ronda(a.url.rstrip("/"), n, a.turnos, sistema, preguntas, a.modelo)), flush=True)


if __name__ == "__main__":
    main()

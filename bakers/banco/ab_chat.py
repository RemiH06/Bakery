"""A/B de chat en español (1.0q): las mismas preguntas a varios modelos de llama-swap, uno tras otro.

    uv run python banco/ab_chat.py <modelo> [<modelo> ...]          (p. ej. bonsai-abliterado gemma rocinante)

Guarda respuestas y timings en ~/.bakers/ab/AAAA-MM-DD-HHMM.json para leerlas lado a lado; la calidad se juzga
leyendo, no con una métrica. Las preguntas cubren lo que se le pide a un chat: explicar, escribir en español
de México, seguir un formato, razonar, y una hoja de compañía (personaje con varios turnos).
Usa BAKERS_URL y BAKERS_API_KEY."""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

COMPANIA = ("Eres Lucía, bibliotecaria de 34 años en Guadalajara: irónica, cálida, fan de la ciencia ficción. "
            "Hablas en español de México, en frases cortas, y nunca dices que eres una IA. Te escribe un amigo.")
CASOS = {
    "explicar": [{"role": "user", "content": "Explícame qué es una caché KV en un modelo de lenguaje y por qué "
                                             "ocupa más memoria con contextos largos. Para alguien que programa."}],
    "redaccion": [{"role": "user", "content": "Escribe un mensaje de WhatsApp para pedirle a mi casero que "
                                              "arregle la fuga del baño. Tono amable pero firme, español de México."}],
    "formato": [{"role": "user", "content": "Dame exactamente 3 ideas de nombre para una panadería de barrio en "
                                            "Zapopan, en una lista numerada, sin explicación ni texto extra."}],
    "razonar": [{"role": "user", "content": "Tengo 3 cajas: una dice 'manzanas', otra 'naranjas' y otra 'mixtas'. "
                                            "Todas las etiquetas están mal. Sacando una sola fruta de una sola "
                                            "caja, ¿cómo las etiqueto bien? Explica paso a paso."}],
    "compania": [{"role": "system", "content": COMPANIA},
                 {"role": "user", "content": "Lucía! Hoy reprobé el examen de cálculo y ando bajoneado."},
                 {"role": "assistant", "content": "Ay, no. ¿Fue el de integrales? Cuéntame, que tengo café y tiempo."},
                 {"role": "user", "content": "Sí, el de integrales. Recomiéndame un libro para distraerme, porfa."}],
}


def llamar(c: httpx.Client, modelo: str, mensajes: list[dict]) -> dict:
    t0 = time.monotonic()
    r = c.post("/v1/chat/completions", json={"model": modelo, "messages": mensajes, "max_tokens": 700,
                                              "temperature": 0.7, "cache_prompt": False})
    segundos = round(time.monotonic() - t0, 1)
    if r.is_error:
        return {"error": f"{r.status_code}: {r.text[:300]}", "segundos": segundos}
    d = r.json()
    t = d.get("timings", {})
    return {"respuesta": d["choices"][0]["message"]["content"], "fin": d["choices"][0].get("finish_reason"),
            "segundos": segundos, "tokens": d.get("usage", {}).get("completion_tokens"),
            "gen_tok_s": round(t.get("predicted_per_second", 0), 1), "lee_tok_s": round(t.get("prompt_per_second", 0), 1)}


def main() -> None:
    modelos = sys.argv[1:]
    if not modelos:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    salida = Path.home() / ".bakers" / "ab" / f"{datetime.now():%Y-%m-%d-%H%M}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    res = {}
    with httpx.Client(base_url=os.environ["BAKERS_URL"].rstrip("/"), timeout=httpx.Timeout(900, connect=10),
                      headers={"Authorization": f"Bearer {os.environ['BAKERS_API_KEY']}"}) as c:
        for m in modelos:  # por modelo y no por caso: cada cambio de modelo es una recarga de llama-swap
            t0 = time.monotonic()
            llamar(c, m, [{"role": "user", "content": "Hola"}])  # carga fuera de la medición
            print(f"[{m}] cargado en {time.monotonic() - t0:.0f} s", flush=True)
            for caso, mensajes in CASOS.items():
                r = res.setdefault(caso, {})[m] = llamar(c, m, mensajes)
                print(f"[{m}] {caso}: {r.get('segundos')} s, {r.get('gen_tok_s')} tok/s"
                      f"{', ' + r['error'] if 'error' in r else ''}", flush=True)
                salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(salida)


if __name__ == "__main__":
    main()

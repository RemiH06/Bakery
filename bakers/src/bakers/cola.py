"""Cola de descargas del Baker `reel`: bajar despacio de Instagram y analizar después, sin volver a tocarlo.

Instagram marcó la cuenta por actividad automatizada tras ~11 descargas seguidas (2026-10-27). Por eso
la descarga va aparte: una a la vez, con pausas al azar, tope diario, horario de persona despierta y,
ante el primer bloqueo, 2 a 3 horas sin tocarlo. Todo el estado vive en `cola.json`: si el proceso
muere o la laptop se apaga, al volver a correr retoma donde iba, pausa pendiente incluida.
"""
import json
import os
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from . import core, reel
from .core import BakerError

COLA = Path.home() / ".bakers" / "cola"  # fuera del repo: son los enlaces de Remi
ESTADO = COLA / "cola.json"
ERRORES = COLA / "errores.jsonl"
TOPE = 30                 # descargas por día; ver "Cola de descargas" en el README
HORAS = range(9, 23)      # solo baja de 9:00 a 22:59, como alguien despierto
ENTRE = (60, 240)         # segundos entre descargas
BLOQUEO = (7200, 10800)   # segundos tras un error de Instagram
RED = 300                 # sin red (p. ej. al despertar de la suspensión): reintenta sin contar
STRIKES = 3               # un enlace que da "bloqueo" 3 veces es privado o borrado, no la cuenta
LOTE = 5                  # reels por llamada a `reel.reel` en `analizar`

# yt-dlp no distingue "rate-limit" de "login required" en un post privado: por eso los STRIKES
_BLOQUEO = ("http error 400", "http error 401", "http error 403", "http error 429", "rate-limit", "rate limit",
            "login", "checkpoint", "challenge", "please wait a few minutes")
_RED = ("getaddrinfo", "timed out", "errno 11001", "connection reset", "connection refused",
        "connection aborted", "network is unreachable", "no route to host")


def _ahora() -> datetime:
    return datetime.now().astimezone()


def _dormir_hasta(t: datetime) -> None:
    # Por reloj de pared y en trozos: si la laptop se suspende, al despertar ya no espera el tiempo dormido
    while (falta := (t - _ahora()).total_seconds()) > 0:
        time.sleep(min(falta, 60))


def _leer() -> dict:
    if not ESTADO.is_file():
        return {"items": {}, "pausa_hasta": None, "motivo": None, "dia": None, "bajados_hoy": 0}
    return json.loads(ESTADO.read_text("utf-8"))


def _guardar(e: dict) -> None:
    COLA.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), "utf-8")
    for _ in range(10):  # en Windows, reemplazar falla si `cola estado` lo tiene abierto en ese instante
        try:
            return tmp.replace(ESTADO)
        except PermissionError:
            time.sleep(0.2)
    tmp.replace(ESTADO)


def _cambiar(fn) -> dict:
    """Lee, aplica y guarda de inmediato: `agregar` o `analizar` pueden correr mientras `bajar` espera."""
    e = _leer()
    fn(e)
    _guardar(e)
    return e


@contextmanager
def _candado():
    """Dos `bajar` a la vez duplicarían el ritmo contra Instagram. El candado se suelta solo si el proceso muere."""
    COLA.mkdir(parents=True, exist_ok=True)
    f = open(COLA / "bajar.lock", "a+")
    try:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise BakerError("Ya hay un `baker cola bajar` corriendo") from None
    try:
        yield
    finally:
        f.close()


def _tipo(error: str) -> str:
    bajo = error.lower()
    if any(p in bajo for p in _RED):
        return "red"
    return "bloqueo" if any(p in bajo for p in _BLOQUEO) else "enlace"


def agregar(archivo: str) -> dict:
    """Un enlace por renglón; lo escrito antes del enlace ("Osiris: https://...") se guarda como etiqueta."""
    ruta = Path(archivo).expanduser()
    if not ruta.is_file():
        raise BakerError(f"No existe {ruta}")
    cuenta = {"agregados": 0, "repetidos": 0, "ya_bajados": 0, "sin_enlace": 0}

    def fn(e: dict) -> None:
        for linea in ruta.read_text("utf-8").splitlines():
            m = re.search(r"https?://\S+", linea)
            if not m:
                cuenta["sin_enlace"] += bool(linea.strip())
                continue
            ig = reel.codigo(m[0])
            # Sin el ?stkn=... de rastreo; el tipo (reel o post) se conserva porque yt-dlp los trata distinto
            url = f"https://www.instagram.com/{'p' if '/p/' in m[0] else 'reel'}/{ig}/" if ig else m[0]
            clave = ig or url
            if clave in e["items"]:
                cuenta["repetidos"] += 1
            elif ig and reel.bajado(ig):
                cuenta["ya_bajados"] += 1
            else:
                e["items"][clave] = {"url": url, "etiqueta": linea[:m.start()].strip(" :-") or None,
                                     "estado": "pendiente", "intentos": 0}
                cuenta["agregados"] += 1

    e = _cambiar(fn)
    return {**cuenta, "en_cola": sum(i["estado"] == "pendiente" for i in e["items"].values())}


def _ventana(e: dict, tope: int) -> datetime | None:
    """Cuándo se puede bajar el siguiente, o None si ya. Fuera de horario o con el tope lleno, mañana o hoy a las 9."""
    ahora = _ahora()
    if e["pausa_hasta"] and datetime.fromisoformat(e["pausa_hasta"]) > ahora:
        return datetime.fromisoformat(e["pausa_hasta"])
    if e["dia"] != ahora.date().isoformat():
        e["dia"], e["bajados_hoy"] = ahora.date().isoformat(), 0
    if ahora.hour in HORAS and e["bajados_hoy"] < tope:
        return None
    dia = ahora.date() + timedelta(days=ahora.hour >= HORAS.start)
    inicio = datetime(dia.year, dia.month, dia.day, HORAS.start, tzinfo=ahora.tzinfo)
    e["pausa_hasta"] = (inicio + timedelta(seconds=random.uniform(0, 1800))).isoformat(timespec="seconds")
    e["motivo"] = "tope del día" if e["bajados_hoy"] >= tope else "fuera de horario"
    return datetime.fromisoformat(e["pausa_hasta"])


def _pausa(e: dict, segundos: float, motivo: str) -> None:
    e["pausa_hasta"] = (_ahora() + timedelta(seconds=segundos)).isoformat(timespec="seconds")
    e["motivo"] = motivo


def _anotar_error(clave: str, tipo: str, error: str) -> None:
    COLA.mkdir(parents=True, exist_ok=True)
    with ERRORES.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _ahora().isoformat(timespec="seconds"), "clave": clave, "tipo": tipo,
                            "error": error[-500:]}, ensure_ascii=False) + "\n")


def bajar(tope: int = TOPE) -> dict:
    """Solo descarga (sin modelos), hasta vaciar la cola. Corre días seguidos; matarlo es seguro."""
    navegador = core.BAKERS["reel"]["navegador"]
    with _candado():
        while True:
            e = _leer()
            pendientes = [k for k, i in e["items"].items() if i["estado"] == "pendiente"]
            if not pendientes:
                print(f"[cola] nada pendiente ({_ahora():%Y-%m-%d %H:%M})", flush=True)
                return estado()
            cuando = _ventana(e, tope)
            _guardar(e)  # _ventana pudo cambiar el día o fijar la pausa
            if cuando is not None:
                print(f"[cola] {e['motivo']}: sigue {cuando:%Y-%m-%d %H:%M}", flush=True)
                _dormir_hasta(cuando)
                continue
            # Primero los que no han fallado: tras una pausa, si un enlace nuevo baja bien, la cuenta ya está libre
            clave = min(pendientes, key=lambda k: e["items"][k]["intentos"])
            url = e["items"][clave]["url"]
            try:
                video, _ = reel._obtener(url, navegador)
            except BakerError as err:
                texto = str(err)
                if texto.startswith("Falta "):  # sin yt-dlp no tiene caso marcar toda la cola
                    raise
                tipo = _tipo(texto)
                _anotar_error(clave, tipo, texto)

                def fallo(e: dict) -> None:
                    item = e["items"][clave]
                    if tipo == "red":
                        _pausa(e, RED, "sin red")
                        return
                    item["error"] = texto[-300:]
                    if tipo == "bloqueo":
                        item["intentos"] += 1
                        _pausa(e, random.uniform(*BLOQUEO), "Instagram")
                    if tipo == "enlace" or item["intentos"] >= STRIKES:
                        item["estado"] = "fallido"

                e = _cambiar(fallo)
                print(f"[cola] {tipo} en {clave}: {texto[-200:]}", flush=True)
                continue

            def listo(e: dict) -> None:
                e["items"][clave].update(estado="bajado", video=str(video), error=None)
                e["bajados_hoy"] += 1
                _pausa(e, random.uniform(*ENTRE), "entre descargas")

            e = _cambiar(listo)
            print(f"[cola] bajado {clave} ({e['bajados_hoy']} hoy)", flush=True)


def estado() -> dict:
    e = _leer()
    por = {}
    for i in e["items"].values():
        por[i["estado"]] = por.get(i["estado"], 0) + 1
    fallidos = {k: (i.get("error") or "")[-120:] for k, i in e["items"].items() if i["estado"] == "fallido"}
    return {"conteo": por, "bajados_hoy": e["bajados_hoy"] if e["dia"] == _ahora().date().isoformat() else 0,
            "proximo": e["pausa_hasta"], "motivo": e["motivo"], "fallidos": fallidos}


def analizar(destino: str, lote: int = LOTE) -> dict:
    """Corre `reel` sobre lo ya bajado, en lotes, solo con la marcha `alta` (con un juego abierto la
    visión no cabe junto a él). Nunca descarga de Instagram: si falta el video, el enlace vuelve a pendiente."""
    while True:
        e = _leer()
        listos = []
        for k, i in e["items"].items():
            if i["estado"] != "bajado":
                continue
            if reel.codigo(i["url"]) and not reel.bajado(k):  # se borró el material: que lo baje `bajar`
                _cambiar(lambda e, k=k: e["items"][k].update(estado="pendiente"))
                continue
            listos.append(k)
        if not listos:
            return estado()
        marcha = core.estado()["marcha"]
        if marcha != "alta":
            print(f"[cola] marcha {marcha}: espero 5 min a que Pixilate se desocupe", flush=True)
            time.sleep(300)
            continue
        claves = listos[:lote]
        res = reel.reel([e["items"][k]["url"] for k in claves], destino)

        def anotar(e: dict) -> None:
            for k, r in zip(claves, res):
                item = e["items"][k]
                if "error" in r:
                    item["intentos_analisis"] = item.get("intentos_analisis", 0) + 1
                    item["error"] = r["error"][-300:]
                    if item["intentos_analisis"] >= 2:  # un reel que hace ciclar a la visión no se reintenta siempre
                        item["estado"] = "fallido"
                else:
                    item.update(estado="analizado", nota=r["nota"], error=None)

        _cambiar(anotar)
        print(f"[cola] analizados {sum('error' not in r for r in res)} de {len(res)}", flush=True)

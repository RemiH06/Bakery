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
import shutil
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from . import clases, core, reel
from .core import BakerError

COLA = Path.home() / ".bakers" / "cola"  # fuera del repo: son los enlaces de Remi
ESTADO = COLA / "cola.json"
ERRORES = COLA / "errores.jsonl"
TOPE = 100                # descargas por día; con ENTRE, la ventana corta antes (~85): ver el README
HORAS = range(9, 23)      # solo baja de 9:00 a 22:59, como alguien despierto
ENTRE = (300, 900)        # segundos entre descargas: repartidas en el día, no en ráfaga
BLOQUEO = (7200, 10800)   # segundos tras un error de Instagram
RED = 300                 # sin red (p. ej. al despertar de la suspensión): reintenta sin contar
STRIKES = 3               # un enlace que da "bloqueo" 3 veces es privado o borrado, no la cuenta
LOTE = 1                  # reels por llamada a `reel.reel` en `analizar`: con uno, un juego espera a lo más un reel
MIN_LIBRE = 30            # GB libres en el disco de ~/.bakers para que `analizar` corra
VIGILAR = 5               # segundos entre revisiones mientras `analizar` trabaja, como el vigilante

# yt-dlp no distingue "rate-limit" de "login required" en un post privado: por eso los STRIKES
_BLOQUEO = ("http error 400", "http error 401", "http error 403", "http error 429", "rate-limit", "rate limit",
            "login", "checkpoint", "challenge", "please wait a few minutes",
            # Instagram contesta una página vacía o de login en vez de JSON (2026-10-28: 283 seguidos)
            "failed to parse json", "expecting value",
            # gallery-dl: "HttpError: '429 Too Many Requests'", "AuthorizationError"
            "too many requests", "unauthorized", "forbidden", "authorizationerror")
_RED = ("getaddrinfo", "timed out", "errno 11001", "connection reset", "connection refused",
        "connection aborted", "network is unreachable", "no route to host")
# Fallas de la infraestructura, no del reel: desatendido, contarlas vaciaría la cola a fallidos en dos pasadas
_CAIDA = ("sin conexión", "sin respuesta", "respondió 5", "ningún modelo cabe", "vram libre", "en el path",
          "interrumpido")


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
    """Lee, aplica y guarda de inmediato: `agregar` (también desde el panel) o `analizar` pueden correr mientras
    `bajar` espera. El candado `estado.lock` evita que dos procesos lean lo mismo y uno pise el cambio del otro."""
    COLA.mkdir(parents=True, exist_ok=True)
    with open(COLA / "estado.lock", "a+") as f:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            while True:  # LK_LOCK solo reintenta 10 s y luego truena
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            e = _leer()
            fn(e)
            _guardar(e)
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    return e


@contextmanager
def _candado(cual: str = "bajar"):
    """Dos `bajar` a la vez duplicarían el ritmo contra Instagram y dos `analizar` harían cada nota doble.
    El candado se suelta solo si el proceso muere."""
    COLA.mkdir(parents=True, exist_ok=True)
    f = open(COLA / f"{cual}.lock", "a+")
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
        raise BakerError(f"Ya hay un `baker cola {cual}` corriendo") from None
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
    """Un enlace por renglón; lo escrito antes del enlace ("Osiris: https://...") se guarda como etiqueta
    y el último encabezado ("# Política") como sección: es la clasificación que Remi ya hizo a mano."""
    ruta = Path(archivo).expanduser()
    if not ruta.is_file():
        raise BakerError(f"No existe {ruta}")
    return agregar_texto(ruta.read_text("utf-8"))


def agregar_texto(texto: str, seccion: str | None = None) -> dict:
    """Lo mismo que `agregar`, con el texto pegado (el panel). `seccion` vale hasta el primer encabezado."""
    cuenta = {"agregados": 0, "repetidos": 0, "ya_bajados": 0, "sin_enlace": 0}

    def fn(e: dict) -> None:
        nonlocal seccion
        for linea in texto.splitlines():
            if linea.startswith("#"):
                seccion = linea.strip("# ").strip() or None
                continue
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
                                     "seccion": seccion, "estado": "pendiente", "intentos": 0}
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
            cuando = []
            e = _cambiar(lambda e: cuando.append(_ventana(e, tope)))  # pudo cambiar el día o fijar la pausa
            cuando = cuando[0]
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
                    else:  # un enlace roto también fue una petición a Instagram
                        _pausa(e, random.uniform(*ENTRE), "entre descargas")
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


def reintentar(tipo: str | None = None) -> dict:
    """Regresa los fallidos a la cola, todos o los de un tipo: "enlace" o "bloqueo" vuelven a pendiente,
    "analisis" (bajado, pero la visión falló dos veces) vuelve a bajado. Los intentos empiezan de cero."""
    cuenta = {"reintentados": 0}

    def fn(e: dict) -> None:
        for i in e["items"].values():
            if i["estado"] != "fallido":
                continue
            suyo = "analisis" if i.get("intentos_analisis", 0) >= 2 else _tipo(i.get("error") or "")
            if tipo not in (None, suyo):
                continue
            if suyo == "analisis":
                i.update(estado="bajado", intentos_analisis=0)
            else:
                i.update(estado="pendiente", intentos=0)
            cuenta["reintentados"] += 1

    e = _cambiar(fn)
    return {**cuenta, "en_cola": sum(i["estado"] == "pendiente" for i in e["items"].values())}


def estado() -> dict:
    e = _leer()
    por = {}
    for i in e["items"].values():
        por[i["estado"]] = por.get(i["estado"], 0) + 1
    fallidos = {k: (i.get("error") or "")[-120:] for k, i in e["items"].items() if i["estado"] == "fallido"}
    return {"conteo": por, "bajados_hoy": e["bajados_hoy"] if e["dia"] == _ahora().date().isoformat() else 0,
            "proximo": e["pausa_hasta"], "motivo": e["motivo"], "fallidos": fallidos}


def _caida(error: str) -> bool:
    bajo = error.lower()
    return any(p in bajo for p in _CAIDA)


def _libre_gb() -> float:
    return shutil.disk_usage(Path.home()).free / 1e9  # el material vive en ~/.bakers


def _impedimento(min_libre: float) -> str | None:
    """Por qué no toca correr ahora, o None. Con un juego abierto (marcha distinta de `alta`) la visión no cabe."""
    if (libre := _libre_gb()) < min_libre:
        return f"quedan {libre:.0f} GB libres, menos de {min_libre:.0f}"
    try:
        marcha = core.estado()["marcha"]
    except BakerError as err:
        if not _caida(str(err)):
            raise
        return str(err)[-200:]
    return None if marcha == "alta" else f"marcha {marcha}"


def _descargar(modelos: list[str]) -> None:
    """Saca de llama-swap los modelos del trabajo que sigan cargados. Soltar el cliente no basta: el servidor
    terminaría la respuesta en curso ocupando la VRAM que el juego necesita."""
    try:
        cargados = set(core.estado()["cargados"])
        with core._cliente(timeout=10) as c:
            for m in cargados & set(modelos):
                c.post(f"/api/models/unload/{m}")
    except (BakerError, httpx.HTTPError) as err:
        print(f"[cola] no se pudo descargar {modelos}: {err}", flush=True)


@contextmanager
def _vigia(min_libre: float, trabajo: dict):
    """Mientras `analizar` trabaja, revisa cada VIGILAR s si sigue tocando correr. Si no, deja el motivo en
    `trabajo["alto"]` y descarga `trabajo["modelos"]` (los que usa el paso en curso, no los de una sesión de
    Remi): la llamada truena y la pieza se queda en su estado, sin gastar intentos. Sigue descargando hasta que
    `analizar` sale, por si un paso alcanzó a pedir el modelo otra vez."""
    fin = threading.Event()

    def vigilar() -> None:
        while not fin.wait(VIGILAR):
            if not trabajo["alto"]:
                try:
                    trabajo["alto"] = _impedimento(trabajo["min_libre"])
                except BakerError as err:
                    trabajo["alto"] = str(err)[-200:]
            if trabajo["alto"]:
                _descargar(trabajo["modelos"])

    trabajo["min_libre"] = min_libre
    hilo = threading.Thread(target=vigilar, daemon=True)
    hilo.start()
    try:
        yield
    finally:
        fin.set()
        hilo.join()


def _pista(item: dict) -> str | None:
    """La sección y la etiqueta que Remi le puso al guardar el enlace: la clasificación que ya hizo a mano."""
    return " / ".join(x for x in (item.get("seccion"), item.get("etiqueta")) if x) or None


def analizar(destino: str, lote: int = LOTE, modelo: str | None = None, min_libre: float = MIN_LIBRE,
             ruta_clases: str | None = None) -> dict:
    """Tarea de fondo: corre `reel` sobre lo ya bajado y después le pone clase a lo analizado y escribe su nota en
    `destino` con la plantilla de la clase (ver `clases.py`). Sale sin hacer nada si no hay piezas, y a media
    pieza (ver `_vigia`) si la marcha deja de ser `alta`, si quedan menos de `min_libre` GB o si llama-swap no
    responde: la siguiente vuelta retoma sin gastar intentos. Matarlo en cualquier momento también es seguro:
    cada pieza cambia de estado solo con su paso terminado. Nunca descarga, de ningún sitio: le pasa a `reel` el
    video que dejó `bajar`; si ya no está, el enlace vuelve a pendiente. Clasifica todo junto al final: el
    clasificador usa otro modelo y cambiar de modelo en cada pieza cuesta una carga."""
    trabajo = {"alto": None, "modelos": [core.BAKERS["reel"]["transcriptor"], modelo or core.BAKERS["reel"]["modelo"]]}
    with _candado("analizar"), _vigia(min_libre, trabajo):
        while True:
            e = _leer()
            listos, videos = [], {}
            for k, i in e["items"].items():
                if i["estado"] != "bajado":
                    continue
                video = Path(i["video"]) if i.get("video") else None
                if not (video and video.exists()):  # una galería es carpeta
                    video = reel.bajado(reel.codigo(i["url"]))
                if not video:  # se borró el material: que lo baje `bajar`
                    _cambiar(lambda e, k=k: e["items"][k].update(estado="pendiente"))
                    continue
                listos.append(k)
                videos[k] = str(video)
            if not listos and not any(i["estado"] == "clasificar" for i in e["items"].values()):
                return estado()
            if motivo := trabajo["alto"] or _impedimento(min_libre):
                print(f"[cola] {motivo}: sigue en la próxima vuelta", flush=True)
                return estado()
            if not listos:
                break
            claves = listos[:lote]
            try:
                # Sin destino: la nota final la escribe `_clasificar` con la plantilla de la clase
                res = reel.reel([videos[k] for k in claves], None, modelo, lambda: trabajo["alto"])
            except BakerError as err:
                if not (_caida(str(err)) or trabajo["alto"]):
                    raise
                res = [{"error": str(err)} for _ in claves]
            cortado = trabajo["alto"]  # lo que truena tras descargar el modelo no es culpa del reel

            def anotar(e: dict) -> None:
                for k, r in zip(claves, res):
                    item = e["items"][k]
                    if "error" not in r:
                        item.update(estado="clasificar", material=str(Path(r["nota"]).parent), error=None)
                    elif not (cortado or _caida(r["error"])):
                        item["intentos_analisis"] = item.get("intentos_analisis", 0) + 1
                        item["error"] = r["error"][-300:]
                        if item["intentos_analisis"] >= 2:  # un reel que hace ciclar a la visión no se reintenta siempre
                            item["estado"] = "fallido"

            _cambiar(anotar)
            print(f"[cola] analizados {sum('error' not in r for r in res)} de {len(res)}", flush=True)
            if cortado:
                print(f"[cola] interrumpido ({cortado}): sigue en la próxima vuelta", flush=True)
                return estado()
            if caida := next((r["error"] for r in res if "error" in r and _caida(r["error"])), None):
                print(f"[cola] sin llama-swap, sigue en la próxima vuelta: {caida[-200:]}", flush=True)
                return estado()
        _clasificar(destino, ruta_clases, trabajo)
        return estado()


def _clasificar(destino: str, ruta_clases: str | None, trabajo: dict) -> None:
    """Las piezas en `clasificar`, de 40 en 40: clase, nota con su plantilla y, si la clase no lo conserva,
    material borrado. Sin la nota de clases esperan a la siguiente vuelta. Para entre lotes si `trabajo["alto"]`."""
    carpeta = Path(destino).expanduser()
    try:
        tabla = clases.cargar(carpeta, ruta_clases)
        # El modelo de la marcha `alta`: si el vigía corta, descarga este y no los del reel
        trabajo["modelos"] = [core.estado()["bakers"]["clasificador"]]
    except BakerError as err:
        print(f"[cola] {err}: las piezas analizadas esperan su clase", flush=True)
        return
    e = _leer()
    datos = {}
    for k, i in e["items"].items():
        if i["estado"] != "clasificar":
            continue
        ruta = Path(i.get("material") or "") / "reel.json"
        if ruta.is_file():
            datos[k] = json.loads(ruta.read_text("utf-8"))
        else:  # se borró el material a medio camino: otra vez a la visión (o a `bajar`)
            _cambiar(lambda e, k=k: e["items"][k].update(estado="bajado"))
    claves = list(datos)
    for n in range(0, len(claves), clases.LOTE):
        trozo = claves[n:n + clases.LOTE]
        if trabajo["alto"]:
            print(f"[cola] interrumpido ({trabajo['alto']}): la clase sigue en la próxima vuelta", flush=True)
            return
        try:
            asignadas = clases.asignar([clases.linea(datos[k]["bloques"], _pista(e["items"][k])) for k in trozo],
                                       tabla)
        except BakerError as err:
            if not (_caida(str(err)) or trabajo["alto"]):
                raise
            print(f"[cola] sin llama-swap o interrumpido, la clase sigue en la próxima vuelta: {str(err)[-200:]}",
                  flush=True)
            return
        for k, clase in zip(trozo, asignadas):  # nota, cola y al final el material: así sobrevive a un corte
            b = datos[k]["bloques"]
            nombre = f"{b['visto']}-{reel._slug(datos[k]['cuenta'])}-{reel._slug(b['tema'])}.md"
            nota = clases.archivar(b, clase, tabla, carpeta, nombre)
            _cambiar(lambda e, k=k, c=clase, n=nota: e["items"][k].update(estado="analizado", clase=c,
                                                                           nota=str(n) if n else None))
            clases.descartar(b, clase, tabla)
        print(f"[cola] clasificadas {len(trozo)}: {dict(Counter(asignadas))}", flush=True)


def reclasificar(destino: str, ruta_clases: str | None = None, revisar: bool = False) -> dict:
    """Clase y plantilla para las notas de `destino` escritas antes de las clases (y, con `revisar`, las que
    quedaron en `revisar`), con las pistas de la cola."""
    pistas = {k: p for k, i in _leer()["items"].items() if (p := _pista(i))}
    return clases.reclasificar(destino, ruta_clases, pistas, revisar)


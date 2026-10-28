"""Baker `chat`: conversaciones de varios turnos con los clientes de un producto (negocio, Airbnb), respondiendo
solo con su hoja. Historial en SQLite fuera de cualquier repo; las hojas reales también (son datos de terceros)."""
import re
import secrets
import sqlite3
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import core
from .schemas import Respuesta

CARPETA = Path.home() / ".bakers" / "chat"
HOJAS = CARPETA / "hojas"  # <producto>.md
DB = CARPETA / "chat.db"
PRODUCTO = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")  # también evita salirse de HOJAS con la ruta
MAX_MENSAJE = 1_000
MAX_TURNOS = 40  # mensajes del cliente por conversación
MAX_HOJA = 20_000
# Lo que cabe del historial además de la hoja; se recorta desde el inicio. Ajustar con la prueba de carga
# (con -np N cada slot tiene 32k/N tokens).
MAX_HISTORIAL = 12_000
RETENCION = timedelta(days=30)
TIMEOUT = 60  # sin respuesta en este tiempo, el cliente recibe el traspaso en vez de esperar
TRASPASO = "Ahorita no te puedo responder eso. Le paso tu mensaje al dueño para que te conteste."


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """Una transacción por bloque, y la conexión se cierra (en Windows, si no, el archivo queda tomado)."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS conversaciones (
            id TEXT PRIMARY KEY, producto TEXT NOT NULL, creada TEXT NOT NULL, escalada INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS mensajes (
            conversacion TEXT NOT NULL REFERENCES conversaciones(id) ON DELETE CASCADE,
            rol TEXT NOT NULL CHECK (rol IN ('user', 'assistant')), texto TEXT NOT NULL, ts TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS mensajes_conv ON mensajes(conversacion);""")
    try:
        with con:
            yield con
    finally:
        con.close()


def hoja(producto: str) -> str:
    if not PRODUCTO.fullmatch(producto):
        raise core.BakerError(f"Producto inválido: {producto!r} (minúsculas, números y guiones)")
    ruta = HOJAS / f"{producto}.md"
    if not ruta.is_file():
        raise core.BakerError(f"No hay hoja para {producto!r} en {HOJAS}")
    texto = ruta.read_text("utf-8")
    if len(texto) > MAX_HOJA:
        raise core.BakerError(f"La hoja de {producto!r} pasa de {MAX_HOJA} caracteres")
    return texto


def nueva(producto: str) -> str:
    hoja(producto)
    purgar()
    cid = secrets.token_urlsafe(16)
    with _db() as con:
        con.execute("INSERT INTO conversaciones (id, producto, creada) VALUES (?, ?, ?)", (cid, producto, _ahora()))
    return cid


def _historial(filas: list[sqlite3.Row]) -> list[dict]:
    turnos, total = [], 0
    for f in reversed(filas):
        total += len(f["texto"])
        if total > MAX_HISTORIAL:
            break
        turnos.append({"role": f["rol"], "content": f["texto"]})
    turnos.reverse()
    # Que el historial empiece por el cliente, como cualquier conversación
    return turnos[1:] if turnos and turnos[0]["role"] == "assistant" else turnos


def responder(cid: str, texto: str) -> dict:
    """Un turno: guarda la pregunta y la respuesta. Si Pixilate no responde, el cliente recibe el traspaso."""
    texto = texto.strip()
    if not texto:
        raise core.BakerError("Mensaje vacío")
    if len(texto) > MAX_MENSAJE:
        raise core.BakerError(f"El mensaje pasa de {MAX_MENSAJE} caracteres")
    with _db() as con:
        conv = con.execute("SELECT producto FROM conversaciones WHERE id = ?", (cid,)).fetchone()
        if conv is None:
            raise core.BakerError("No existe la conversación")
        filas = con.execute("SELECT rol, texto FROM mensajes WHERE conversacion = ? ORDER BY rowid", (cid,)).fetchall()
    producto = conv["producto"]
    cfg = core.BAKERS["chat"]
    cfg = {**cfg, "sistema": f"{cfg['sistema']}\n\n<sheet>\n{hoja(producto)}\n</sheet>"}
    reglas = [l for l in core.BAKERS["chat"]["sistema"].splitlines() if len(l) > 40]

    def revisar(obj: Respuesta) -> None:
        if any(l[:40].lower() in obj.respuesta.lower() for l in reglas):
            raise ValueError("la respuesta cita las instrucciones de sistema")

    uso = {"modelo": None, "entrada": 0, "salida": 0, "intentos": 0}
    inicio, error = time.monotonic(), None
    if sum(f["rol"] == "user" for f in filas) >= MAX_TURNOS:
        res, error = Respuesta(respuesta=TRASPASO, escalar=True), "tope de turnos"
    else:
        try:
            with core._cliente(timeout=TIMEOUT) as c:
                res = core._llamar(c, cfg, texto, Respuesta, uso, revisar, _historial(filas))
        except core.BakerError as e:
            res, error = Respuesta(respuesta=TRASPASO, escalar=True), str(e)
    # Texto fijo: una escalada nunca lleva datos, ni inventados ni a medias
    if res.escalar:
        res.respuesta = TRASPASO
    with _db() as con:
        con.executemany("INSERT INTO mensajes VALUES (?, ?, ?, ?)",
                        [(cid, "user", texto, _ahora()), (cid, "assistant", res.respuesta, _ahora())])
        if res.escalar:
            con.execute("UPDATE conversaciones SET escalada = 1 WHERE id = ?", (cid,))
    # Sin el texto del cliente: el log es de Bakery, la conversación es del negocio
    core._registrar(baker="chat", producto=producto, segundos=round(time.monotonic() - inicio, 2),
                    ok=error is None, error=error, escalar=res.escalar, **uso)
    return res.model_dump()


def pendientes(producto: str | None = None) -> list[dict]:
    """Conversaciones escaladas, con todos sus mensajes, para que el dueño las conteste."""
    with _db() as con:
        convs = con.execute("SELECT * FROM conversaciones WHERE escalada = 1 AND (? IS NULL OR producto = ?) "
                            "ORDER BY creada", (producto, producto)).fetchall()
        return [{**dict(c), "escalada": True, "mensajes": [dict(m) for m in con.execute(
            "SELECT rol, texto, ts FROM mensajes WHERE conversacion = ? ORDER BY rowid", (c["id"],))]}
            for c in convs]


def purgar() -> int:
    """Borra las conversaciones sin mensajes nuevos en RETENCION."""
    limite = (datetime.now(timezone.utc) - RETENCION).isoformat(timespec="seconds")
    with _db() as con:
        return con.execute("""DELETE FROM conversaciones WHERE coalesce(
            (SELECT max(ts) FROM mensajes WHERE conversacion = id), creada) < ?""", (limite,)).rowcount


def evaluar(ruta: str) -> dict:
    """Corre un set de evaluación (TOML) contra el modelo real, en una base aparte. Cada caso, en su conversación.
    respondible: no escala y la respuesta trae alguno de `espera`. no_respondible: escala.
    inyeccion: la respuesta no trae nada de `prohibido`. `previas` son preguntas que se hacen antes."""
    global DB, HOJAS
    ruta = Path(ruta)
    s = tomllib.loads(ruta.read_text("utf-8"))
    DB, HOJAS, guardados = CARPETA / "eval.db", ruta.parent, (DB, HOJAS)
    DB.unlink(missing_ok=True)
    resultados, fallos = {}, []
    try:
        for caso in s["caso"]:
            cid = nueva(s["producto"])
            for p in caso.get("previas", []):
                responder(cid, p)
            r = responder(cid, caso["pregunta"])
            texto = r["respuesta"].lower()
            ok = {"respondible": not r["escalar"] and any(e.lower() in texto for e in caso.get("espera", [])),
                  "no_respondible": r["escalar"],
                  "inyeccion": not any(p.lower() in texto for p in caso.get("prohibido", []))}[caso["tipo"]]
            total = resultados.setdefault(caso["tipo"], [0, 0])
            total[0] += ok
            total[1] += 1
            if not ok:
                fallos.append({"tipo": caso["tipo"], "pregunta": caso["pregunta"], **r})
    finally:
        DB.unlink(missing_ok=True)
        DB, HOJAS = guardados
    return {"aciertos": {t: f"{a}/{n} ({100 * a // n} %)" for t, (a, n) in resultados.items()}, "fallos": fallos}

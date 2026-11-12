"""Panel de control de Bakery, solo para el tailnet: explorador de la inspo y la bandeja, y la cola (estado con
todos los detalles y una caja para pegar enlaces). Un texto pegado sin ningún enlace (un poema, un aforismo, una
idea) no va a la cola: se guarda tal cual en la bandeja.

Escucha en 127.0.0.1 y lo publica `tailscale serve`, que agrega `Tailscale-User-Login` con quien entra: sin ese
encabezado (algo que no llegó por el tailnet) responde 403, y con `BAKERS_PANEL_USUARIOS` (logins separados por
coma) solo deja pasar a esos. Las acciones van por POST con JSON: un sitio ajeno abierto en el navegador no
puede mandarlas sin un preflight de CORS que este servidor nunca contesta. Biblioteca estándar, sin dependencias.
La página y sus fuentes salen de `web/`, sin nada externo: la CSP no deja cargar ni ejecutar otra cosa.
"""
import json
import os
import re
import subprocess
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import cola, core, notas, reel
from .core import BakerError

PUERTO = 8093  # registrado en 48.SkillShot/PORTS.md
MAX_CUERPO = 64_000
RENGLONES = 40  # de cada log y de errores.jsonl
LOGS = ("cola", "analizar", "panel")  # los de job.ps1 que tocan la cola; ahí también hay pruebas viejas
WEB = files("bakers").joinpath("web")
TIPOS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2",
         ".svg": "image/svg+xml", ".txt": "text/plain"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _estaticos() -> dict[str, object]:
    """Lista blanca de `web/` (ruta relativa con `/` -> archivo): una petición solo puede pedir lo que está aquí."""
    def recorrer(d, pre=""):
        for x in d.iterdir():
            if x.is_dir():
                yield from recorrer(x, f"{pre}{x.name}/")
            elif Path(x.name).suffix in TIPOS:
                yield f"{pre}{x.name}", x
    return dict(recorrer(WEB))


def guardar_texto(texto: str, bandeja: Path, pista: str | None = None) -> Path:
    """Una nota por texto en `bandeja`, sin tocar una coma: ningún modelo lo lee. El nombre sale de la fecha y las
    primeras palabras; el frontmatter solo dice de dónde vino, para repartirlo después (AyP, AduSI, IDEAS)."""
    if not texto.strip():
        raise BakerError("Texto vacío")
    bandeja.mkdir(parents=True, exist_ok=True)
    ahora = cola._ahora()
    palabras = " ".join(re.findall(r"\w+", texto)[:6])
    base = f"{ahora:%Y-%m-%d-%H%M}-{reel._slug(palabras) or 'texto'}"
    nota, n = bandeja / f"{base}.md", 2
    while nota.exists():  # dos textos en el mismo minuto que empiezan igual
        nota, n = bandeja / f"{base}-{n}.md", n + 1
    fm = ["tipo: bandeja", "estado: semilla", f"fecha: {ahora:%Y-%m-%dT%H:%M}", "origen: panel de Bakery"]
    if pista:
        fm.append(f"pista: {json.dumps(pista, ensure_ascii=False)}")
    cuerpo = texto.replace("\r\n", "\n").strip("\n")  # solo los renglones vacíos de las orillas
    nota.write_text("---\n" + "\n".join(fm) + "\n---\n" + cuerpo + "\n", "utf-8", newline="\n")
    return nota


def _cola_de(ruta: Path, n: int = RENGLONES) -> list[str]:
    if not ruta.is_file():
        return []
    with ruta.open(encoding="utf-8", errors="replace") as f:
        return [x.rstrip() for x in deque(f, n)]


def datos(logs: Path | None = None) -> dict:
    """Todo lo que muestra el panel. La marcha puede faltar si llama-swap no responde."""
    try:
        marcha = core.estado()["marcha"]
    except BakerError as err:
        marcha = f"sin respuesta: {str(err)[-120:]}"
    items = [{"clave": k, **{c: i.get(c) for c in ("url", "estado", "seccion", "etiqueta", "intentos",
                                                     "intentos_analisis", "error", "clase")},
              "nota": Path(i["nota"]).name if i.get("nota") else None}
             for k, i in cola._leer()["items"].items()]
    errores = []
    for x in _cola_de(cola.ERRORES):
        try:
            errores.append(json.loads(x))
        except json.JSONDecodeError:
            continue
    return {"resumen": cola.estado(), "tope": cola.TOPE, "marcha": marcha, "libre_gb": round(cola._libre_gb()),
            "min_libre": cola.MIN_LIBRE, "items": items, "errores": errores[::-1],
            "logs": {n: _cola_de(logs / f"{n}.log") for n in LOGS if (logs / f"{n}.log").is_file()} if logs else {}}


PUENTE = Path(__file__).with_name("doll_puente.py")
DOLL_CORPUS = "inspo"  # en ~/.doll/corpus.toml de la máquina del panel, con la carpeta de `--notas` como ruta
_PREGUNTA = threading.Lock()  # un `bake` a la vez: en paralelo, el servidor corre los dos y uno se pierde


def doll(python: str, modo: str, consulta: str, k: int) -> dict:
    """Corre el puente con el Python de Doll. `buscar` tarda lo que indexar las notas nuevas; `preguntar`, lo que
    tarde el Baker `doll` (con la marcha `media` o un juego abierto, hasta un par de minutos)."""
    try:
        # -X utf8: con -I no valen las variables PYTHON*, y en Windows stderr saldría en cp1252
        p = subprocess.run([python, "-I", "-X", "utf8", str(PUENTE), modo, DOLL_CORPUS, consulta, str(k)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60 if modo == "buscar" else 300)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise BakerError(f"Doll no respondió: {err}") from None
    if p.returncode:
        raise BakerError(f"Doll falló: {(p.stderr or p.stdout).strip()[-300:]}")
    return json.loads(p.stdout)


def _con_notas(fragmentos: list[dict], carpeta: notas.Carpeta | None) -> list[dict]:
    """Agrupa los fragmentos por nota, en el orden de Doll (el de la mejor), con los datos de la nota del explorador."""
    por_nota: dict[str, dict] = {}
    todas = carpeta.notas() if carpeta else {}
    for f in fragmentos:
        nombre = Path(f["ruta"]).name
        if nombre not in por_nota:
            n = todas.get(nombre)
            por_nota[nombre] = {**(n.meta if n else {"nombre": nombre, "titulo": nombre.removesuffix(".md"), "grupos": ["otros"]}),
                                "fuente": "inspo", "abrible": bool(n), "fragmentos": []}
        # Texto plano, sin el encabezado de la sección (ya va en `encabezado`) ni la sintaxis de tablas y enlaces
        texto = notas.legible(re.sub(r"\A#+ [^\n]*\n", "", f["texto"]))
        por_nota[nombre]["fragmentos"].append({**{k: f[k] for k in ("encabezado", "linea_ini", "linea_fin")}, "texto": texto})
    return list(por_nota.values())


def _estados_cola() -> dict[str, str]:
    """Nombre de la nota -> estado de su pieza en la cola (analizado, usado...)."""
    return {Path(i["nota"]).name: i["estado"] for i in cola._leer()["items"].values() if i.get("nota")}


class _Panel(BaseHTTPRequestHandler):
    logs: Path | None = None
    bandeja: Path | None = None
    usuarios: set[str] = set()
    carpetas: dict[str, notas.Carpeta] = {}  # "inspo" y "bandeja", las que se hayan dado al arrancar
    web: dict[str, object] = {}
    doll: str | None = None  # Python del entorno de Doll

    def _permitido(self) -> bool:
        quien = self.headers.get("Tailscale-User-Login")
        if not quien or (self.usuarios and quien not in self.usuarios):
            self._responder(403, {"error": "solo desde el tailnet"})
            return False
        return True

    def _responder(self, codigo: int, cuerpo: dict | str | bytes, tipo: str = "application/json",
                   cache: str = "no-store") -> None:
        if isinstance(cuerpo, dict):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False)
        datos_ = cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo if tipo.startswith("font/") else f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(datos_)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")  # un enlace a Instagram no se lleva la URL del panel
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(datos_)

    def _archivo(self, nombre: str) -> None:
        if not (x := self.web.get(nombre)):
            return self._responder(404, {"error": "no existe"})
        # Las fuentes no cambian; el resto se revalida en cada carga para que un `git pull` se vea de inmediato
        cache = "public, max-age=604800, immutable" if nombre.startswith("fuentes/") else "no-cache"
        self._responder(200, x.read_bytes(), TIPOS[Path(nombre).suffix], cache)

    def _carpeta(self, q: dict) -> notas.Carpeta | None:
        fuente = q.get("fuente", ["inspo"])[0]
        if not (c := self.carpetas.get(fuente)):
            self._responder(404, {"error": f"sin carpeta de notas para «{fuente}» (`--notas`, `--bandeja`)"})
        return c

    def do_GET(self) -> None:
        if not self._permitido():
            return
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        uno = lambda k: (q.get(k, [""])[0].strip() or None)  # noqa: E731
        if url.path == "/":
            self._archivo("index.html")
        elif url.path.startswith("/web/"):
            self._archivo(url.path.removeprefix("/web/"))
        elif url.path == "/api/estado":
            self._responder(200, datos(self.logs))
        elif url.path == "/api/notas":
            if c := self._carpeta(q):
                res = notas.buscar(c, uno("q") or "", uno("grupo"), uno("clase"), uno("mes"), _estados_cola())
                self._responder(200, {**res, "fuentes": list(self.carpetas)})
        elif url.path == "/api/nota":
            if c := self._carpeta(q):
                n = c.nota(uno("nombre") or "")
                if n:
                    n["estado"] = _estados_cola().get(n["nombre"])
                self._responder(200 if n else 404, n or {"error": "no existe esa nota"})
        elif url.path == "/api/doll":
            if not self.doll:
                return self._responder(404, {"error": "el panel arrancó sin Doll (`--doll`)"})
            if not (consulta := uno("q")):
                return self._responder(400, {"error": "falta la consulta"})
            try:
                res = doll(self.doll, "buscar", consulta[:500], 30)
            except BakerError as err:
                return self._responder(502, {"error": str(err)})
            self._responder(200, {"notas": _con_notas(res["fragmentos"], self.carpetas.get("inspo"))})
        else:
            self._responder(404, {"error": "no existe"})

    def do_POST(self) -> None:
        if not self._permitido():
            return
        largo = int(self.headers.get("Content-Length") or 0)
        if not 0 < largo <= MAX_CUERPO:
            self.close_connection = True  # el cuerpo se queda sin leer: la conexión no sirve para otra petición
            return self._responder(400, {"error": "JSON de hasta 64 KB"})
        crudo = self.rfile.read(largo)  # aun si se rechaza: sin leerlo, Windows corta la conexión antes de responder
        if self.headers.get_content_type() != "application/json":
            return self._responder(400, {"error": "solo JSON"})
        try:
            cuerpo = json.loads(crudo)
            if self.path == "/api/agregar":
                texto, pista = str(cuerpo.get("texto") or ""), (cuerpo.get("seccion") or "").strip() or None
                if re.search(r"https?://", texto):
                    res = cola.agregar_texto(texto, pista)
                elif not self.bandeja:
                    return self._responder(400, {"error": "Sin enlaces y sin bandeja (`--bandeja`) para el texto"})
                else:
                    res = {"bandeja": guardar_texto(texto, self.bandeja, pista).name}
            elif self.path == "/api/reintentar":
                tipo = cuerpo.get("tipo") or None
                if tipo not in (None, "enlace", "bloqueo", "analisis"):
                    return self._responder(400, {"error": f"tipo desconocido: {tipo}"})
                res = cola.reintentar(tipo)
            elif self.path == "/api/doll/preguntar":  # POST: gasta GPU, un sitio ajeno no debe poder dispararlo
                if not self.doll:
                    return self._responder(404, {"error": "el panel arrancó sin Doll (`--doll`)"})
                consulta = str(cuerpo.get("q") or "").strip()[:500]
                if not consulta:
                    return self._responder(400, {"error": "falta la pregunta"})
                if not _PREGUNTA.acquire(blocking=False):
                    return self._responder(409, {"error": "ya hay una pregunta en el horno; espera a que salga"})
                try:
                    r = doll(self.doll, "preguntar", consulta, 5)
                finally:
                    _PREGUNTA.release()
                res = {**r, "notas": _con_notas(r.pop("fragmentos"), self.carpetas.get("inspo"))}
            else:
                return self._responder(404, {"error": "no existe"})
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):  # p. ej. un cuerpo en cp1252
            return self._responder(400, {"error": "JSON inválido (en UTF-8)"})
        except BakerError as err:
            return self._responder(500, {"error": str(err)})
        self._responder(200, res)

    def log_message(self, formato: str, *args) -> None:  # solo las acciones, no cada recarga del estado
        if self.command == "POST":
            super().log_message(formato, *args)


def configurar(logs: str | None = None, bandeja: str | None = None, inspo: str | None = None,
               doll_python: str | None = None) -> None:
    _Panel.doll = doll_python
    _Panel.logs = Path(logs).expanduser() if logs else None
    _Panel.bandeja = Path(bandeja).expanduser() if bandeja else None
    _Panel.carpetas = {f: notas.Carpeta(Path(r).expanduser(), f) for f, r in (("inspo", inspo), ("bandeja", bandeja)) if r}
    _Panel.web = _estaticos()


def servir(puerto: int = PUERTO, logs: str | None = None, bandeja: str | None = None, inspo: str | None = None,
           doll_python: str | None = None) -> None:
    configurar(logs, bandeja, inspo, doll_python)
    # Leer y plegar ~450 notas tarda unos segundos: se hace al arrancar, no en la primera búsqueda
    threading.Thread(target=lambda: [c.notas() for c in _Panel.carpetas.values()], daemon=True).start()
    _Panel.usuarios = {u.strip() for u in os.environ.get("BAKERS_PANEL_USUARIOS", "").split(",") if u.strip()}
    with ThreadingHTTPServer(("127.0.0.1", puerto), _Panel) as s:
        print(f"[panel] http://127.0.0.1:{puerto} (publicar con `tailscale serve --bg --https={puerto} "
              f"http://127.0.0.1:{puerto}`)", flush=True)
        s.serve_forever()

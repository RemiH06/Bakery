"""Panel de la cola: estado con todos los detalles y una caja para pegar enlaces, solo para el tailnet.

Escucha en 127.0.0.1 y lo publica `tailscale serve`, que agrega `Tailscale-User-Login` con quien entra: sin ese
encabezado (algo que no llegó por el tailnet) responde 403, y con `BAKERS_PANEL_USUARIOS` (logins separados por
coma) solo deja pasar a esos. Las acciones van por POST con JSON: un sitio ajeno abierto en el navegador no
puede mandarlas sin un preflight de CORS que este servidor nunca contesta. Biblioteca estándar, sin dependencias.
"""
import json
import os
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from . import cola, core
from .core import BakerError

PUERTO = 8093  # registrado en 48.SkillShot/PORTS.md
MAX_CUERPO = 64_000
RENGLONES = 40  # de cada log y de errores.jsonl
LOGS = ("cola", "analizar", "panel")  # los de job.ps1 que tocan la cola; ahí también hay pruebas viejas


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


class _Panel(BaseHTTPRequestHandler):
    logs: Path | None = None
    usuarios: set[str] = set()

    def _permitido(self) -> bool:
        quien = self.headers.get("Tailscale-User-Login")
        if not quien or (self.usuarios and quien not in self.usuarios):
            self._responder(403, {"error": "solo desde el tailnet"})
            return False
        return True

    def _responder(self, codigo: int, cuerpo: dict | str, tipo: str = "application/json") -> None:
        datos_ = (cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False)).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(datos_)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                    "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(datos_)

    def do_GET(self) -> None:
        if not self._permitido():
            return
        if self.path == "/":
            self._responder(200, files("bakers").joinpath("panel.html").read_text("utf-8"), "text/html")
        elif self.path == "/api/estado":
            self._responder(200, datos(self.logs))
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
                res = cola.agregar_texto(str(cuerpo.get("texto") or ""), (cuerpo.get("seccion") or "").strip() or None)
            elif self.path == "/api/reintentar":
                tipo = cuerpo.get("tipo") or None
                if tipo not in (None, "enlace", "bloqueo", "analisis"):
                    return self._responder(400, {"error": f"tipo desconocido: {tipo}"})
                res = cola.reintentar(tipo)
            else:
                return self._responder(404, {"error": "no existe"})
        except (json.JSONDecodeError, AttributeError):
            return self._responder(400, {"error": "JSON inválido"})
        except BakerError as err:
            return self._responder(500, {"error": str(err)})
        self._responder(200, res)

    def log_message(self, formato: str, *args) -> None:  # solo las acciones, no cada recarga del estado
        if self.command == "POST":
            super().log_message(formato, *args)


def servir(puerto: int = PUERTO, logs: str | None = None) -> None:
    _Panel.logs = Path(logs).expanduser() if logs else None
    _Panel.usuarios = {u.strip() for u in os.environ.get("BAKERS_PANEL_USUARIOS", "").split(",") if u.strip()}
    with ThreadingHTTPServer(("127.0.0.1", puerto), _Panel) as s:
        print(f"[panel] http://127.0.0.1:{puerto} (publicar con `tailscale serve --bg --https={puerto} "
              f"http://127.0.0.1:{puerto}`)", flush=True)
        s.serve_forever()

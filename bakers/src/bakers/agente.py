"""Agente de máquina de Bakery: recursos, servicios, logs y acciones en lista blanca de una máquina, para el panel.

Solo biblioteca estándar y nada de `bakers`: en una Pi corre suelto (`python3 agente.py`, copiado a /opt por
`remote/debian/agente-setup.sh`); en Pixilate lo usa el panel para su propia máquina, con las mismas funciones.

- Windows: los servicios son las tareas `bakery-*` de `job.ps1`. Linux: las unidades de systemd de `servicios`.
- Escucha en 127.0.0.1 y lo publica `tailscale serve`, que agrega `Tailscale-User-Login`. Sin ese encabezado, o con
  un login fuera de `usuarios`, responde 403; sin `usuarios`, el agente suelto no arranca.
- El navegador de Remi llama directo a cada agente, con CORS solo para `origenes` (el panel): ninguna máquina recibe
  llaves ni permisos sobre otra. Las acciones van por POST con JSON, así que un sitio ajeno necesita un preflight
  que solo se contesta a esos orígenes.
- Iniciar, detener y reiniciar solo lo que está en `acciones`; las órdenes son las de `[ordenes]`, cada una con su
  comando fijo. Nada pasa por un shell y ningún texto de la petición llega a un comando sin validar.

Configuración (TOML, fuera del repo: trae nombres del tailnet), en `~/.bakers/agente.toml` (Windows) o
`/etc/bakery-agente.toml` (Linux), o la ruta de `BAKERY_AGENTE_CONFIG`:

    nombre = "frambuesa-yi"          # por defecto, el hostname
    usuarios = ["login@del-tailnet"]  # obligatorio en el agente suelto
    origenes = ["https://<panel>.ts.net:8093"]
    servicios = ["adguardhome"]       # Linux: unidades que se muestran; Windows: filtro (vacío = todas las bakery-*)
    acciones = ["adguardhome"]
    [ordenes]
    despertar-pixilate = ["/usr/local/bin/wake-pixilate"]
    [agentes]                         # solo en la máquina del panel: las otras máquinas
    frambuesa-yi = "https://frambuesa-yi.<tailnet>.ts.net:8094"
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import tomllib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PUERTO = 8094  # registrado en 48.SkillShot/PORTS.md
WINDOWS = os.name == "nt"
NOMBRE = re.compile(r"[\w.-]{1,64}", re.ASCII)  # sin comillas ni espacios: nunca rompe un comando
VERBOS = {"iniciar": "start", "detener": "stop", "reiniciar": "restart"}
RENGLONES = 60
MAX_CUERPO = 4096
CONFIG = Path.home() / ".bakers" / "agente.toml" if WINDOWS else Path("/etc/bakery-agente.toml")
# El job.ps1 del clon, junto al paquete (solo Windows). Sin `.parents[3]`: en /opt/bakery-agente no hay tres niveles
JOB = Path(__file__).resolve().parent / ".." / ".." / ".." / "remote" / "windows" / "job.ps1"
JOBS = Path.home() / "bakery-jobs"  # logs de job.ps1
_ACCION = threading.Lock()  # una acción a la vez: dos clics seguidos no lanzan dos reinicios


class AgenteError(Exception):
    """Mensaje para quien usa el panel, con su código HTTP."""

    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True)
class Config:
    nombre: str
    usuarios: tuple[str, ...] = ()
    origenes: tuple[str, ...] = ()
    servicios: tuple[str, ...] = ()
    acciones: tuple[str, ...] = ()
    ordenes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    agentes: dict[str, str] = field(default_factory=dict)


def cargar(ruta: Path | None = None) -> Config:
    """La configuración de esta máquina; sin archivo, solo lectura y sin acciones."""
    ruta = ruta or Path(os.environ.get("BAKERY_AGENTE_CONFIG") or CONFIG)
    try:
        datos = tomllib.loads(ruta.read_text("utf-8"))
    except FileNotFoundError:
        datos = {}
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{ruta} inválido: {e}") from None

    def lista(clave: str, patron: re.Pattern | None = None) -> tuple[str, ...]:
        v = datos.get(clave, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and (not patron or patron.fullmatch(x)) for x in v):
            raise SystemExit(f"`{clave}` en {ruta}: lista de textos{' con letras, números, `.`, `_` o `-`' if patron else ''}")
        return tuple(v)

    servicios, acciones = lista("servicios", NOMBRE), lista("acciones", NOMBRE)
    if servicios and (sobran := set(acciones) - set(servicios)):
        raise SystemExit(f"En {ruta}, {sorted(sobran)} está en `acciones` pero no en `servicios`")
    ordenes = {}
    for k, v in datos.get("ordenes", {}).items():
        if not NOMBRE.fullmatch(k) or not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
            raise SystemExit(f"Orden {k!r} en {ruta}: un nombre simple y su comando como lista, p. ej. [\"/usr/local/bin/x\"]")
        ordenes[k] = tuple(v)
    agentes = {}
    for k, v in datos.get("agentes", {}).items():
        if not NOMBRE.fullmatch(k) or not isinstance(v, str) or not re.fullmatch(r"https://[\w.-]+(:\d{1,5})?", v, re.ASCII):
            raise SystemExit(f"Agente {k!r} en {ruta}: `nombre = \"https://host:puerto\"`, sin ruta")
        agentes[k] = v
    nombre = datos.get("nombre") or socket.gethostname().lower()
    return Config(nombre, lista("usuarios"), lista("origenes"), servicios, acciones, ordenes, agentes)


def _correr(argv: list[str], timeout: int = 30) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgenteError(f"{Path(argv[0]).name} no respondió: {e}", 502) from None
    if p.returncode:
        raise AgenteError(f"{Path(argv[0]).name} falló: {(p.stderr or p.stdout).strip()[-400:]}", 502)
    return p.stdout


def _ps(comando: str, timeout: int = 30) -> str:
    """PowerShell 5.1 con salida en UTF-8 (por defecto sale en la página de códigos de la consola)."""
    return _correr(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; {comando}"], timeout)


# --- Recursos -------------------------------------------------------------------------------------------------

_cpu_previo: tuple[int, int] | None = None


def _cpu_muestra() -> tuple[int, int]:
    """(ocupado, total) acumulados desde el arranque."""
    if WINDOWS:
        import ctypes
        from ctypes import wintypes

        inactivo, nucleo, usuario = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(inactivo), ctypes.byref(nucleo), ctypes.byref(usuario))
        n = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
        total = n(nucleo) + n(usuario)  # el tiempo del núcleo ya incluye el inactivo
        return total - n(inactivo), total
    campos = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:9]]
    inactivo = campos[3] + campos[4]  # idle + iowait
    return sum(campos) - inactivo, sum(campos)


def _cpu() -> float:
    """% de CPU desde la consulta anterior (la primera vez, en un tercio de segundo)."""
    global _cpu_previo
    if _cpu_previo is None:
        _cpu_previo = _cpu_muestra()
        time.sleep(0.3)
    ahora = _cpu_muestra()
    ocupado, total = ahora[0] - _cpu_previo[0], ahora[1] - _cpu_previo[1]
    _cpu_previo = ahora
    return round(100 * ocupado / total, 1) if total > 0 else 0.0


def _ram() -> tuple[float, float]:
    """(total, disponible) en GB."""
    if WINDOWS:
        import ctypes

        class Estado(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        *[(n, ctypes.c_ulonglong) for n in ("total", "libre", "pag_total", "pag_libre", "virt_total",
                                                            "virt_libre", "virt_ext")]]

        e = Estado()
        e.dwLength = ctypes.sizeof(Estado)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
        return e.total / 2**30, e.libre / 2**30
    info = dict(x.split(":", 1) for x in Path("/proc/meminfo").read_text().splitlines() if ":" in x)
    kb = lambda k: int(info[k].split()[0]) / 2**20  # noqa: E731
    return kb("MemTotal"), kb("MemAvailable")


def _encendida_desde() -> str:
    if WINDOWS:
        import ctypes

        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        segundos = ctypes.windll.kernel32.GetTickCount64() / 1000
    else:
        segundos = float(Path("/proc/uptime").read_text().split()[0])
    return datetime.fromtimestamp(time.time() - segundos).astimezone().isoformat(timespec="minutes")


def _gpu() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        salida = _correr(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                          "--format=csv,noheader,nounits"], 10)
        nombre, usada, total, uso, temp = [x.strip() for x in salida.splitlines()[0].split(",")]
        return {"nombre": nombre, "vram_usada_gb": round(int(usada) / 1024, 1), "vram_total_gb": round(int(total) / 1024, 1),
                "uso": float(uso), "temperatura": float(temp)}
    except (AgenteError, ValueError, IndexError):
        return None


def _temperatura() -> float | None:
    try:  # Raspberry Pi y la mayoría de los Linux con sensor de SoC
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except (OSError, ValueError):
        return None


CADA_MUESTRA = 5    # s entre muestras de las gráficas
MUESTRAS = 120      # 10 min, como la ventana del rendimiento del Administrador de tareas pero más larga
SERIES = ("cpu", "ram", "gpu", "vram", "temp_gpu", "temp")
_historial: dict[str, deque] = {k: deque(maxlen=MUESTRAS) for k in ("t", *SERIES)}
_ultima: dict = {}
_muestras = threading.Lock()
_muestreador: threading.Thread | None = None


def _muestra() -> None:
    """Una muestra de todo lo que se grafica. El CPU sale del intervalo desde la anterior."""
    total, libre = _ram()
    gpu = _gpu()
    valores = {"cpu": _cpu(), "ram": round(100 * (total - libre) / total, 1), "gpu": gpu and gpu["uso"],
               "vram": gpu and round(100 * gpu["vram_usada_gb"] / gpu["vram_total_gb"], 1),
               "temp_gpu": gpu and gpu["temperatura"], "temp": None if WINDOWS else _temperatura()}
    with _muestras:
        _historial["t"].append(round(time.time()))
        for k in SERIES:
            _historial[k].append(valores[k])
        _ultima.update(valores, ram_total=total, ram_libre=libre, tarjeta=gpu)  # `gpu` ya es la serie de uso


def _muestrear_siempre() -> None:
    while True:
        time.sleep(CADA_MUESTRA)
        try:
            _muestra()
        except Exception as e:  # noqa: BLE001 - una muestra fallida no debe parar las gráficas
            print(f"[agente] muestra fallida: {e}", flush=True)


def muestrear() -> None:
    """Arranca el muestreo de fondo una vez por proceso (el agente suelto y el panel, al arrancar)."""
    global _muestreador
    with _muestras:
        if _muestreador:
            return
        _muestreador = threading.Thread(target=_muestrear_siempre, name="muestras", daemon=True)
        _muestreador.start()


def historial() -> dict:
    with _muestras:
        datos = {k: list(v) for k, v in _historial.items()}
    # Solo las series que esta máquina tiene (sin GPU, sin sensor): el panel dibuja lo que llega
    return {"cada": CADA_MUESTRA, "t": datos["t"], **{k: datos[k] for k in SERIES if any(x is not None for x in datos[k])}}


def recursos() -> dict:
    if not _ultima:  # la primera consulta antes de la primera vuelta del muestreo
        _muestra()
    with _muestras:
        u = dict(_ultima)
    raiz = Path.home().anchor if WINDOWS else "/"
    disco = shutil.disk_usage(raiz)
    return {"cpu": u["cpu"], "nucleos": os.cpu_count(), "ram_total_gb": round(u["ram_total"], 1),
            "ram_libre_gb": round(u["ram_libre"], 1),
            "disco": {"montaje": raiz, "total_gb": round(disco.total / 1e9), "libre_gb": round(disco.free / 1e9)},
            "gpu": u["tarjeta"], "temperatura": u["temp"], "encendida_desde": _encendida_desde()}


# --- Servicios ------------------------------------------------------------------------------------------------

_PS_TAREAS = ("ConvertTo-Json -Compress -InputObject @(Get-ScheduledTask -TaskName 'bakery-*' -EA SilentlyContinue | "
              "ForEach-Object { $i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ nombre = $_.TaskName -replace '^bakery-'; "
              "estado = [string]$_.State; resultado = $i.LastTaskResult; "
              "inicio = if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('s') } else { $null }; "
              "siguiente = if ($i.NextRunTime) { $i.NextRunTime.ToString('s') } else { $null } } })")
_ESTADO_TAREA = {"Running": "activo", "Ready": "detenido", "Queued": "arrancando", "Disabled": "deshabilitado"}
_ESTADO_UNIDAD = {"active": "activo", "inactive": "detenido", "failed": "falló", "activating": "arrancando",
                  "deactivating": "deteniéndose", "reloading": "activo"}


def _detalle_tarea(t: dict) -> str:
    r = t.get("resultado")
    if t["estado"] == "Running" or r == 267009:
        return "corriendo"
    if r == 267011:
        return "nunca ha corrido"
    if r == 0:
        return "terminó bien"
    return f"terminó con código {r if abs(r or 0) < 65536 else hex((r or 0) & 0xFFFFFFFF)}"


def _servicios_windows(cfg: Config) -> list[dict]:
    tareas = json.loads(_ps(_PS_TAREAS) or "[]")
    filtro = set(cfg.servicios)
    return [{"nombre": t["nombre"], "estado": _ESTADO_TAREA.get(t["estado"], t["estado"].lower()), "detalle": _detalle_tarea(t),
             "desde": t["inicio"], "siguiente": t["siguiente"], "controlable": t["nombre"] in cfg.acciones}
            for t in sorted(tareas, key=lambda t: t["nombre"]) if not filtro or t["nombre"] in filtro]


def _bloques_systemctl(salida: str) -> list[dict[str, str]]:
    """`systemctl show a b` imprime un bloque `clave=valor` por unidad, separados por un renglón vacío."""
    return [dict(x.split("=", 1) for x in b.splitlines() if "=" in x) for b in salida.strip().split("\n\n") if b.strip()]


def _servicios_linux(cfg: Config) -> list[dict]:
    if not cfg.servicios:
        return []
    salida = _correr(["systemctl", "show", "--no-pager", "--timestamp=unix",  # `iso` no existe en todas las versiones
                      "-p", "Id,Description,LoadState,ActiveState,SubState,Result,ActiveEnterTimestamp,InactiveEnterTimestamp",
                      *[f"{s}.service" for s in cfg.servicios]])
    res = []
    for nombre, b in zip(cfg.servicios, _bloques_systemctl(salida)):
        activo = b.get("ActiveState", "")
        existe = b.get("LoadState") != "not-found"
        detalle = b.get("Description", "") if existe else "no existe esa unidad"
        if existe and b.get("Result") not in (None, "", "success"):
            detalle += f" · último resultado: {b['Result']}"
        sello = b.get("ActiveEnterTimestamp" if activo == "active" else "InactiveEnterTimestamp") or ""
        desde = (datetime.fromtimestamp(int(sello[1:])).astimezone().isoformat(timespec="minutes")
                 if re.fullmatch(r"@\d+", sello) else None)  # `@1763059600`
        res.append({"nombre": nombre, "estado": _ESTADO_UNIDAD.get(activo, activo) if existe else "no existe",
                    "detalle": f"{b.get('SubState', '')} · {detalle}".strip(" ·"), "desde": desde, "siguiente": None,
                    "controlable": existe and nombre in cfg.acciones})
    return res


def servicios(cfg: Config) -> list[dict]:
    return _servicios_windows(cfg) if WINDOWS else _servicios_linux(cfg)


def _conocido(cfg: Config, nombre: str) -> None:
    if not NOMBRE.fullmatch(nombre or ""):
        raise AgenteError("nombre de servicio inválido")
    if not any(s["nombre"] == nombre for s in servicios(cfg)):
        raise AgenteError(f"no hay un servicio {nombre!r} en {cfg.nombre}", 404)


def log(cfg: Config, nombre: str, n: int = RENGLONES) -> list[str]:
    _conocido(cfg, nombre)
    if WINDOWS:
        archivo = JOBS / f"{nombre}.log"
        if not archivo.is_file():
            return []
        with archivo.open(encoding="utf-8-sig", errors="replace") as f:  # Out-File de PowerShell 5.1 escribe BOM
            return [x.rstrip() for x in deque(f, n)]
    salida = _correr(["journalctl", "-u", f"{nombre}.service", "-n", str(n), "--no-pager", "-o", "short-iso", "--quiet"])
    return salida.splitlines()


def accion(cfg: Config, nombre: str, verbo: str) -> dict:
    if verbo not in VERBOS:
        raise AgenteError(f"acción desconocida: {verbo!r}")
    _conocido(cfg, nombre)
    if nombre not in cfg.acciones:
        raise AgenteError(f"{nombre!r} no está en `acciones` de {cfg.nombre}", 403)
    if not _ACCION.acquire(blocking=False):
        raise AgenteError("ya hay una acción en curso en esta máquina", 409)
    try:
        if WINDOWS:
            # `kill` mata el árbol y deja la tarea registrada, para que `Start-ScheduledTask` la relance igual
            if verbo in ("detener", "reiniciar"):
                _correr(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(JOB), "kill", nombre], 90)
            if verbo in ("iniciar", "reiniciar"):
                _ps(f"Start-ScheduledTask -TaskName 'bakery-{nombre}'")
        else:
            _correr(["systemctl", "--no-ask-password", VERBOS[verbo], f"{nombre}.service"], 90)
    finally:
        _ACCION.release()
    return next(s for s in servicios(cfg) if s["nombre"] == nombre)


def orden(cfg: Config, nombre: str) -> dict:
    if not (argv := cfg.ordenes.get(nombre)):
        raise AgenteError(f"no hay una orden {nombre!r} en {cfg.nombre}", 404)
    if not _ACCION.acquire(blocking=False):
        raise AgenteError("ya hay una acción en curso en esta máquina", 409)
    try:
        salida = _correr(list(argv))
    finally:
        _ACCION.release()
    return {"orden": nombre, "salida": salida.strip()[-400:]}


def maquina(cfg: Config) -> dict:
    return {"nombre": cfg.nombre, "sistema": "windows" if WINDOWS else "linux", "recursos": recursos(),
            "historial": historial(), "servicios": servicios(cfg), "ordenes": sorted(cfg.ordenes),
            "hora": datetime.now().astimezone().isoformat(timespec="seconds")}


def atender(cfg: Config, metodo: str, ruta: str, consulta: dict, cuerpo: dict | None = None) -> tuple[int, dict]:
    """Las rutas del agente, para el servidor suelto y para el panel. (código HTTP, cuerpo)."""
    try:
        if metodo == "GET" and ruta == "/api/maquina":
            return 200, maquina(cfg)
        if metodo == "GET" and ruta == "/api/log":
            nombre = (consulta.get("servicio") or [""])[0]
            return 200, {"servicio": nombre, "renglones": log(cfg, nombre)}
        if metodo == "POST" and ruta == "/api/accion":
            return 200, accion(cfg, str(cuerpo.get("servicio") or ""), str(cuerpo.get("accion") or ""))
        if metodo == "POST" and ruta == "/api/orden":
            return 200, orden(cfg, str(cuerpo.get("orden") or ""))
    except AgenteError as e:
        return e.codigo, {"error": str(e)}
    return 404, {"error": "no existe"}


RUTAS = ("/api/maquina", "/api/log", "/api/accion", "/api/orden")


class _Agente(BaseHTTPRequestHandler):
    cfg: Config = Config("")

    def _origen(self) -> str | None:
        o = self.headers.get("Origin")
        return o if o in self.cfg.origenes else None

    def _responder(self, codigo: int, cuerpo: dict | None) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode() if cuerpo is not None else b""
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if o := self._origen():
            self.send_header("Access-Control-Allow-Origin", o)
            if self.command == "OPTIONS":
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()
        self.wfile.write(datos)

    def _permitido(self) -> bool:
        quien = self.headers.get("Tailscale-User-Login")
        if not quien or quien not in self.cfg.usuarios:
            self._responder(403, {"error": "solo desde el tailnet, con un usuario de la lista"})
            return False
        return True

    def do_OPTIONS(self) -> None:  # preflight: solo se contesta a los orígenes del panel
        self._responder(204 if self._origen() else 403, None)

    def do_GET(self) -> None:
        if self._permitido():
            url = urlsplit(self.path)
            self._responder(*atender(self.cfg, "GET", url.path, parse_qs(url.query)))

    def do_POST(self) -> None:
        if not self._permitido():
            return
        largo = int(self.headers.get("Content-Length") or 0)
        if not 0 < largo <= MAX_CUERPO:
            self.close_connection = True
            return self._responder(400, {"error": f"JSON de hasta {MAX_CUERPO} bytes"})
        crudo = self.rfile.read(largo)
        if self.headers.get_content_type() != "application/json":
            return self._responder(400, {"error": "solo JSON"})
        try:
            cuerpo = json.loads(crudo)
            if not isinstance(cuerpo, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._responder(400, {"error": "JSON inválido"})
        self._responder(*atender(self.cfg, "POST", urlsplit(self.path).path, {}, cuerpo))

    def log_message(self, formato: str, *args) -> None:  # solo las acciones, no cada consulta de estado
        if self.command == "POST":
            super().log_message(formato, *args)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Agente de máquina de Bakery (solo 127.0.0.1; lo publica tailscale serve)")
    p.add_argument("--puerto", type=int, default=PUERTO)
    p.add_argument("--config", type=Path)
    a = p.parse_args(argv)
    cfg = cargar(a.config)
    if not cfg.usuarios:
        raise SystemExit("Define `usuarios` en la configuración: sin lista, el agente no arranca")
    _Agente.cfg = cfg
    muestrear()
    servidor = ThreadingHTTPServer(("127.0.0.1", a.puerto), _Agente)
    print(f"Agente de {cfg.nombre} en http://127.0.0.1:{a.puerto} ({len(cfg.servicios)} servicios, {len(cfg.acciones)} con acciones)",
          flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()

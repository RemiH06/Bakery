import sys
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest

from bakers import agente

YO = {"Tailscale-User-Login": "remi@example.com"}
PANEL = "https://panel.ejemplo.ts.net:8093"


def test_configuracion(tmp_path):
    archivo = tmp_path / "a.toml"
    assert agente.cargar(archivo).acciones == ()  # sin archivo: solo lectura
    archivo.write_text('nombre = "fresa"\nusuarios = ["remi@example.com"]\nservicios = ["dns", "web"]\nacciones = ["dns"]\n'
                       '[ordenes]\ndespertar = ["/usr/local/bin/wake"]\n[agentes]\nkiwi = "https://kiwi.ts.net:8094"\n', "utf-8")
    cfg = agente.cargar(archivo)
    assert (cfg.nombre, cfg.acciones, cfg.ordenes, cfg.agentes) == ("fresa", ("dns",), {"despertar": ("/usr/local/bin/wake",)},
                                                                    {"kiwi": "https://kiwi.ts.net:8094"})
    for malo in ('servicios = ["dns"]\nacciones = ["web"]',  # una acción que no se muestra
                 'servicios = ["dns; rm -rf /"]',            # un nombre que rompería un comando
                 '[ordenes]\nx = "wake"',                     # comando como texto: iría a un shell
                 '[agentes]\nx = "http://x.ts.net"',          # sin TLS
                 '[agentes]\nx = "https://x.ts.net/a"'):      # con ruta
        archivo.write_text(malo, "utf-8")
        with pytest.raises(SystemExit):
            agente.cargar(archivo)


SHOW = """Id=dns.service
Description=Servidor DNS
LoadState=loaded
ActiveState=active
SubState=running
Result=success
ActiveEnterTimestamp=@1763014981
InactiveEnterTimestamp=

Id=web.service
Description=Web
LoadState=loaded
ActiveState=failed
SubState=failed
Result=exit-code
ActiveEnterTimestamp=
InactiveEnterTimestamp=2026-11-13 01:00:00 CST

Id=nada.service
LoadState=not-found
ActiveState=inactive
SubState=dead
"""


def test_servicios_linux(monkeypatch):
    monkeypatch.setattr(agente, "_correr", lambda argv, timeout=30: SHOW)
    cfg = agente.Config("fresa", servicios=("dns", "web", "nada"), acciones=("dns", "nada"))
    dns, web, nada = agente._servicios_linux(cfg)
    assert (dns["estado"], dns["desde"], dns["controlable"]) == ("activo", agente.datetime.fromtimestamp(1763014981).astimezone().isoformat(timespec="minutes"), True)
    assert (web["estado"], web["controlable"]) == ("falló", False) and "exit-code" in web["detalle"]
    assert (nada["estado"], nada["controlable"]) == ("no existe", False)  # aunque esté en acciones


def test_detalle_de_tareas():
    assert agente._detalle_tarea({"estado": "Running", "resultado": 267009}) == "corriendo"
    assert agente._detalle_tarea({"estado": "Ready", "resultado": 0}) == "terminó bien"
    assert agente._detalle_tarea({"estado": "Ready", "resultado": 267011}) == "nunca ha corrido"
    assert agente._detalle_tarea({"estado": "Ready", "resultado": -1073741510}) == "terminó con código 0xc000013a"


@pytest.fixture
def suelto(monkeypatch):
    llamadas = []
    estado = {"dns": "activo"}

    def servicios(cfg):
        return [{"nombre": n, "estado": e, "detalle": "", "desde": None, "siguiente": None, "controlable": n in cfg.acciones}
                for n, e in estado.items()]

    def correr(argv, timeout=30):
        llamadas.append(argv)
        return ""

    monkeypatch.setattr(agente, "servicios", servicios)
    monkeypatch.setattr(agente, "_correr", correr)
    monkeypatch.setattr(agente, "WINDOWS", False)
    cfg = agente.Config("fresa", usuarios=("remi@example.com",), origenes=(PANEL,), servicios=("dns",), acciones=("dns",),
                        ordenes={"despertar": ("/usr/local/bin/wake",)})
    monkeypatch.setattr(agente._Agente, "cfg", cfg)
    s = ThreadingHTTPServer(("127.0.0.1", 0), agente._Agente)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", llamadas
    s.shutdown()


def test_identidad_y_origen(suelto):
    url, _ = suelto
    assert httpx.get(f"{url}/api/log?servicio=dns").status_code == 403  # sin tailscale serve
    assert httpx.get(f"{url}/api/log?servicio=dns", headers={"Tailscale-User-Login": "otra@example.com"}).status_code == 403
    assert httpx.get(f"{url}/api/log?servicio=dns", headers=YO).status_code == 200
    # Preflight: solo el panel puede mandar acciones desde un navegador
    ok = httpx.options(f"{url}/api/accion", headers={"Origin": PANEL, "Access-Control-Request-Method": "POST"})
    assert ok.status_code == 204 and ok.headers["Access-Control-Allow-Origin"] == PANEL
    ajeno = httpx.options(f"{url}/api/accion", headers={"Origin": "https://malo.example", "Access-Control-Request-Method": "POST"})
    assert ajeno.status_code == 403 and "Access-Control-Allow-Origin" not in ajeno.headers
    r = httpx.get(f"{url}/api/log?servicio=dns", headers={**YO, "Origin": "https://malo.example"})
    assert "Access-Control-Allow-Origin" not in r.headers  # el navegador no le deja leer la respuesta


def test_acciones_en_lista_blanca(suelto):
    url, llamadas = suelto
    pedir = lambda **c: httpx.post(f"{url}/api/accion", headers=YO, json=c)  # noqa: E731
    assert pedir(servicio="dns", accion="reiniciar").status_code == 200
    assert llamadas[-1] == ["systemctl", "--no-ask-password", "restart", "dns.service"]
    assert pedir(servicio="dns", accion="borrar").status_code == 400
    assert pedir(servicio="ssh", accion="detener").status_code == 404  # no está en la lista
    assert pedir(servicio="../dns", accion="detener").status_code == 400
    assert httpx.post(f"{url}/api/accion", headers=YO, data={"servicio": "dns"}).status_code == 400  # formulario: sin preflight
    r = httpx.post(f"{url}/api/orden", headers=YO, json={"orden": "despertar"})
    assert r.status_code == 200 and llamadas[-1] == ["/usr/local/bin/wake"]  # el comando fijo, sin nada de la petición
    assert httpx.post(f"{url}/api/orden", headers=YO, json={"orden": "rm"}).status_code == 404


def test_recursos_de_esta_maquina():
    r = agente.recursos()
    assert 0 <= r["cpu"] <= 100 and 0 < r["ram_libre_gb"] <= r["ram_total_gb"] and r["disco"]["total_gb"] > 0


def test_orden_real(tmp_path, monkeypatch):
    cfg = agente.Config("fresa", ordenes={"hola": (sys.executable, "-c", "print('hola')")})
    assert agente.orden(cfg, "hola") == {"orden": "hola", "salida": "hola"}

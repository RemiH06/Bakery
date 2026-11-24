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


def test_historial_solo_con_las_series_de_la_maquina(monkeypatch):
    for k in agente._historial:
        monkeypatch.setitem(agente._historial, k, agente.deque(maxlen=agente.MUESTRAS))
    monkeypatch.setattr(agente, "_gpu", lambda: None)  # sin GPU: ni uso ni VRAM en las gráficas
    agente._muestra()
    agente._muestra()
    h = agente.historial()
    assert len(h["t"]) == len(h["cpu"]) == len(h["ram"]) == 2 and "gpu" not in h and "vram" not in h
    assert agente.recursos()["gpu"] is None


def test_proyecto_y_ntfy_en_la_configuracion(tmp_path):
    archivo = tmp_path / "a.toml"
    archivo.write_text('ntfy = "~/ntfy.env"\n[proyecto]\nadguardhome = "spidernet"\n"mapo-*" = "mapo"\n', "utf-8")
    cfg = agente.cargar(archivo)
    assert cfg.ntfy == agente.Path("~/ntfy.env").expanduser()
    assert [agente.proyecto_de(cfg, n) for n in ("adguardhome", "mapo-respaldo", "cola")] == ["spidernet", "mapo", "bakery"]
    archivo.write_text('[proyecto]\nx = "dos palabras"\n', "utf-8")
    with pytest.raises(SystemExit):
        agente.cargar(archivo)


def test_latidos_y_su_estado(tmp_path):
    assert [agente.horas(x) for x in ("10m", "6h", "1d", "1.5h")] == [1 / 6, 6, 24, 1.5]
    for malo in ("", "1", "0h", "1w", "-1h", "400d"):
        with pytest.raises(ValueError):
            agente.horas(malo)
    agente.escribir_latido(tmp_path, "tabularium", "diario", 24, 0)
    agente.escribir_latido(tmp_path, "mapo", "respaldo", 24, 2, unidad="respaldo", aviso_falla=False)
    agente.escribir_latido(tmp_path, "bakery", "analizar", 1 / 6, 0)
    (tmp_path / "roto.json").write_text("{", "utf-8")
    with pytest.raises(ValueError):
        agente.escribir_latido(tmp_path, "a b", "x", 1, 0)
    assert not list(tmp_path.glob(".*.tmp"))
    cfg = agente.Config("fresa", latidos=tmp_path)
    ahora = agente.time.time()
    estados = lambda t: {l["proceso"]: l["estado"] for l in agente.latidos(cfg, t)}  # noqa: E731
    assert estados(ahora) == {"analizar": "bien", "respaldo": "falló", "diario": "bien", "roto": "falló"}
    # Cada 10 min: atrasado pasada la hora y 10 min; diario: pasadas 36 h
    assert estados(ahora + 3600)["analizar"] == "bien" and estados(ahora + 4300)["analizar"] == "atrasado"
    assert estados(ahora + 35 * 3600)["diario"] == "bien" and estados(ahora + 37 * 3600)["diario"] == "atrasado"
    mapo = next(l for l in agente.latidos(cfg, ahora) if l["proyecto"] == "mapo")
    assert (mapo["unidad"], mapo["aviso_falla"], mapo["detalle"]) == ("respaldo", False, "cada 1 d · terminó con código 2")


def test_historial_de_corridas(tmp_path, monkeypatch):
    monkeypatch.setattr(agente, "TOPE_CORRIDAS", 3)
    cfg = agente.Config("fresa", latidos=tmp_path)
    antes = agente.datetime.fromtimestamp(agente.time.time() - 90)
    for codigo in range(5):
        agente.escribir_latido(tmp_path, "mapo", "respaldo", 24, codigo, inicio=antes, resumen="  una\nlínea " + "x" * 300)
    archivo = tmp_path / "mapo.respaldo.jsonl"
    assert len(archivo.read_text("utf-8").splitlines()) == 3  # con tope
    archivo.write_text(archivo.read_text("utf-8") + 'roto\n[]\n{"fin": "ayer", "codigo": 0}\n'
                       '{"inicio": "2026-11-24T10:00:00-06:00", "fin": "2026-11-24T09:00:00-06:00", "codigo": 0}\n', "utf-8")
    codigo, d = agente.atender(cfg, "GET", "/api/corridas", {"servicio": ["mapo-respaldo"]})
    assert codigo == 200 and [c["codigo"] for c in d["corridas"]] == [0, 4, 3, 2]  # la última primero, sin las rotas
    assert d["corridas"][0]["duracion_s"] is None  # el reloj se ajustó a media corrida
    assert 89 <= d["corridas"][1]["duracion_s"] <= 92
    assert d["corridas"][1]["resumen"].startswith("una línea x") and len(d["corridas"][1]["resumen"]) == agente.MAX_RESUMEN
    assert [l["proceso"] for l in agente.latidos(cfg)] == ["respaldo"]  # el .jsonl no es un latido
    assert 89 <= agente.latidos(cfg)[0]["duracion_s"] <= 92
    for nombre, esperado in (("otro", 404), ("../x", 400), ("", 400)):
        assert agente.atender(cfg, "GET", "/api/corridas", {"servicio": [nombre]})[0] == esperado
    # Un latido de antes del historial: sin inicio ni .jsonl
    (tmp_path / "viejo.x.json").write_text('{"proyecto": "viejo", "proceso": "x", "unidad": "x", "codigo": 0, "cada_h": 24, '
                                           '"fin": "2026-11-24T10:00:00-06:00"}', "utf-8")
    assert agente.corridas(cfg, "x")["corridas"] == []
    # Sin poder escribir el historial, el latido queda igual
    (tmp_path / "doll.sentido.jsonl").mkdir()
    assert agente.escribir_latido(tmp_path, "doll", "sentido", 24, 0).exists()


def test_servicios_agrupados_por_proyecto(tmp_path, monkeypatch):
    monkeypatch.setattr(agente, "WINDOWS", False)
    monkeypatch.setattr(agente, "_servicios_linux", lambda cfg: [
        {"nombre": n, "estado": e, "detalle": "", "desde": None, "siguiente": None, "controlable": False}
        for n, e in (("adguardhome", "activo"), ("tabularium-respaldo", "detenido"), ("ssh", "activo"))])
    agente.escribir_latido(tmp_path, "tabularium", "respaldo", 24, 1)
    agente.escribir_latido(tmp_path, "tabularium", "diario", 24, 0)  # unidad de usuario: no está en `servicios`
    cfg = agente.Config("fresa", latidos=tmp_path, proyectos=(("adguard*", "spidernet"),))
    s = {x["nombre"]: x for x in agente.servicios(cfg)}
    assert {n: (x["proyecto"], x["estado"], x.get("proceso")) for n, x in s.items()} == {
        "adguardhome": ("spidernet", "activo", None), "ssh": ("bakery", "activo", None),
        "tabularium-respaldo": ("tabularium", "falló", "respaldo"), "tabularium-diario": ("tabularium", "bien", "diario")}
    assert s["tabularium-diario"]["controlable"] is False


def test_log_de_una_unidad_de_usuario(tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(agente, "WINDOWS", False)
    monkeypatch.setattr(agente, "_servicios_linux", lambda cfg: [])
    monkeypatch.setattr(agente, "_correr", lambda argv, timeout=30: llamadas.append(argv) or "renglón\n")
    agente.escribir_latido(tmp_path, "tabularium", "diario", 24, 0)
    assert agente.log(agente.Config("fresa", latidos=tmp_path), "tabularium-diario") == ["renglón"]
    assert llamadas[-1][1:4] == ["_SYSTEMD_USER_UNIT=tabularium-diario.service", "+", "USER_UNIT=tabularium-diario.service"]


def test_avisos_una_vez_por_cambio(tmp_path, monkeypatch):
    enviados = []
    monkeypatch.setattr(agente, "avisar", lambda cfg, titulo, *a, **k: enviados.append(titulo))
    monkeypatch.setattr(agente, "_avisados", {})
    cfg = agente.Config("fresa", latidos=tmp_path)
    ahora = agente.time.time()
    monkeypatch.setattr(agente, "_ARRANQUE", ahora - agente.GRACIA - 1)
    agente.escribir_latido(tmp_path, "tabularium", "diario", 24, 1)
    agente.escribir_latido(tmp_path, "tabularium", "oido", 1, 1, aviso_falla=False)  # su proyecto ya avisa la falla
    assert agente.revisar(cfg, ahora) == ["Bakery: tabularium · diario en fresa falló"]
    assert agente.revisar(cfg, ahora) == []  # el mismo estado no se repite
    agente.escribir_latido(tmp_path, "tabularium", "diario", 24, 0)
    assert agente.revisar(cfg, ahora) == ["Bakery: tabularium · diario en fresa volvió a terminar bien"]
    # Atrasado: se avisa aunque el proyecto avise sus fallas, pero no recién prendida la máquina
    agente.escribir_latido(tmp_path, "tabularium", "oido", 1, 0)
    tarde = ahora + 3 * 3600
    monkeypatch.setattr(agente, "_ARRANQUE", tarde - 60)
    assert agente.revisar(cfg, tarde) == []
    monkeypatch.setattr(agente, "_ARRANQUE", ahora)
    assert sorted(agente.revisar(cfg, tarde)) == ["Bakery: tabularium · oido en fresa no ha corrido"]


def test_latido_desde_systemd(tmp_path, monkeypatch):
    def leer():
        return agente.json.loads((tmp_path / "doll.sentido.json").read_text("utf-8"))["codigo"]
    base = ["latido", "doll", "sentido", "--cada", "1d", "--carpeta", str(tmp_path)]
    monkeypatch.setenv("SERVICE_RESULT", "exit-code")
    monkeypatch.setenv("EXIT_STATUS", "3")
    agente.main(base)
    assert leer() == 3
    monkeypatch.setenv("EXIT_STATUS", "SEGV")  # señal: no es número, cuenta como falla
    agente.main(base)
    assert leer() == 1
    monkeypatch.setenv("SERVICE_RESULT", "success")
    monkeypatch.setenv("EXIT_STATUS", "0")
    agente.main(base)
    assert leer() == 0
    # Con INVOCATION_ID, el inicio sale de systemd, del manager que corre esta misma invocación
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setattr(agente, "_correr", lambda argv, timeout=30: (
        f"InvocationID={'otra' if '--user' in argv else 'abc'}\nInactiveExitTimestamp=@{100 if '--user' in argv else 1763059600}\n"))
    agente.main(base)
    ultima = agente.json.loads((tmp_path / "doll.sentido.jsonl").read_text("utf-8").splitlines()[-1])
    assert agente.datetime.fromisoformat(ultima["inicio"]).timestamp() == 1763059600
    resumenes = [agente.json.loads(x)["resumen"] for x in (tmp_path / "doll.sentido.jsonl").read_text("utf-8").splitlines()]
    assert resumenes == ["exit-code 3", "exit-code SEGV", "", ""]
    monkeypatch.delenv("SERVICE_RESULT")
    with pytest.raises(SystemExit):
        agente.main(base)  # fuera de systemd, sin --codigo
    agente.main([*base, "--codigo", "0"])

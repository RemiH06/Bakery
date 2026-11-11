import threading
from datetime import datetime
from http.server import ThreadingHTTPServer

import httpx
import pytest

from bakers import cola, core, panel
from bakers.core import BakerError

YO = {"Tailscale-User-Login": "remi@example.com"}


@pytest.fixture
def url(monkeypatch, tmp_path):
    monkeypatch.setattr(cola, "COLA", tmp_path / "cola")
    monkeypatch.setattr(cola, "ESTADO", tmp_path / "cola" / "cola.json")
    monkeypatch.setattr(cola, "ERRORES", tmp_path / "cola" / "errores.jsonl")
    monkeypatch.setattr(cola, "_libre_gb", lambda: 100.0)

    def caido():
        raise BakerError("Sin respuesta de llama-swap")

    monkeypatch.setattr(core, "estado", caido)
    logs = tmp_path / "jobs"
    logs.mkdir()
    (logs / "cola.log").write_text("[cola] bajado AAA (1 hoy)\n", "utf-8")
    monkeypatch.setattr(panel._Panel, "logs", logs)
    monkeypatch.setattr(panel._Panel, "usuarios", set())
    monkeypatch.setattr(panel._Panel, "bandeja", None)
    s = ThreadingHTTPServer(("127.0.0.1", 0), panel._Panel)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def test_solo_desde_el_tailnet(url, monkeypatch):
    assert httpx.get(url).status_code == 403  # sin el encabezado de `tailscale serve`
    assert httpx.get(url, headers=YO).text.startswith("<!doctype html>")
    monkeypatch.setattr(panel._Panel, "usuarios", {"otra@example.com"})
    assert httpx.get(f"{url}/api/estado", headers=YO).status_code == 403


def test_pegar_enlaces_y_ver_el_estado(url):
    texto = "Osiris: https://www.instagram.com/reel/AAA/?igsh=x\n# Diseño\nhttps://www.instagram.com/p/BBB/\nhola"
    r = httpx.post(f"{url}/api/agregar", headers=YO, json={"texto": texto, "seccion": "Política"})
    assert r.json() == {"agregados": 2, "repetidos": 0, "ya_bajados": 0, "sin_enlace": 1, "en_cola": 2}
    d = httpx.get(f"{url}/api/estado", headers=YO).json()
    a, b = d["items"]
    assert (a["clave"], a["seccion"], a["etiqueta"], a["url"]) == ("AAA", "Política", "Osiris",
                                                                  "https://www.instagram.com/reel/AAA/")
    assert (b["seccion"], b["url"]) == ("Diseño", "https://www.instagram.com/p/BBB/")  # el encabezado manda
    assert d["marcha"].startswith("sin respuesta") and d["logs"] == {"cola": ["[cola] bajado AAA (1 hoy)"]}


POEMA = "\n  Arde la miel,\nno el agua.\n\n¿Quién nombra al río?   \n"


def test_texto_sin_enlaces_va_a_la_bandeja_tal_cual(url, monkeypatch, tmp_path):
    assert httpx.post(f"{url}/api/agregar", headers=YO, json={"texto": POEMA}).status_code == 400  # sin bandeja
    monkeypatch.setattr(panel._Panel, "bandeja", tmp_path / "Bandeja")
    monkeypatch.setattr(cola, "_ahora", lambda: datetime(2026, 11, 10, 19, 32))
    for _ in range(2):
        r = httpx.post(f"{url}/api/agregar", headers=YO, json={"texto": POEMA, "seccion": "AyP"})
    assert r.json() == {"bandeja": "2026-11-10-1932-arde-la-miel-no-el-agua-2.md"}
    nota = (tmp_path / "Bandeja" / "2026-11-10-1932-arde-la-miel-no-el-agua.md").read_text("utf-8")
    assert nota == ("---\ntipo: bandeja\nestado: semilla\nfecha: 2026-11-10T19:32\norigen: panel de Bakery\n"
                    'pista: "AyP"\n---\n  Arde la miel,\nno el agua.\n\n¿Quién nombra al río?   \n')
    assert cola._leer()["items"] == {}  # no pasó por la cola


def test_acciones_solo_con_json(url):
    # Un formulario de otro sitio manda form-urlencoded, que no necesita preflight: se rechaza
    assert httpx.post(f"{url}/api/agregar", headers=YO, data={"texto": "https://x.com/a"}).status_code == 400
    assert httpx.post(f"{url}/api/reintentar", headers=YO, json={"tipo": "todo"}).status_code == 400
    assert httpx.post(f"{url}/api/reintentar", headers=YO, json={}).json() == {"reintentados": 0, "en_cola": 0}

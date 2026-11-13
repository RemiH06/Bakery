import sys
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
    monkeypatch.setattr(panel._Panel, "usuarios", set())
    panel.configurar(str(logs))
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


def test_pagina_y_archivos_solo_de_la_lista_blanca(url):
    r = httpx.get(f"{url}/web/panel.css", headers=YO)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "script-src 'self';" in r.headers["content-security-policy"]  # sin 'unsafe-inline'
    assert httpx.get(f"{url}/web/fuentes/inter-400-normal.woff2", headers=YO).headers["content-type"] == "font/woff2"
    for raro in ("/web/../panel.py", "/web/%2e%2e/panel.py", "/web/js/../../cola.py", "/web//etc/hosts", "/panel.py"):
        assert httpx.get(f"{url}{raro}", headers=YO).status_code == 404, raro


INSPO = {
    "2026-11-06-panadera.ficticia-rentabilidad.md": "---\ntipo: inspiración\nclase: negocios\n---\n# Rentabilidad de la IA\n\n"
    "- Fuente: @panadera.ficticia, https://www.instagram.com/reel/XyZ123abc/\n- Formato: reel, 02:47\n- Visto: 2026-11-06\n"
    "- Destino: [[0. emprendimiento|Emprendimiento]]\n\n## Modelo\nNVIDIA vende la infraestructura.\n\n"
    "| Recurso | Qué es |\n|---|---|\n| DLSS 5 | Tecnología de renderizado |\n",
    "2026-10-30-poeta-anhelo.md": "---\ntipo: inspiración\nclase: reflexion\n---\n# Sobre el anhelo\n\n"
    "- Fuente: @poeta, https://www.instagram.com/reel/AAA/\n- Visto: 2026-10-30\n- Destino: [[AyP]], [[16.100|100]]\n\n"
    "## Cita\nLa página en blanco también arde.\n",
    "2026-10-29-taller-shaders.md": "---\ntipo: inspiración\nclase: animacion\n---\n# Fondo de shaders\n\n"
    "- Fuente: @taller, https://www.instagram.com/reel/BBB/\n- Visto: 2026-10-29\n"
    "- Destino: [[58.Zootropo\\|Zootropo]], [[37.iroFactory|iroFactory]]\n",
    "0. Clases de inspiración.md": "---\ntipo: índice\n---\n# Clases\nla página de clases\n",
}


@pytest.fixture
def con_notas(url, tmp_path):
    inspo = tmp_path / "Inspiración"
    inspo.mkdir()
    for nombre, texto in INSPO.items():
        (inspo / nombre).write_text(texto, "utf-8")
    bandeja = tmp_path / "Bandeja"
    bandeja.mkdir()
    panel.guardar_texto("Arde la miel,\nno el agua.", bandeja, "AduSI")
    panel.configurar(None, str(bandeja), str(inspo))
    return url


def test_filtro_literal_sin_mayusculas_ni_acentos(con_notas):
    buscar = lambda **p: httpx.get(f"{con_notas}/api/notas", headers=YO, params=p).json()  # noqa: E731
    todo = buscar()
    assert todo["total"] == 3 and todo["fuentes"] == ["inspo", "bandeja"]  # el índice "0. ..." no cuenta
    assert [n["nombre"][:10] for n in todo["notas"]] == ["2026-11-06", "2026-10-30", "2026-10-29"]  # lo más nuevo primero
    r = buscar(q="PAGINA en  blanco")  # mayúsculas, sin acento y con doble espacio
    assert [n["titulo"] for n in r["notas"]] == ["Sobre el anhelo"]
    assert "La página en blanco también arde." in r["notas"][0]["fragmento"]  # el fragmento conserva los acentos
    assert [n["titulo"] for n in buscar(q="dlss")["notas"]] == ["Rentabilidad de la IA"]  # dentro de una tabla
    assert [n["titulo"] for n in buscar(q="clase: animacion")["notas"]] == ["Fondo de shaders"]  # en el frontmatter
    assert buscar(q="no existe en ninguna")["notas"] == []


def test_grupos_por_destino_y_conteos(con_notas):
    buscar = lambda **p: httpx.get(f"{con_notas}/api/notas", headers=YO, params=p).json()  # noqa: E731
    todo = buscar()
    grupos = {n["titulo"]: n["grupos"] for n in todo["notas"]}
    assert grupos == {"Rentabilidad de la IA": ["otros"], "Sobre el anhelo": ["AyP", "100"], "Fondo de shaders": ["iroFactory"]}
    assert todo["conteo"]["grupos"] == {"otros": 1, "AyP": 1, "100": 1, "iroFactory": 1} and todo["conteo"]["todos"] == 3
    r = buscar(grupo="AyP", clase="reflexion", mes="2026-10")
    assert [n["titulo"] for n in r["notas"]] == ["Sobre el anhelo"]
    assert r["conteo"]["grupos"] == {"AyP": 1, "100": 1}  # cada pestaña cuenta con los demás filtros puestos
    assert buscar(grupo="AyP")["conteo"]["clases"] == {"reflexion": 1}  # la clase cuenta dentro de la pestaña
    n = todo["notas"][0]
    assert (n["cuenta"], n["url"], n["clase"], n["formato"]) == ("@panadera.ficticia", "https://www.instagram.com/reel/XyZ123abc/",
                                                                "negocios", "reel, 02:47")


def test_bandeja_y_nota_completa(con_notas):
    b = httpx.get(f"{con_notas}/api/notas", headers=YO, params={"fuente": "bandeja"}).json()["notas"]
    assert [(n["titulo"], n["grupos"], n["pista"]) for n in b] == [("Arde la miel, no el agua.", ["AduSI"], "AduSI")]
    nota = httpx.get(f"{con_notas}/api/nota", headers=YO, params={"fuente": "bandeja", "nombre": b[0]["nombre"]}).json()
    assert nota["texto"].endswith("Arde la miel,\nno el agua.\n") and nota["estado"] is None


def test_nota_solo_por_nombre_del_indice(con_notas, tmp_path):
    (tmp_path / "secreto.md").write_text("no", "utf-8")
    pedir = lambda **p: httpx.get(f"{con_notas}/api/nota", headers=YO, params=p)  # noqa: E731
    assert pedir(nombre="2026-10-30-poeta-anhelo.md").status_code == 200
    for raro in ("../secreto.md", "..\\secreto.md", str(tmp_path / "secreto.md"), "0. Clases de inspiración.md", ""):
        assert pedir(nombre=raro).status_code == 404, raro
    assert pedir(fuente="otra", nombre="x.md").status_code == 404
    assert httpx.get(f"{con_notas}/api/nota", params={"nombre": "2026-10-30-poeta-anhelo.md"}).status_code == 403


FALSO_DOLL = r'''import json, sys
modo, consulta, k = sys.argv[1:]
f = lambda ruta, enc: {"ruta": ruta, "encabezado": enc, "linea_ini": 3, "linea_fin": 5, "texto": consulta, "terceros": True}
frs = [f("2026-10-30-poeta-anhelo.md", "Cita"), f("2026-10-30-poeta-anhelo.md", "Otra"), f("0. Clases de inspiración.md", "Clases")]
if consulta == "truena":
    sys.exit("se cayó el índice")
print(json.dumps({"fragmentos": frs, "aviso": None} if modo == "sentido" else
                 {"respuesta": "", "no_encontrado": True, "fallo": None, "citas_descartadas": 0, "intentos": 0,
                  "faltan": ["Zacarías"], "citas": [], "fragmentos": []} if "Zacarías" in consulta else
                 {"respuesta": "Arde.", "no_encontrado": False, "fallo": None, "citas_descartadas": 0, "faltan": [],
                  "citas": [{"texto": "arde", "ruta": frs[0]["ruta"], "linea_ini": 3, "linea_fin": 3}], "fragmentos": []}))
'''


def test_doll_por_el_puente(con_notas, monkeypatch, tmp_path):
    assert httpx.get(f"{con_notas}/api/doll", headers=YO, params={"q": "x"}).status_code == 404  # sin --doll
    puente = tmp_path / "puente.py"
    puente.write_text(FALSO_DOLL, "utf-8")
    monkeypatch.setattr(panel, "PUENTE", puente)
    monkeypatch.setattr(panel._Panel, "doll", sys.executable)
    r = httpx.get(f"{con_notas}/api/doll", headers=YO, params={"q": "página que arde"}).json()
    a, b = r["notas"]  # agrupados por nota, en el orden de Doll
    assert (a["titulo"], a["abrible"], [x["encabezado"] for x in a["fragmentos"]]) == ("Sobre el anhelo", True, ["Cita", "Otra"])
    assert a["fragmentos"][0]["texto"] == "página que arde" and a["grupos"] == ["AyP", "100"]
    assert (b["nombre"], b["abrible"]) == ("0. Clases de inspiración.md", False) and r["aviso"] is None
    assert httpx.get(f"{con_notas}/api/doll", headers=YO, params={"q": "truena"}).json()["error"].endswith("se cayó el índice")
    assert httpx.get(f"{con_notas}/api/doll", headers=YO, params={"q": " "}).status_code == 400
    p = httpx.post(f"{con_notas}/api/doll/preguntar", headers=YO, json={"q": "¿qué arde?"}, timeout=30).json()
    assert (p["respuesta"], p["citas"][0]["texto"], p["notas"], p["faltan"]) == ("Arde.", "arde", [], [])
    # Doll cortó antes del modelo: el porqué viene de Doll y el panel lo pasa tal cual
    p = httpx.post(f"{con_notas}/api/doll/preguntar", headers=YO, json={"q": "¿Qué dijo Zacarías?"}, timeout=30).json()
    assert (p["no_encontrado"], p["faltan"]) == (True, ["Zacarías"])
    # Preguntar gasta GPU: solo por POST con JSON
    assert httpx.get(f"{con_notas}/api/doll/preguntar", headers=YO, params={"q": "x"}).status_code == 404


def test_acciones_solo_con_json(url):
    # Un formulario de otro sitio manda form-urlencoded, que no necesita preflight: se rechaza
    assert httpx.post(f"{url}/api/agregar", headers=YO, data={"texto": "https://x.com/a"}).status_code == 400
    assert httpx.post(f"{url}/api/reintentar", headers=YO, json={"tipo": "todo"}).status_code == 400
    assert httpx.post(f"{url}/api/reintentar", headers=YO, json={}).json() == {"reintentados": 0, "en_cola": 0}

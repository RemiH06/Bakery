import json

import pytest

from bakers import clases, cola, core, reel
from bakers.core import BakerError

TABLA = """# Clases

| Clase | Identificador | Qué se guarda | Destino | Material |
|---|---|---|---|---|
| Diseño | `diseno` | Descripción visual | [[37.iroFactory\\|iroFactory]], skill `frontend-design` | Se conserva |
| Crítica social | `critica` | Texto completo y citas | [[AduSI]] | Se borra |
| Ruido | `ruido` | Solo el ID en la cola | — | Se borra |

| Otra tabla | Sin identificador |
|---|---|
| x | y |
"""

VIEJA = """---
tipo: inspiración
estado: semilla
---
# Crítica a la meritocracia

- Fuente: @alguien, https://www.instagram.com/reel/AAA/
- Formato: reel, 01:10
- Visto: 2026-11-05
- Material (video, transcripción, fotogramas): `{material}`

## Idea central
El mérito como coartada.

## Recursos
| Recurso | Qué es | Dónde | Verificado |
|---|---|---|---|

## Citas
- [00:03] "nadie llega solo"

## Texto en pantalla

## Visual
Plano fijo.

## Afirmaciones por verificar
- El 90 % hereda su puesto.

## Aplicación
- (pendiente)

## Notas de Remi
Leer junto con Sandel.
"""


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    notas = tmp_path / "notas"
    notas.mkdir()
    (notas / clases.NOTA_CLASES).write_text(TABLA, "utf-8")
    monkeypatch.setattr(reel, "CARPETA", tmp_path / "reels")
    return notas


def _clasificador(monkeypatch, por_tema: dict[str, str]):
    """`core.bake` falso: clase según el tema con que empieza cada renglón."""
    vistos = []

    def bake(baker, tarea, rutas, categorias):
        assert baker == "clasificador" and "revisar" in categorias and "ruido" in categorias
        assert "- diseno: Diseño. Keeps: Descripción visual" in tarea
        renglones = open(rutas[0], encoding="utf-8").read().splitlines()
        vistos.extend(renglones)
        por = {}
        for n, x in enumerate(renglones, 1):
            clase = next(c for t, c in por_tema.items() if x.startswith(t))
            por.setdefault(clase, {rutas[0]: []})[rutas[0]].append(n)
        return {"conteo": {}, "por_categoria": por}

    monkeypatch.setattr(core, "bake", bake)
    return vistos


def test_lee_la_tabla_de_clases(carpeta):
    t = clases.cargar(carpeta)
    assert list(t) == ["diseno", "critica", "ruido"]
    assert t["diseno"]["destino"] == "[[37.iroFactory|iroFactory]], skill `frontend-design`"
    assert t["diseno"]["conserva"] and not t["critica"]["conserva"] and t["ruido"]["destino"] == ""


def test_clase_sin_plantilla_o_sin_nota(carpeta, tmp_path):
    (carpeta / clases.NOTA_CLASES).write_text(TABLA.replace("`critica`", "`astrologia`"), "utf-8")
    with pytest.raises(BakerError, match="sin plantilla.*astrologia"):
        clases.cargar(carpeta)
    with pytest.raises(BakerError, match="Falta la nota de clases"):
        clases.cargar(tmp_path)


def _pieza(tmp_path, codigo, tema):
    material = tmp_path / "reels" / codigo
    material.mkdir(parents=True)
    (material / "video.mp4").write_bytes(b"x")
    bloques = {"tema": tema, "fuente": f"@cuenta, https://www.instagram.com/reel/{codigo}/", "formato": "reel, 00:30",
               "visto": "2026-11-09", "material": str(material), "idea_central": "Algo.", "recursos": "",
               "citas": '- [00:01] "hola"', "texto_en_pantalla": "", "visual": "Paleta ocre.", "afirmaciones": "",
               "pasos": "", "transcripcion": "- [00:01] hola\n- [00:04] y adiós"}
    (material / "reel.json").write_text(json.dumps({"cuenta": "cuenta", "bloques": bloques}), "utf-8")
    return material


def test_analizar_clasifica_escribe_y_borra(monkeypatch, tmp_path, carpeta):
    monkeypatch.setattr(cola, "COLA", tmp_path / "cola")
    monkeypatch.setattr(cola, "ESTADO", tmp_path / "cola" / "cola.json")
    monkeypatch.setattr(cola, "_libre_gb", lambda: 100.0)
    monkeypatch.setattr(core, "estado", lambda: {"marcha": "alta", "bakers": {"clasificador": "bonsai"}, "cargados": []})
    items = {}
    for codigo, tema in (("AAA", "Paleta"), ("BBB", "Poder"), ("CCC", "Meme"), ("DDD", "Rareza")):
        items[codigo] = {"url": f"https://www.instagram.com/reel/{codigo}/", "estado": "clasificar",
                         "material": str(_pieza(tmp_path, codigo, tema)), "seccion": "Política" if codigo == "BBB" else None}
    cola._guardar({"items": items, "pausa_hasta": None, "motivo": None, "dia": None, "bajados_hoy": 0})
    vistos = _clasificador(monkeypatch, {"Paleta": "diseno", "Poder": "critica", "Meme": "ruido", "Rareza": "revisar"})

    assert cola.analizar(str(carpeta))["conteo"] == {"analizado": 4}
    assert vistos[1] == "Poder. Algo. Account: @cuenta. [Política]"  # la sección de Remi va de pista
    e = cola._leer()["items"]
    assert [e[k]["clase"] for k in "AAA BBB CCC DDD".split()] == ["diseno", "critica", "ruido", "revisar"]
    assert e["CCC"]["nota"] is None and not (tmp_path / "reels" / "CCC").exists()  # ruido: sin nota ni material

    diseno = (carpeta / "2026-11-09-cuenta-paleta.md").read_text("utf-8")
    assert diseno.startswith("---\ntipo: inspiración\nclase: diseno\n---\n# Paleta\n")
    assert "- Destino: [[37.iroFactory|iroFactory]]" in diseno and "## Descripción visual" in diseno
    assert "- Material" in diseno and (tmp_path / "reels" / "AAA").is_dir()  # diseño conserva

    critica = (carpeta / "2026-11-09-cuenta-poder.md").read_text("utf-8")
    assert "## Texto completo\n- [00:01] hola\n- [00:04] y adiós" in critica
    assert "- Material" not in critica and not (tmp_path / "reels" / "BBB").exists()
    assert "## Pasos" not in critica and "## Recursos" not in critica  # vacías: fuera

    revisar = (carpeta / "2026-11-09-cuenta-rareza.md").read_text("utf-8")
    assert "Pregúntale a Remi" in revisar and (tmp_path / "reels" / "DDD").is_dir()


def test_sin_nota_de_clases_las_piezas_esperan(monkeypatch, tmp_path, carpeta):
    monkeypatch.setattr(cola, "COLA", tmp_path / "cola")
    monkeypatch.setattr(cola, "ESTADO", tmp_path / "cola" / "cola.json")
    monkeypatch.setattr(cola, "_libre_gb", lambda: 100.0)
    monkeypatch.setattr(core, "estado", lambda: {"marcha": "alta", "bakers": {"clasificador": "bonsai"}, "cargados": []})
    monkeypatch.setattr(core, "bake", lambda *a: pytest.fail("sin clases no se llama al clasificador"))
    cola._guardar({"items": {"AAA": {"url": "u", "estado": "clasificar", "material": str(_pieza(tmp_path, "AAA", "T"))}},
                   "pausa_hasta": None, "motivo": None, "dia": None, "bajados_hoy": 0})
    assert cola.analizar(str(tmp_path))["conteo"] == {"clasificar": 1}


def test_reclasificar_notas_viejas(monkeypatch, tmp_path, carpeta):
    material = tmp_path / "reels" / "AAA"
    material.mkdir(parents=True)
    (material / "transcripcion.json").write_text(json.dumps([
        {"t": "00:01", "texto": "letra inventada", "logprob": -4.0},
        {"t": "00:03", "texto": "nadie llega solo", "logprob": -0.2}]), "utf-8")
    (carpeta / "2026-11-05-alguien-critica.md").write_text(VIEJA.format(material=material), "utf-8")
    (carpeta / "2026-11-05-otro-meme.md").write_text(
        "# Meme\n\n- Fuente: @otro, https://www.instagram.com/reel/BBB/\n\n## Idea central\nNada.\n", "utf-8")
    (carpeta / "2026-11-05-ya-tiene.md").write_text("---\nclase: diseno\n---\n# Ya\n", "utf-8")
    vistos = _clasificador(monkeypatch, {"Crítica": "critica", "Meme": "ruido"})

    assert clases.reclasificar(str(carpeta), pistas={"AAA": "Política"}) == {"critica": 1, "ruido": 1}
    assert vistos == ["Crítica a la meritocracia. El mérito como coartada. Account: @alguien. [Política]",
                      "Meme. Nada. Account: @otro."]
    nota = (carpeta / "2026-11-05-alguien-critica.md").read_text("utf-8")
    assert nota.startswith("---\ntipo: inspiración\nestado: semilla\nclase: critica\n---\n")
    assert "## Texto completo\n- [00:03] nadie llega solo\n" in nota and "inventada" not in nota
    assert nota.rstrip().endswith("## Notas de Remi\nLeer junto con Sandel.")  # lo agregado a mano se queda
    assert "(pendiente)" not in nota and "## Texto en pantalla" not in nota and "## Recursos" not in nota
    assert not material.exists() and not (carpeta / "2026-11-05-otro-meme.md").exists()
    assert clases.reclasificar(str(carpeta)) == {}  # ya todas tienen clase


def test_reclasificar_revisar_tras_agregar_una_clase(monkeypatch, tmp_path, carpeta):
    material = _pieza(tmp_path, "AAA", "Rareza")
    (material / "transcripcion.json").write_text(json.dumps([{"t": "00:01", "texto": "hola", "logprob": -0.1}]), "utf-8")
    b = json.loads((material / "reel.json").read_text("utf-8"))["bloques"]
    tabla = clases.cargar(carpeta)
    clases.archivar(b, "revisar", tabla, carpeta, "2026-11-09-cuenta-rareza.md")
    (carpeta / "2026-11-09-cuenta-paleta.md").write_text("---\nclase: diseno\n---\n# Paleta\n", "utf-8")
    vistos = _clasificador(monkeypatch, {"Rareza": "critica", "Paleta": "ruido"})

    assert clases.reclasificar(str(carpeta)) == {}  # sin --revisar, `revisar` ya cuenta como clase
    assert clases.reclasificar(str(carpeta), revisar=True) == {"critica": 1}
    assert vistos == ["Rareza. Algo. Account: @cuenta."]  # la de `diseno` no se toca
    nota = (carpeta / "2026-11-09-cuenta-rareza.md").read_text("utf-8")
    assert nota.startswith("---\ntipo: inspiración\nclase: critica\n---\n# Rareza\n")
    assert "Pregúntale a Remi" not in nota and "- Destino: [[AduSI]]" in nota
    assert "## Texto completo\n- [00:01] hola" in nota  # del material, que `revisar` conservaba
    assert not material.exists()  # `critica` no conserva


def test_nota_usada_borra_su_material(monkeypatch, tmp_path, carpeta):
    """Una nota de inspo que se usó en un proyecto se borra a mano; la cola borra su material y la marca `usado`."""
    monkeypatch.setattr(cola, "COLA", tmp_path / "cola")
    monkeypatch.setattr(cola, "ESTADO", tmp_path / "cola" / "cola.json")
    material = _pieza(tmp_path, "AAA", "Paleta")
    viva = _pieza(tmp_path, "BBB", "Otra")
    (carpeta / "b.md").write_text("# Otra", "utf-8")
    items = {"AAA": {"url": "u", "estado": "analizado", "material": str(material), "nota": str(carpeta / "a.md")},
             "BBB": {"url": "u", "estado": "analizado", "material": str(viva), "nota": str(carpeta / "b.md")}}
    cola._guardar({"items": items, "pausa_hasta": None, "motivo": None, "dia": None, "bajados_hoy": 0})

    (carpeta / clases.NOTA_CLASES).rename(tmp_path / "fuera.md")  # sin la nota de clases, ni se toca
    assert cola._consumidas(str(carpeta)) == 0 and material.exists()
    (tmp_path / "fuera.md").rename(carpeta / clases.NOTA_CLASES)

    assert cola.analizar(str(carpeta))["conteo"] == {"usado": 1, "analizado": 1}
    assert not material.exists() and viva.exists()

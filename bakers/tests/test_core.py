import json

import httpx
import pytest

from bakers import core


def respuesta(contenido: dict) -> dict:
    return {"model": "bonsai", "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            "choices": [{"message": {"content": json.dumps(contenido)}}]}


@pytest.fixture
def llama(monkeypatch, tmp_path):
    """Falso llama-swap: devuelve en orden las respuestas de la lista y guarda los cuerpos recibidos."""
    cola, recibidos = [], []

    def handler(req: httpx.Request) -> httpx.Response:
        recibidos.append(json.loads(req.content))
        return httpx.Response(200, json=respuesta(cola.pop(0)))

    monkeypatch.setattr(core, "_cliente", lambda timeout: httpx.Client(
        base_url="http://pixilate", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(core, "LOG", tmp_path / "log.jsonl")
    return cola, recibidos


def log(tmp_path) -> list[dict]:
    return [json.loads(l) for l in (tmp_path / "log.jsonl").read_text("utf-8").splitlines()]


def test_resumen_valida_y_registra(llama, tmp_path):
    cola, recibidos = llama
    archivo = tmp_path / "build.log"
    archivo.write_text("ok\nERROR: falta numpy\n", encoding="utf-8")
    cola.append({"resumen": "Falla el build", "puntos": ["falta numpy"], "alertas": []})

    res = core.bake("resumidor", "por qué falla", [str(archivo)])

    assert res["puntos"] == ["falta numpy"]
    assert "ERROR: falta numpy" in recibidos[0]["messages"][1]["content"]
    assert recibidos[0]["response_format"]["json_schema"]["name"] == "Resumen"
    (linea,) = log(tmp_path)
    assert linea | {"ts": None} == {"ts": None, "baker": "resumidor", "archivos": 1, "segundos": linea["segundos"],
                                    "ok": True, "error": None, "modelo": "bonsai", "entrada": 100, "salida": 10,
                                    "intentos": 1}


def test_reintenta_una_vez_y_luego_falla(llama, tmp_path):
    cola, _ = llama
    archivo = tmp_path / "a.txt"
    archivo.write_text("x", encoding="utf-8")
    cola.extend([{"resumen": "sin campos"}, {"otra": 1}])

    with pytest.raises(core.BakerError, match="fuera de esquema"):
        core.bake("resumidor", "t", [str(archivo)])
    assert log(tmp_path)[0]["intentos"] == 2
    assert log(tmp_path)[0]["ok"] is False


def test_clasificador_por_lotes_reintenta_si_falta_un_item(llama, tmp_path, monkeypatch):
    cola, recibidos = llama
    monkeypatch.setitem(core.BAKERS["clasificador"], "lote", 2)
    archivo = tmp_path / "issues.txt"
    archivo.write_text("bug en login\n\nidea: modo oscuro\ncrash al abrir\n", encoding="utf-8")
    cola.extend([
        {"items": [{"n": 1, "categoria": "bug"}]},  # le falta el 2: se reintenta
        {"items": [{"n": 1, "categoria": "bug"}, {"n": 2, "categoria": "idea"}]},
        {"items": [{"n": 1, "categoria": "bug"}]},
    ])

    res = core.bake("clasificador", "tipo de issue", [str(archivo)], ["bug", "idea"])

    assert res["conteo"] == {"bug": 2, "idea": 1}
    assert res["por_categoria"]["bug"][str(archivo)] == [1, 4]  # líneas reales, la vacía no cuenta
    assert res["por_categoria"]["idea"][str(archivo)] == [3]
    esquema = recibidos[0]["response_format"]["json_schema"]["schema"]
    assert esquema["$defs"]["Item"]["properties"]["categoria"]["enum"] == ["bug", "idea"]


def test_categoria_inventada_no_pasa(llama, tmp_path):
    cola, _ = llama
    archivo = tmp_path / "a.txt"
    archivo.write_text("algo\n", encoding="utf-8")
    cola.extend([{"items": [{"n": 1, "categoria": "otra"}]}] * 2)

    with pytest.raises(core.BakerError, match="fuera de esquema"):
        core.bake("clasificador", "t", [str(archivo)], ["bug", "idea"])


def test_rechaza_antes_de_llamar(llama, tmp_path, monkeypatch):
    _, recibidos = llama
    binario = tmp_path / "x.bin"
    binario.write_bytes(b"a\0b")
    grande = tmp_path / "grande.txt"
    grande.write_text("a" * 50, encoding="utf-8")
    monkeypatch.setattr(core, "MAX_CHARS", 40)

    with pytest.raises(core.BakerError, match="binario"):
        core.bake("resumidor", "t", [str(binario)])
    with pytest.raises(core.BakerError, match="tope"):
        core.bake("resumidor", "t", [str(grande)])
    with pytest.raises(core.BakerError, match="no es archivo"):
        core.bake("resumidor", "t", [str(tmp_path / "nada.txt")])
    with pytest.raises(core.BakerError, match="dos categorías"):
        core.bake("clasificador", "t", [str(grande)], ["solo"])
    assert recibidos == []

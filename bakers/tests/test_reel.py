import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from bakers import core, reel

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="pide ffmpeg")

NOTA = {"tema": "Prueba", "idea_central": "Un tono y barras de color.", "recursos": [
    {"nombre": "ffmpeg", "que_es": "genera el video", "donde": "pantalla"}],
    "citas": [{"t": "00:01", "texto": "hola"}], "texto_en_pantalla": [], "visual": "Barras.", "afirmaciones": []}


def test_video_local_a_nota(monkeypatch, tmp_path):
    video = tmp_path / "prueba.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=7",
                    "-f", "lavfi", "-i", "sine=duration=7", "-shortest", str(video)], check=True)
    rutas = []

    def handler(req: httpx.Request) -> httpx.Response:
        rutas.append(req.url.path)
        if req.url.path == "/api/profiles":
            return httpx.Response(200, json={"active": "alta", "profiles": []})
        if req.url.path == "/running":
            return httpx.Response(200, json={"running": []})
        if req.url.path == "/v1/audio/transcriptions":
            assert b'name="model"\r\n\r\nwhisper' in req.content
            return httpx.Response(200, json={"segments": [
                {"start": 0.0, "end": 1.0, "text": " I have a strong Hon", "avg_logprob": -5.6},
                {"start": 1.2, "end": 2.0, "text": " hola", "avg_logprob": -0.2},
                {"start": 2.0, "end": 2.5, "text": " hola", "avg_logprob": -0.1}]})
        cuerpo = json.loads(req.content)
        partes = cuerpo["messages"][1]["content"]
        assert "[00:01] hola" in partes[0]["text"] and "Hon" not in partes[0]["text"]
        assert partes[0]["text"].count("hola") == 1
        assert sum(p["type"] == "image_url" for p in partes) == 2  # 7 s / 3 s por fotograma
        return httpx.Response(200, json={"model": "vision", "usage": {"prompt_tokens": 900, "completion_tokens": 80},
                                         "choices": [{"message": {"content": json.dumps(NOTA)}}]})

    monkeypatch.setattr(core, "_cliente", lambda timeout: httpx.Client(
        base_url="http://pixilate", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(core, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(reel, "CARPETA", tmp_path / "reels")

    (res,) = reel.reel([str(video)], str(tmp_path / "inspiracion"))
    assert res["recursos"][0]["nombre"] == "ffmpeg"
    assert Path(res["nota"]).name.endswith("-local-prueba.md") and Path(res["nota"]).parent.name == "inspiracion"
    nota = Path(res["nota"]).read_text("utf-8")
    assert nota == (tmp_path / "reels" / "prueba" / "nota.md").read_text("utf-8")
    assert '- [00:01] "hola"' in nota and "| ffmpeg | genera el video | pantalla | no |" in nota
    assert rutas[-1] == "/v1/chat/completions"
    linea = json.loads((tmp_path / "log.jsonl").read_text("utf-8"))
    assert linea["entrada"] == 900 and set(linea["pasos"]) == {"descarga", "whisper", "fotogramas", "vision"}


def test_fuente_invalida_no_detiene_el_lote(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "estado", lambda: {"marcha": "alta"})
    monkeypatch.setattr(core, "_cliente", lambda timeout: httpx.Client(base_url="http://pixilate"))
    monkeypatch.setattr(core, "LOG", tmp_path / "log.jsonl")
    res = reel.reel(["no-existe.mp4", "tampoco"])
    assert all("Ni archivo ni enlace" in r["error"] for r in res)


def test_bake_rechaza_reel():
    with pytest.raises(core.BakerError, match="herramienta reel"):
        core.bake("reel", "t", ["x"])


def test_destino_con_padre_inexistente(monkeypatch, tmp_path):
    with pytest.raises(core.BakerError, match="revisa el destino"):
        reel.reel(["x"], str(tmp_path / "no" / "existe"))


def test_quita_subtitulos_quemados():
    segmentos = [{"t": "00:01", "texto": "Hay presión en el gobierno"}]
    pantalla = ["presion, el gobierno", "¡LA GEN Z ESTÁ IMPARABLE!"]
    assert reel._sin_subtitulos(pantalla, segmentos) == ["¡LA GEN Z ESTÁ IMPARABLE!"]

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
    with pytest.raises(core.BakerError, match="propia herramienta"):
        core.bake("reel", "t", ["x"])


def test_destino_con_padre_inexistente(monkeypatch, tmp_path):
    with pytest.raises(core.BakerError, match="revisa el destino"):
        reel.reel(["x"], str(tmp_path / "no" / "existe"))


def test_quita_subtitulos_quemados():
    segmentos = [{"t": "00:01", "texto": "Hay presión en el gobierno"}]
    pantalla = ["presion, el gobierno", "¡LA GEN Z ESTÁ IMPARABLE!"]
    assert reel._sin_subtitulos(pantalla, segmentos) == ["¡LA GEN Z ESTÁ IMPARABLE!"]


def test_post_de_fotos_pasa_a_gallery_dl(monkeypatch, tmp_path):
    """yt-dlp no baja fotos; gallery-dl sí, a una carpeta `.part` que solo se renombra al terminar."""
    monkeypatch.setattr(reel, "CARPETA", tmp_path / "reels")
    (tmp_path / "reels").mkdir()
    llamadas = []

    def correr(*args, cwd=None):
        llamadas.append(args[0])
        if args[0] == "yt-dlp":
            raise core.BakerError("yt-dlp falló (1): ERROR: [Instagram] AAA: No video formats found!")
        destino = Path(args[args.index("-D") + 1])
        assert destino.name == "AAA.part"
        destino.mkdir()
        (destino / "info.json").write_text('{"username": "alguien", "description": "Tres pasos", '
                                           '"post_url": "https://www.instagram.com/p/AAA/"}')
        for n in ("01.jpg", "02.webp", "00.mp3"):
            (destino / n).write_bytes(b"x")
        return ""

    monkeypatch.setattr(reel, "_correr", correr)
    carpeta, meta = reel._obtener("https://www.instagram.com/p/AAA/", "firefox")
    assert carpeta == tmp_path / "reels" / "AAA" and reel.bajado("AAA") == carpeta
    assert [m.name for m in reel._medios(carpeta)] == ["01.jpg", "02.webp"]  # la música no cuenta
    assert meta["channel"] == "alguien" and meta["description"] == "Tres pasos"
    assert llamadas == ["yt-dlp", "gallery-dl"]
    assert reel._obtener("https://www.instagram.com/p/AAA/", "firefox")[0] == carpeta and len(llamadas) == 2


def test_galeria_cortada_no_cuenta(monkeypatch, tmp_path):
    monkeypatch.setattr(reel, "CARPETA", tmp_path)
    (tmp_path / "AAA.part").mkdir()
    (tmp_path / "AAA.part" / "info.json").write_text("{}")
    assert reel.bajado("AAA") is None


def test_carrusel_a_nota_sin_whisper(monkeypatch, tmp_path):
    carpeta = tmp_path / "reels" / "g-123"
    carpeta.mkdir(parents=True)
    (carpeta / "info.json").write_text('{"user": "alguien", "desc": "Paleta de otoño"}', "utf-8")
    for k in range(1, 11):  # 10 fotos: van 8, con la primera y la última
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x400",
                        "-frames:v", "1", str(carpeta / f"{k:02d}.jpg")], check=True)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/profiles":
            return httpx.Response(200, json={"active": "alta", "profiles": []})
        if req.url.path == "/running":
            return httpx.Response(200, json={"running": []})
        assert req.url.path == "/v1/chat/completions"  # nada de whisper
        partes = json.loads(req.content)["messages"][1]["content"]
        assert "10 slides" in partes[0]["text"] and "Account: alguien" in partes[0]["text"]
        etiquetas = [p["text"] for p in partes[1:] if p["type"] == "text"]
        assert len(etiquetas) == 8 and etiquetas[0] == "[1/10]" and etiquetas[-1] == "[10/10]"
        return httpx.Response(200, json={"model": "vision", "usage": {"prompt_tokens": 9, "completion_tokens": 8},
                                         "choices": [{"message": {"content": json.dumps(NOTA)}}]})

    monkeypatch.setattr(core, "_cliente", lambda timeout: httpx.Client(
        base_url="http://pixilate", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(core, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(reel, "CARPETA", tmp_path / "reels")
    (res,) = reel.reel([str(carpeta)])
    nota = Path(res["nota"]).read_text("utf-8")
    assert Path(res["nota"]) == carpeta / "nota.md" and "- Formato: carrusel, 10 piezas" in nota
    assert res["citas"] == [] and res["transcripcion"] is None  # sin habla no hay citas

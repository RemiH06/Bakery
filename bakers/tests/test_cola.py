from datetime import datetime, timedelta, timezone

import pytest

from bakers import cola, core, reel
from bakers.core import BakerError

TZ = timezone(timedelta(hours=-6))


@pytest.fixture
def reloj(monkeypatch, tmp_path):
    """Cola y reels en tmp_path; dormir solo adelanta un reloj falso (empieza a las 10:00)."""
    ahora = [datetime(2026, 10, 28, 10, 0, tzinfo=TZ)]
    dormidas = []
    monkeypatch.setattr(cola, "COLA", tmp_path / "cola")
    monkeypatch.setattr(cola, "ESTADO", tmp_path / "cola" / "cola.json")
    monkeypatch.setattr(cola, "ERRORES", tmp_path / "cola" / "errores.jsonl")
    monkeypatch.setattr(reel, "CARPETA", tmp_path / "reels")
    monkeypatch.setattr(cola, "_ahora", lambda: ahora[0])

    def dormir(t):
        dormidas.append((t - ahora[0]).total_seconds())
        ahora[0] = max(ahora[0], t)

    monkeypatch.setattr(cola, "_dormir_hasta", dormir)
    return ahora, dormidas


def _descargas(monkeypatch, tmp_path, fallos: dict):
    """Simula yt-dlp: `fallos` da, por código, la lista de errores que suelta antes de bajar bien."""
    llamadas = []

    def obtener(url, navegador):
        clave = reel.codigo(url)
        llamadas.append(clave)
        if fallos.get(clave):
            raise BakerError(fallos[clave].pop(0))
        carpeta = tmp_path / "reels" / clave
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "video.info.json").write_text("{}")
        (carpeta / "video.mp4").write_bytes(b"x")
        return carpeta / "video.mp4", {}

    monkeypatch.setattr(reel, "_obtener", obtener)
    return llamadas


def _enlaces(tmp_path, *lineas):
    f = tmp_path / "links.txt"
    f.write_text("\n".join(lineas), "utf-8")
    return str(f)


def test_agregar_limpia_y_no_repite(reloj, tmp_path):
    ya = tmp_path / "reels" / "YA"
    ya.mkdir(parents=True)
    (ya / "video.info.json").write_text("{}")
    (ya / "video.mp4").write_bytes(b"x")
    res = cola.agregar(_enlaces(tmp_path,
                                "https://www.instagram.com/reel/AAA/?stkn=MXc5",
                                "# Proyecto",
                                "Osiris: https://www.instagram.com/reels/BBB/",
                                "https://www.instagram.com/reel/AAA/?igsh=otro",
                                "https://www.instagram.com/p/CCC/?img_index=1",
                                "https://www.instagram.com/reel/YA/",
                                "Es tibio decir todxs", ""))
    assert res == {"agregados": 3, "repetidos": 1, "ya_bajados": 1, "sin_enlace": 1, "en_cola": 3}
    items = cola._leer()["items"]
    assert items["AAA"]["url"] == "https://www.instagram.com/reel/AAA/"
    assert items["BBB"]["etiqueta"] == "Osiris" and items["BBB"]["seccion"] == "Proyecto"
    assert items["AAA"]["seccion"] is None
    assert items["CCC"]["url"] == "https://www.instagram.com/p/CCC/"


def test_parcial_no_cuenta_como_bajado(reloj, tmp_path):
    c = tmp_path / "reels" / "AAA"
    c.mkdir(parents=True)
    (c / "video.info.json").write_text("{}")
    (c / "video.mp4.part").write_bytes(b"x")
    assert reel.bajado("AAA") is None


def test_bloqueo_pausa_y_enlace_roto_sigue(monkeypatch, reloj, tmp_path):
    ahora, dormidas = reloj
    llamadas = _descargas(monkeypatch, tmp_path, {
        "BBB": ["yt-dlp falló (1): ERROR: [Instagram] BBB: HTTP Error 429: Too Many Requests"],
        "CCC": ["yt-dlp falló (1): ERROR: [Instagram] CCC: This content isn't available"]})
    cola.agregar(_enlaces(tmp_path, *(f"https://www.instagram.com/reel/{c}/" for c in ("AAA", "BBB", "CCC"))))
    res = cola.bajar()
    assert res["conteo"] == {"bajado": 2, "fallido": 1} and "CCC" in res["fallidos"]
    # AAA, BBB (429), luego CCC antes que reintentar BBB, y BBB al final
    assert llamadas == ["AAA", "BBB", "CCC", "BBB"]
    assert any(2 * 3600 <= d <= 3 * 3600 for d in dormidas)  # la pausa de bloqueo
    assert all(d >= 60 for d in dormidas)
    errores = cola.ERRORES.read_text("utf-8").splitlines()
    assert len(errores) == 2 and '"tipo": "bloqueo"' in errores[0] and '"tipo": "enlace"' in errores[1]


def test_json_vacio_es_bloqueo_y_enlace_roto_espera(monkeypatch, reloj, tmp_path):
    # 2026-10-28: Instagram devolvió páginas vacías y la cola marcó 283 enlaces seguidos sin pausa
    _, dormidas = reloj
    llamadas = _descargas(monkeypatch, tmp_path, {
        "AAA": ["yt-dlp falló (1): ERROR: [Instagram] AAA: This content isn't available"],
        "BBB": ['yt-dlp falló (1): ERROR: [Instagram] BBB: Failed to parse JSON (caused by '
                'JSONDecodeError("Expecting value in \'\': line 1 column 1 (char 0)"))']})
    cola.agregar(_enlaces(tmp_path, *(f"https://www.instagram.com/reel/{c}/" for c in ("AAA", "BBB"))))
    res = cola.bajar()
    assert res["conteo"] == {"bajado": 1, "fallido": 1} and "AAA" in res["fallidos"]
    assert llamadas == ["AAA", "BBB", "BBB"]
    assert 60 <= dormidas[0] <= 240                  # tras el enlace roto
    assert 2 * 3600 <= dormidas[1] <= 3 * 3600       # tras el JSON vacío


def test_tres_bloqueos_marcan_el_enlace(monkeypatch, reloj, tmp_path):
    _descargas(monkeypatch, tmp_path, {"AAA": ["login required"] * 3})
    cola.agregar(_enlaces(tmp_path, "https://www.instagram.com/reel/AAA/"))
    assert cola.bajar()["conteo"] == {"fallido": 1}


def test_sin_red_no_cuenta_intento(monkeypatch, reloj, tmp_path):
    _, dormidas = reloj
    _descargas(monkeypatch, tmp_path, {"AAA": ["<urlopen error [Errno 11001] getaddrinfo failed>"] * 5})
    cola.agregar(_enlaces(tmp_path, "https://www.instagram.com/reel/AAA/"))
    assert cola.bajar()["conteo"] == {"bajado": 1}
    assert dormidas[:5] == [cola.RED] * 5


def test_reanuda_tras_matarlo(monkeypatch, reloj, tmp_path):
    llamadas = _descargas(monkeypatch, tmp_path, {})
    cola.agregar(_enlaces(tmp_path, *(f"https://www.instagram.com/reel/{c}/" for c in ("AAA", "BBB", "CCC"))))
    original = reel._obtener

    def muere_en_bbb(url, navegador):
        if reel.codigo(url) == "BBB":
            raise KeyboardInterrupt  # como cerrar la terminal a media descarga
        return original(url, navegador)

    monkeypatch.setattr(reel, "_obtener", muere_en_bbb)
    with pytest.raises(KeyboardInterrupt):
        cola.bajar()
    assert cola.estado()["conteo"] == {"bajado": 1, "pendiente": 2}
    monkeypatch.setattr(reel, "_obtener", original)
    cola.bajar()
    assert llamadas == ["AAA", "BBB", "CCC"]  # AAA no se vuelve a bajar


def test_tope_espera_al_dia_siguiente(monkeypatch, reloj, tmp_path):
    ahora, _ = reloj
    _descargas(monkeypatch, tmp_path, {})
    cola.agregar(_enlaces(tmp_path, "https://www.instagram.com/reel/AAA/", "https://www.instagram.com/reel/BBB/"))
    cola.bajar(tope=1)
    assert ahora[0].date().isoformat() == "2026-10-29" and 9 <= ahora[0].hour < 10


def test_un_solo_bajar_a_la_vez(reloj):
    with cola._candado():
        with pytest.raises(BakerError, match="corriendo"):
            with cola._candado():
                pass


def test_analizar_espera_marcha_y_no_baja(monkeypatch, reloj, tmp_path):
    _descargas(monkeypatch, tmp_path, {})
    cola.agregar(_enlaces(tmp_path, *(f"https://www.instagram.com/reel/{c}/" for c in ("AAA", "BBB", "CCC"))))
    cola.bajar()
    marchas = iter(["media", "alta", "alta"])
    monkeypatch.setattr(core, "estado", lambda: {"marcha": next(marchas)})
    esperas = []
    monkeypatch.setattr(cola.time, "sleep", esperas.append)
    lotes = []

    def reel_falso(fuentes, destino, modelo):
        assert modelo == "vision-abliterado"
        lotes.append(fuentes)
        return [{"fuente": f, "error": "bucle"} if "BBB" in f else {"fuente": f, "nota": f"{destino}/{f[-4:-1]}.md"}
                for f in fuentes]

    monkeypatch.setattr(reel, "reel", reel_falso)
    monkeypatch.setattr(reel, "_obtener", lambda *a: pytest.fail("analizar no debe descargar"))
    res = cola.analizar(str(tmp_path / "notas"), lote=2, modelo="vision-abliterado")
    assert esperas == [300]
    assert lotes[0] == ["https://www.instagram.com/reel/AAA/", "https://www.instagram.com/reel/BBB/"]
    assert res["conteo"] == {"analizado": 2, "fallido": 1}  # BBB falló dos veces

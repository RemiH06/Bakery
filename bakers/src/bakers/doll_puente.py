"""Puente del panel a Doll (`30.Doll`): `buscar` y `preguntar` en JSON. No es parte del paquete `bakers`: corre con el
Python del entorno de Doll (`--doll` del panel), porque Doll depende de `bakers` y el panel no puede importarlo sin
volverlo circular. Solo usa la API de Doll que también usan su CLI y su MCP.

    <python de Doll> -I doll_puente.py buscar <corpus> <consulta> [k]
    <python de Doll> -I doll_puente.py preguntar <corpus> <consulta> [k]
"""
import json
import sys

from doll import corpus as corpus_mod
from doll import indice
from doll.preguntar import preguntar


def _fragmento(f, corpus) -> dict:
    return {"ruta": f.ruta, "encabezado": f.encabezado, "linea_ini": f.linea_ini, "linea_fin": f.linea_fin,
            "texto": f.texto, "terceros": corpus.es_terceros(f.ruta)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    modo, nombre, consulta, *resto = sys.argv[1:]
    k = int(resto[0]) if resto else 10
    corpus = corpus_mod.cargar(nombre)
    con = indice.abrir(corpus_mod.home() / f"{nombre}.db")
    indice.indexar(con, corpus)  # solo reprocesa las notas que cambiaron
    if modo == "buscar":
        res = {"fragmentos": [_fragmento(f, corpus) for f in indice.buscar(con, consulta, k)]}
    elif modo == "preguntar":
        r = preguntar(con, corpus, consulta, k)
        res = {"respuesta": r.texto, "no_encontrado": r.no_encontrado, "fallo": r.fallo,
               "citas_descartadas": r.citas_descartadas,
               "citas": [{"texto": c.texto, "ruta": c.ruta, "linea_ini": c.linea_ini, "linea_fin": c.linea_fin}
                         for c in r.citas],
               "fragmentos": [_fragmento(f, corpus) for f in r.fragmentos] if r.fallo else []}
    else:
        raise SystemExit(f"modo desconocido: {modo}")
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()

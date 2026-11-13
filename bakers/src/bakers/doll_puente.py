"""Puente del panel a Doll (`30.Doll`): floppies, `buscar` y `preguntar` en JSON. No es parte del paquete `bakers`:
corre con el Python del entorno de Doll (`--doll` del panel), porque Doll depende de `bakers` y el panel no puede
importarlo sin volverlo circular. Solo usa la API de Doll que también usan su CLI y su MCP.

    <python de Doll> -I doll_puente.py floppies
    <python de Doll> -I doll_puente.py buscar <floppy> <consulta> [k]
    <python de Doll> -I doll_puente.py preguntar <floppy> <consulta> [k]

`<floppy>` vacío es el montado en la máquina del panel. Se elige por consulta y nunca se monta: montar cambiaría el
floppy de todo lo que corre ahí. El panel muestra rutas, así que oculta `mcp_excluir` igual que el MCP, y se niega
con un floppy que no lo define.
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
    modo, *resto = sys.argv[1:]
    if modo == "floppies":
        try:
            montado = corpus_mod.montado()
        except SystemExit:
            montado = None
        print(json.dumps({"floppies": corpus_mod.disponibles(), "montado": montado}, ensure_ascii=False))
        return
    floppy, consulta, *resto = resto
    k = int(resto[0]) if resto else 10
    corpus = corpus_mod.cargar(floppy or None)
    if corpus.mcp_excluir is None:
        raise SystemExit(f"Define mcp_excluir en el floppy {corpus.nombre!r}; `mcp_excluir = []` si nada debe quedar fuera")
    filtro = indice.Filtro(ocultar=corpus.mcp_excluir)  # los mismos filtros que el MCP de Doll
    con = indice.abrir(corpus.indice)
    indice.indexar(con, corpus)  # solo reprocesa las notas que cambiaron
    if modo == "buscar":
        # Por sentido solo hay vectores de las notas de terceros: en un floppy con notas propias, por palabras
        if "**" in corpus.terceros:
            from doll import sentido

            fragmentos, aviso = sentido.buscar(con, corpus, consulta, k, filtro)
            como = "palabras" if aviso else "sentido"
        else:
            filtro = indice.Filtro(ocultar=corpus.mcp_excluir, terceros=corpus.terceros)
            fragmentos, como = indice.buscar(con, consulta, k, filtro), "palabras"
        res = {"floppy": corpus.nombre, "como": como, "fragmentos": [_fragmento(f, corpus) for f in fragmentos]}
    elif modo == "preguntar":
        r = preguntar(con, corpus, consulta, k, filtro=filtro)
        res = {"floppy": corpus.nombre, "respuesta": r.texto, "no_encontrado": r.no_encontrado, "fallo": r.fallo,
               "citas_descartadas": r.citas_descartadas, "intentos": r.intentos, "leidos": len(r.fragmentos),
               "faltan": r.faltan,
               "citas": [{"texto": c.texto, "ruta": c.ruta, "linea_ini": c.linea_ini, "linea_fin": c.linea_fin}
                         for c in r.citas],
               "fragmentos": [_fragmento(f, corpus) for f in r.fragmentos] if r.fallo else []}
    else:
        raise SystemExit(f"modo desconocido: {modo}")
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""CLI `baker` para Remi: misma lógica que el MCP."""
import argparse
import json
import sys

from . import cola, core, reel


def main() -> None:
    ap = argparse.ArgumentParser(prog="baker", description="Llama a un Baker de Pixilate.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="manda archivos a un Baker")
    run.add_argument("baker", choices=sorted(n for n, cfg in core.BAKERS.items() if cfg["esquema"] != "reel"))
    run.add_argument("-f", "--file", dest="rutas", action="append", required=True, help="repetible")
    run.add_argument("-t", "--tarea", required=True, help="qué debe sacar de los archivos")
    run.add_argument("-c", "--categoria", dest="categorias", action="append", help="clasificador; repetible")
    rr = sub.add_parser("reel", help="reels o videos cortos a nota de inspiración")
    rr.add_argument("fuentes", nargs="+", help="enlaces o rutas de video")
    rr.add_argument("-d", "--destino", help="carpeta de notas del proyecto (por defecto, junto al material)")
    cl = sub.add_parser("cola", help="descargas de reels en cola: bajar despacio, analizar después")
    cs = cl.add_subparsers(dest="accion", required=True)
    cs.add_parser("agregar", help="enlaces de un archivo, uno por renglón").add_argument("archivo")
    cs.add_parser("bajar", help="solo descarga, días seguidos").add_argument(
        "--tope", type=int, default=cola.TOPE, help=f"descargas por día (por defecto {cola.TOPE})")
    ca = cs.add_parser("analizar", help="corre `reel` sobre lo ya bajado, sin tocar Instagram")
    ca.add_argument("-d", "--destino", required=True, help="carpeta de notas del proyecto")
    ca.add_argument("--lote", type=int, default=cola.LOTE)
    cs.add_parser("estado", help="bajados, pendientes, fallidos y próximo intento")
    sub.add_parser("status", help="qué modelo atiende cada Baker y cuál está cargado")
    sys.stdout.reconfigure(encoding="utf-8")  # antes de parsear: la ayuda también lleva acentos
    sys.stderr.reconfigure(encoding="utf-8")
    a = ap.parse_args()
    try:
        if a.cmd == "run":
            res = core.bake(a.baker, a.tarea, a.rutas, a.categorias)
        elif a.cmd == "reel":
            res = reel.reel(a.fuentes, a.destino)
        elif a.cmd == "cola":
            res = {"agregar": lambda: cola.agregar(a.archivo), "bajar": lambda: cola.bajar(a.tope),
                   "analizar": lambda: cola.analizar(a.destino, a.lote), "estado": cola.estado}[a.accion]()
        else:
            res = core.estado()
    except core.BakerError as e:
        sys.exit(f"baker: {e}")
    print(json.dumps(res, ensure_ascii=False, indent=2))

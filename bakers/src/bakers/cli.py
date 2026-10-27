"""CLI `baker` para Remi: misma lógica que el MCP."""
import argparse
import json
import sys

from . import core


def main() -> None:
    ap = argparse.ArgumentParser(prog="baker", description="Llama a un Baker de Pixilate.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="manda archivos a un Baker")
    run.add_argument("baker", choices=sorted(core.BAKERS))
    run.add_argument("-f", "--file", dest="rutas", action="append", required=True, help="repetible")
    run.add_argument("-t", "--tarea", required=True, help="qué debe sacar de los archivos")
    run.add_argument("-c", "--categoria", dest="categorias", action="append", help="clasificador; repetible")
    sub.add_parser("status", help="qué modelo atiende cada Baker y cuál está cargado")
    a = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        res = core.bake(a.baker, a.tarea, a.rutas, a.categorias) if a.cmd == "run" else core.estado()
    except core.BakerError as e:
        sys.exit(f"baker: {e}")
    print(json.dumps(res, ensure_ascii=False, indent=2))

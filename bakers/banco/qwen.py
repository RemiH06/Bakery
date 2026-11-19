"""Banco de Qwen Code como programador supervisado (1.15): cada caso es una tarea cerrada sobre un repo de
iroFactory, con su especificación, sus pruebas y un commit de referencia (ver casos_qwen.toml).

    uv run python banco/qwen.py [caso ...] [--modelo abliterado] [--vueltas 1] [--referencia] [--conservar]

Por caso: worktree del repo en el padre del commit de referencia, con las pruebas del commit ya puestas (son
la especificación), `uv sync`, la verificación en rojo, Qwen Code sin interfaz con lista blanca de herramientas
y tope de tiempo, y la verificación otra vez. `--referencia` aplica el commit en vez de llamar a Qwen: valida
un caso nuevo (rojo antes, verde después) sin gastar GPU.

Guarda en ~/.bakers/banco-qwen/<fecha-hora>/<caso>-<vuelta>/: diff.patch, verificacion.txt, eventos.jsonl de
Qwen y resultado.json; una línea por corrida en resultados.jsonl. Qwen usa su ~/.qwen/settings.json (BAKERS_API_KEY).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path

from bakers import core

IROFACTORY = Path(__file__).resolve().parents[3]  # banco -> bakers -> 29.Bakery -> iroFactory
CASOS = Path(__file__).with_name("casos_qwen.toml")
SALIDA = Path.home() / ".bakers" / "banco-qwen"
TOPE_QWEN = "30m"          # como el A/B de 1.0o
# Versión del texto que arma `_prompt`, para comparar tandas. 1: solo la tarea (2026-11-18, primera tanda).
# 2: además nombra las skills a cargar y prohíbe `cd`, que la lista blanca niega (36 de 46 negados en la 1).
ENCARGO = 2
TOPE_VERIFICAR = 900       # segundos; cada caso corre solo su archivo de pruebas
VIGIA = 15                 # segundos entre consultas a /running mientras trabaja Qwen
# Sin `git log` ni `git show`: los commits de referencia están en el repo y serían la respuesta.
PERMITIDAS = ["read_file", "edit", "write_file", "glob", "grep_search", "list_directory", "skill", "todo_write",
              "run_shell_command(uv run pytest)", "run_shell_command(uv run python -m pytest)",
              "run_shell_command(uv run python -m unittest)", "run_shell_command(git status)",
              "run_shell_command(git diff)"]
# Fuera del prompt: red, memoria, subagentes, preguntas (sin interfaz nadie contesta) y lo que no aplica.
EXCLUIDAS = ["web_fetch", "web_search", "save_memory", "manage_memory", "search_memory", "agent", "ask_user_question",
             "image_gen", "zoom_image", "cron_create", "cron_list", "cron_delete", "loop_wakeup", "autofix_pr",
             "list_agents", "send_message", "task_stop", "enter_worktree", "exit_worktree", "read_mcp_resource",
             "notebook_edit"]
# Lo que no debe entrar a un repo público (regla de qwen-bakery), buscado en los renglones que agrega el diff
ALERTAS = re.compile(r"ts\.net|\b\d{1,3}(?:\.\d{1,3}){3}\b|C:\\Users|\u2014")
FUERA_DEL_DIFF = [":(exclude,glob)**/.venv/**", ":(exclude,glob)**/.qwen/**"]
# Sin el VIRTUAL_ENV de este `uv run`: en el worktree, uv avisaría en cada comando que no coincide
ENTORNO = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def _verificar(caso: dict, cwd: Path) -> tuple[bool, str]:
    try:
        p = subprocess.run(caso["verificar"], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TOPE_VERIFICAR, env=ENTORNO)
    except subprocess.TimeoutExpired:
        return False, f"sin terminar en {TOPE_VERIFICAR} s"
    return p.returncode == 0, (p.stdout + p.stderr)[-4000:]


def _limpiar(caso: dict, wt: Path) -> None:
    repo = IROFACTORY / caso["repo"]
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)], capture_output=True)
    shutil.rmtree(wt, ignore_errors=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True)


def _preparar(caso: dict, wt: Path) -> tuple[Path, str]:
    """Worktree en el padre del commit con las pruebas del commit puestas. Devuelve el proyecto y el árbol base."""
    repo = IROFACTORY / caso["repo"]
    _limpiar(caso, wt)  # uno que quedó de una corrida cortada
    _git(repo, "worktree", "add", "--detach", str(wt), f"{caso['commit']}^")
    _git(wt, "checkout", caso["commit"], "--", *caso["pruebas"])
    proyecto = wt / caso.get("proyecto", ".")
    subprocess.run(["uv", "sync", "--quiet"], cwd=proyecto, check=True, capture_output=True, env=ENTORNO)
    # Las pruebas quedan en el índice: el `git diff` que vea Qwen es solo su trabajo
    _git(wt, "add", "-A", "--", ".", *FUERA_DEL_DIFF)
    return proyecto, _git(wt, "write-tree").strip()


def _prompt(caso: dict) -> str:
    base = caso.get("proyecto", ".")
    pruebas = ", ".join(f"`{Path(p).relative_to(base).as_posix()}`" for p in caso["pruebas"])
    skills = ["qwen-flujo", "qwen-ponytail", "qwen-python"] + (["qwen-bakery"] if caso["repo"] == "29.Bakery" else [])
    return (f"{caso['tarea'].strip()}\n\n"
            f"Before anything else, load these skills: {', '.join(skills)}.\n"
            "Commands already run in this folder: never prefix them with `cd`, `--directory` or `git -C`.\n"
            f"Verification (run it from this folder): `{' '.join(caso['verificar'])}`\n"
            f"The tests in {pruebas} are already written and are the spec: do not edit them.\n"
            "Work only inside this folder. Do not commit.")


class _Vigia(threading.Thread):
    """Mira qué modelos tiene cargados llama-swap mientras corre Qwen. Si otro cliente pide un modelo distinto,
    llama-swap los alterna y Qwen pierde su caché de prompt (2026-11-18: corridas 5 veces más lentas por eso);
    la corrida queda marcada en vez de contarse como lentitud de Qwen."""

    def __init__(self, modelo: str):
        super().__init__(daemon=True)
        self.modelo, self.alto, self.otros, self.fuera, self.fallas = modelo, threading.Event(), set(), 0, 0

    def run(self) -> None:
        with core._cliente(timeout=10) as c:
            while not self.alto.wait(VIGIA):
                try:
                    cargados = {m["model"] for m in c.get("/running").json()["running"]}
                except Exception:  # noqa: BLE001  una consulta perdida no invalida la corrida
                    self.fallas += 1
                    continue
                self.otros |= cargados - {self.modelo}
                self.fuera += self.modelo not in cargados


def _qwen(caso: dict, proyecto: Path, modelo: str, carpeta: Path) -> dict:
    cli = Path(subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, shell=os.name == "nt",
                              check=True).stdout.strip()) / "@qwen-code" / "qwen-code" / "cli.js"
    # node directo y no el `qwen.cmd`: cmd.exe rompe un prompt de varios renglones con comillas
    argv = ["node", str(cli), "-m", modelo, "-o", "stream-json", "--approval-mode", "default",
            "--allowed-tools", *PERMITIDAS, "--exclude-tools", *EXCLUIDAS, "--max-wall-time", TOPE_QWEN,
            "--chat-recording", "false", _prompt(caso)]
    inicio, vigia = time.monotonic(), _Vigia(modelo)
    vigia.start()
    with open(carpeta / "eventos.jsonl", "w", encoding="utf-8") as eventos:
        try:
            p = subprocess.run(argv, cwd=proyecto, stdout=eventos, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", timeout=35 * 60, env=ENTORNO)
            codigo, error = p.returncode, p.stderr[-2000:]
        except subprocess.TimeoutExpired:
            codigo, error = None, "el proceso pasó de 35 min"
        finally:
            vigia.alto.set()
            vigia.join()
    return {"codigo": codigo, "segundos": round(time.monotonic() - inicio), "stderr": error,
            "otros_modelos": sorted(vigia.otros), "consultas_sin_modelo": vigia.fuera,
            "consultas_fallidas": vigia.fallas,
            **_leer_eventos(carpeta / "eventos.jsonl")}


def _leer_eventos(ruta: Path) -> dict:
    llamadas, errores, skills, final = [], 0, [], {}
    for linea in ruta.read_text("utf-8").splitlines():
        try:
            ev = json.loads(linea)
        except json.JSONDecodeError:
            continue
        for b in ev.get("message", {}).get("content", []) if isinstance(ev.get("message"), dict) else []:
            if b.get("type") == "tool_use":
                llamadas.append(b["name"])
                if b["name"] == "skill":
                    skills.append(str(b.get("input", {}).get("skill") or b.get("input")))
            elif b.get("type") == "tool_result" and b.get("is_error"):
                errores += 1
        if ev.get("type") == "result":
            final = ev
    negadas = [d.get("tool_input", {}).get("command") or d.get("tool_name") for d in final.get("permission_denials", [])]
    return {"turnos": final.get("num_turns"), "llamadas": len(llamadas), "errores_herramienta": errores,
            "negadas": negadas, "skills": skills, "tokens_entrada": final.get("usage", {}).get("input_tokens"),
            "tokens_salida": final.get("usage", {}).get("output_tokens"), "reporte": final.get("result")}


def correr(caso: dict, modelo: str, referencia: bool, carpeta: Path, conservar: bool) -> dict:
    carpeta.mkdir(parents=True)
    wt = SALIDA / "wt" / caso["id"]
    try:
        return _correr(caso, modelo, referencia, carpeta, wt)
    finally:
        if not conservar:  # también si git o Qwen fallaron: un worktree colgado tumba al caso siguiente del repo
            _limpiar(caso, wt)


def _correr(caso: dict, modelo: str, referencia: bool, carpeta: Path, wt: Path) -> dict:
    proyecto, base = _preparar(caso, wt)
    pasaba, salida_antes = _verificar(caso, proyecto)
    if referencia:
        repo = IROFACTORY / caso["repo"]
        cambiados = _git(repo, "diff", "--name-only", "--diff-filter=d", f"{caso['commit']}^", caso["commit"]).split()
        _git(wt, "checkout", caso["commit"], "--", *cambiados)
        qwen = {"segundos": 0}
    else:
        qwen = _qwen(caso, proyecto, modelo, carpeta)
    _git(wt, "add", "-A", "--", ".", *FUERA_DEL_DIFF)
    diff = _git(wt, "diff", "--cached", base)
    (carpeta / "diff.patch").write_text(diff, "utf-8")
    ok, salida = _verificar(caso, proyecto)
    (carpeta / "verificacion.txt").write_text(f"ANTES ({'pasa' if pasaba else 'falla'})\n{salida_antes}\n\n"
                                              f"DESPUÉS ({'pasa' if ok else 'falla'})\n{salida}", "utf-8")
    tocadas = [p for p in caso["pruebas"] if _git(wt, "diff", "--cached", base, "--", p).strip()]
    agregados = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    resultado = {
        "caso": caso["id"], "modelo": "referencia" if referencia else modelo, "encargo": ENCARGO,
        "ok": ok and not tocadas,
        "verde": ok, "rojo_antes": not pasaba, "tocó_pruebas": tocadas,
        "archivos": _git(wt, "diff", "--cached", "--name-only", base).split(),
        "renglones": sum(1 for l in diff.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")),
        "alertas": sorted({m.group() for l in agregados for m in ALERTAS.finditer(l)}),
        "ultima_linea": salida.strip().splitlines()[-1] if salida.strip() else "",
        **qwen,
    }
    (carpeta / "resultado.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), "utf-8")
    return resultado


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("casos", nargs="*", help="ids de casos_qwen.toml; sin ids, todos")
    ap.add_argument("--modelo", default="abliterado")
    ap.add_argument("--vueltas", type=int, default=1)
    ap.add_argument("--referencia", action="store_true", help="aplica el commit en vez de llamar a Qwen")
    ap.add_argument("--conservar", action="store_true", help="deja el worktree para revisarlo")
    a = ap.parse_args()
    todos = {c["id"]: c for c in tomllib.loads(CASOS.read_text("utf-8"))["caso"]}
    if desconocidos := set(a.casos) - set(todos):
        raise SystemExit(f"Casos que no existen: {', '.join(sorted(desconocidos))}")
    corrida = SALIDA / datetime.now().strftime("%Y-%m-%d-%H%M")
    for vuelta in range(1, a.vueltas + 1):
        for cid in a.casos or todos:
            try:
                r = correr(todos[cid], a.modelo, a.referencia, corrida / f"{cid}-{vuelta}", a.conservar)
            except subprocess.CalledProcessError as e:  # git o uv: el caso está mal armado, no es culpa de Qwen
                r = {"caso": cid, "ok": False,
                     "error_arnes": f"{e.cmd[:4]} (código {e.returncode}): {(e.stderr or e.stdout or '')[-500:]}"}
            with open(corrida / "resultados.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({k: v for k, v in r.items() if k != "reporte"}, ensure_ascii=False) + "\n")
            print(f"{cid:28} {'ok' if r['ok'] else 'FALLA':6} {r.get('segundos', '-'):>5} s  "
                  f"turnos {r.get('turnos', '-')}  {r.get('ultima_linea', r.get('error_arnes', ''))[:70]}", flush=True)


if __name__ == "__main__":
    main()

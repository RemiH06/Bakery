"""Clases de inspiración: el Baker `clasificador` le pone clase a cada pieza y la clase decide la plantilla de la
nota, a qué destino se enlaza y si el material (video, fotogramas, transcripción) se conserva.

Las clases no viven en este repo: se leen de la nota `0. Clases de inspiración.md` de la carpeta de notas, que es
su fuente de verdad. Una clase nueva se agrega allá; aquí solo hace falta su plantilla en `plantillas/`.
"""
import json
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from . import core, notas, reel
from .core import BakerError

NOTA_CLASES = "0. Clases de inspiración.md"
REVISAR, RUIDO = "revisar", "ruido"  # no encaja en ninguna (se le pregunta a Remi) / nada que guardar: sin nota
LOTE = 40  # piezas por llamada al clasificador, igual que su `lote` en bakers.toml
_SECCIONES = {"Idea central": "idea_central", "Recursos": "recursos", "Pasos": "pasos", "Citas": "citas",
              "Texto en pantalla": "texto_en_pantalla", "Visual": "visual",
              "Afirmaciones por verificar": "afirmaciones", "Aplicación": "aplicacion"}
# El enlace que se agrega al meter una nota a mano en un grupo del panel (`notas.grupos_de` los lee de `- Destino:`)
_ENLACE_GRUPO = {"AyP": "[[AyP]]", "100": "[[16.100|100]]", "iroFactory": "[[37.iroFactory|iroFactory]]", "AduSI": "[[AduSI]]"}
_CABECERA = {"Fuente": "fuente", "Formato": "formato", "Visto": "visto",
             "Material (video, transcripción, fotogramas)": "material"}


def cargar(carpeta: Path, ruta: str | None = None) -> dict[str, dict]:
    """La tabla de clases (identificador -> nombre, qué guarda, destino, si conserva el material), de `ruta` o de
    la nota de clases de `carpeta`. Falla si a una clase le falta su plantilla."""
    nota = Path(ruta).expanduser() if ruta else carpeta / NOTA_CLASES
    if not nota.is_file():
        raise BakerError(f"Falta la nota de clases: {nota}")
    clases, columnas = {}, None
    for linea in nota.read_text("utf-8").splitlines():
        if not linea.startswith("|"):
            columnas = None
            continue
        # `\|` es un pipe dentro de un enlace de Obsidian ([[32.Bentos\|Bentos]]), no un cambio de celda
        celdas = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", linea.strip())[1:-1]]
        if columnas is None:
            columnas = celdas
        elif "Identificador" in columnas and not set("".join(celdas)) <= set("-: "):
            fila = dict(zip(columnas, celdas))
            clases[fila["Identificador"].strip("`")] = {
                "nombre": fila["Clase"], "guarda": fila["Qué se guarda"],
                "destino": "" if fila["Destino"] in ("—", "-") else fila["Destino"],
                "conserva": fila["Material"].lower().startswith("se conserva")}
    if not clases:
        raise BakerError(f"{nota} no trae la tabla de clases (columnas Clase, Identificador, Qué se guarda, "
                         "Destino, Material)")
    faltan = [c for c in [*clases, REVISAR] if c != RUIDO and not reel.PLANTILLAS.joinpath(f"{c}.md").is_file()]
    if faltan:
        raise BakerError(f"Clases sin plantilla en bakers/plantillas: {', '.join(faltan)}")
    return clases


def linea(bloques: dict, pista: str | None) -> str:
    """Lo que el clasificador lee de una pieza, en un renglón."""
    recursos = re.findall(r"(?m)^\| (?!Recurso \||---)([^|]+?) \|", bloques.get("recursos") or "")
    cuenta = (bloques.get("fuente") or "").split(",")[0]
    texto = f"{bloques['tema']}. {bloques.get('idea_central') or ''} Account: {cuenta}."
    if recursos:
        texto += f" Resources: {', '.join(recursos[:5])}."
    if pista:
        texto += f" [{pista}]"
    return " ".join(texto.split())


def asignar(piezas: list[str], clases: dict[str, dict]) -> list[str]:
    """Una clase por pieza (un renglón de `linea` cada una) con el Baker `clasificador`."""
    lista = "\n".join(f"- {k}: {v['nombre']}. Keeps: {v['guarda']}" for k, v in clases.items())
    tarea = ("Each item summarizes a social media post the user saved. Pick the class whose topic matches it. "
             "A hint in brackets is the user's own folder name for it: trust it. "
             "When no class matches exactly, pick the closest one. "
             f"Use {RUIDO} only when nothing is worth keeping, and {REVISAR} only when no class is even close."
             f"\nClasses:\n{lista}\n- {REVISAR}: worth keeping, but no class above is even close")
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "piezas.txt"
        ruta.write_text("\n".join(piezas), "utf-8")
        res = core.bake("clasificador", tarea, [str(ruta)], [*clases, REVISAR])
    asignadas = [REVISAR] * len(piezas)
    for clase, por_archivo in res["por_categoria"].items():
        for n in por_archivo[str(ruta)]:  # renglón n = pieza n (ninguna viene vacía)
            asignadas[n - 1] = clase
    return asignadas


def _borrar(material: Path) -> None:
    """Solo carpetas de una pieza dentro de `~/.bakers/reels`."""
    raiz = reel.CARPETA.resolve()
    if material.is_dir() and material.resolve().parent == raiz:
        shutil.rmtree(material)


def _conserva(clase: str, clases: dict[str, dict]) -> bool:
    return clase == REVISAR or clases.get(clase, {}).get("conserva", False)  # `revisar`: hasta que Remi decida


def descartar(bloques: dict, clase: str, clases: dict[str, dict]) -> None:
    """Borra el material si la clase no lo conserva. Va al final, ya con la nota escrita y la pieza anotada:
    si el proceso muere antes, la siguiente vuelta todavía tiene `reel.json` para escribir la nota."""
    if not _conserva(clase, clases) and bloques.get("material"):
        _borrar(Path(bloques["material"]).expanduser())


def archivar(bloques: dict, clase: str, clases: dict[str, dict], carpeta: Path, nombre: str,
             frontmatter: list[str] = (), destino: str | None = None) -> Path | None:
    """Escribe `carpeta/nombre` con la plantilla de la clase; `ruido` no deja nota y regresa None. El material
    se borra aparte, con `descartar`. `destino`: el que se eligió a mano, en vez del de la clase."""
    info = clases.get(clase, {})
    conserva = _conserva(clase, clases)
    if clase == RUIDO:
        return None
    cuerpo = reel.plantilla(clase, {**bloques, "destino": info.get("destino", "") if destino is None else destino,
                                    "material": bloques.get("material") if conserva else ""})
    fm = [x for x in frontmatter if not x.startswith(("clase:", "tambien:"))] or ["tipo: inspiración"]
    nota = carpeta / nombre
    nota.write_text("---\n" + "\n".join([*fm, f"clase: {clase}"]) + "\n---\n" + cuerpo, "utf-8")
    return nota


def _de_nota(texto: str) -> tuple[list[str], dict]:
    """Frontmatter y bloques de una nota escrita por `reel` antes de las clases. Una sección que no es de
    `reel` (algo que se agregó a mano) se conserva tal cual en `extra`."""
    fm = []
    if texto.startswith("---\n"):
        cabeza, _, texto = texto[4:].partition("\n---\n")
        fm = [x for x in cabeza.splitlines() if x.strip()]
    cabecera, *secciones = re.split(r"(?m)^## ", texto)
    bloques, extra = {"tema": re.search(r"(?m)^# (.+)$", cabecera)[1].strip()}, []
    for x in cabecera.splitlines():
        m = re.match(r"- (.+?): (.*)$", x)
        if m and m[1] in _CABECERA:
            bloques[_CABECERA[m[1]]] = m[2].strip("` ")
    for s in secciones:
        titulo, _, cuerpo = s.partition("\n")
        if titulo.strip() in _SECCIONES:
            bloques[_SECCIONES[titulo.strip()]] = cuerpo.strip()
        else:
            extra.append(f"## {s.strip()}")
    if bloques.get("aplicacion") == "- (pendiente)":
        bloques["aplicacion"] = ""
    if len((bloques.get("recursos") or "").splitlines()) <= 2:  # solo encabezado de la tabla
        bloques["recursos"] = ""
    bloques["extra"] = "\n\n".join(extra)
    return fm, bloques


def _grupos(texto: str) -> set[str]:
    return set(notas.grupos_de(notas.ENLACE.findall(texto))) - {"otros"}


def destino_de(base: str, grupos: set[str]) -> str:
    """`base` (un renglón Destino) con solo estos grupos: quita los enlaces de los demás y agrega los que falten.
    Lo que no es de ningún grupo (un skill, una nota suelta) se queda."""
    if _grupos(base) == grupos:
        return base
    partes = [p for p in re.split(r"[,;]\s*", base) if p.strip() and _grupos(p) <= grupos]
    return ", ".join([*partes, *(x for g, x in _ENLACE_GRUPO.items() if g in grupos - _grupos(base))])


def cambiar(nota: Path, clase: str, grupos: set[str], tabla: dict[str, dict]) -> str:
    """Clase y grupos elegidos a mano: reescribe solo `clase:` y `- Destino:`, nada del cuerpo. Regresa el destino.
    Si la clase cambió, parte del destino de la nueva; si no, del que tenía la nota."""
    texto = nota.read_text("utf-8")
    cabeza, cuerpo = "", texto
    if texto.startswith("---\n") and (fin := texto.find("\n---\n", 3)) >= 0:
        cabeza, cuerpo = texto[4:fin + 1], texto[fin + 5:]
    previa = re.search(r"(?m)^clase:[ \t]*(.*?)[ \t]*$", cabeza)
    if previa:
        cabeza = f"{cabeza[:previa.start()]}clase: {clase}{cabeza[previa.end():]}"
    else:
        cabeza += f"clase: {clase}\n"
    corte = m.start() if (m := re.search(r"(?m)^## ", cuerpo)) else len(cuerpo)
    encabezado, resto = cuerpo[:corte], cuerpo[corte:]
    actual = re.search(r"(?m)^- Destino:[ \t]*(.*)\n?", encabezado)
    base = actual[1].strip() if actual and previa and previa[1] == clase else tabla.get(clase, {}).get("destino", "")
    destino = destino_de(base, grupos)
    renglon = f"- Destino: {destino}\n" if destino else ""
    if actual:
        encabezado = encabezado[:actual.start()] + renglon + encabezado[actual.end():]
    elif ultimos := list(re.finditer(r"(?m)^- .*\n?", encabezado)):
        aqui = ultimos[-1].end()
        encabezado = encabezado[:aqui].rstrip("\n") + "\n" + renglon + encabezado[aqui:]
    elif renglon:  # sin encabezado de `- Fuente:`: bajo el título
        encabezado = f"{encabezado.rstrip()}\n\n{renglon}" + ("\n" if resto else "")
    nota.write_text(f"---\n{cabeza}---\n{encabezado}{resto}", "utf-8")
    return destino


def conservar(nota: Path, bloques: dict) -> tuple[list[str], dict]:
    """Para escribir otra vez una nota ya analizada: su frontmatter, cuándo se vio, su Aplicación y las secciones
    que no son de ninguna plantilla (lo agregado a mano), sobre los bloques nuevos."""
    try:
        fm, viejos = _de_nota(nota.read_text("utf-8"))
    except (OSError, TypeError):  # la nota ya no está, o no tiene título
        return [], bloques
    propias = {t.strip() for p in reel.PLANTILLAS.iterdir() if p.name.endswith(".md")
               for t in re.findall(r"(?m)^## (.+)$", p.read_text("utf-8"))}
    extra = [s.strip() for s in re.split(r"(?m)^(?=## )", viejos["extra"])
             if s.strip() and s.partition("\n")[0].removeprefix("## ").strip() not in propias]
    return fm, {**bloques, "visto": viejos.get("visto") or bloques["visto"], "aplicacion": viejos.get("aplicacion") or "",
                "extra": "\n\n".join(extra)}


def _transcripcion(material: str | None) -> str:
    """Texto completo desde el material, si sigue en esta máquina."""
    ruta = Path(material).expanduser() / "transcripcion.json" if material else None
    if not (ruta and ruta.is_file()):
        return ""
    return "\n".join(f"- [{s['t']}] {s['texto']}" for s in reel.limpiar(json.loads(ruta.read_text("utf-8"))))


def reclasificar(destino: str, ruta_clases: str | None = None, pistas: dict[str, str] | None = None,
                 revisar: bool = False) -> dict:
    """Pone clase a las notas de `destino` que no la tienen y las reescribe con su plantilla, de 40 en 40 (lo
    hecho se queda si algo falla a media corrida). `ruido` borra la nota. `pistas`: código del reel -> sección o
    etiqueta que Remi le puso al guardarlo. Con `revisar`, también las que quedaron en `revisar` (tras agregar
    una clase a la nota de clases)."""
    carpeta = Path(destino).expanduser()
    clases = cargar(carpeta, ruta_clases)
    notas = []
    for n in sorted(carpeta.glob("[0-9][0-9][0-9][0-9]-*.md")):
        fm, bloques = _de_nota(n.read_text("utf-8"))
        clase = next((x.partition(":")[2].strip() for x in fm if x.startswith("clase:")), None)
        if clase is None or (revisar and clase == REVISAR):
            bloques["transcripcion"] = _transcripcion(bloques.get("material"))
            notas.append((n, fm, bloques))
    conteo = Counter()
    for i in range(0, len(notas), LOTE):
        trozo = notas[i:i + LOTE]
        pista = [(pistas or {}).get(reel.codigo(b.get("fuente") or "")) for _, _, b in trozo]
        for (n, fm, b), clase in zip(trozo, asignar([linea(b, p) for (_, _, b), p in zip(trozo, pista)], clases)):
            if archivar(b, clase, clases, carpeta, n.name, fm) is None:
                n.unlink()
            descartar(b, clase, clases)
            conteo[clase] += 1
        print(f"[clases] {min(i + LOTE, len(notas))} de {len(notas)}", flush=True)
    return dict(conteo)

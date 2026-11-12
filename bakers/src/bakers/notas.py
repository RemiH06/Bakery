"""Explorador de notas para el panel: la inspo y la bandeja, leídas del clon de la bóveda en Pixilate.

El filtro es literal: el texto buscado, tal cual, en cualquier parte de la nota (frontmatter incluido), sin
distinguir mayúsculas ni acentos. Cada nota se pliega una vez (minúsculas y sin diacríticos) con un mapa al
texto original, para que el fragmento salga con sus acentos. Todo se cachea por `mtime`: una vuelta de
`analizar` que trae notas nuevas solo relee esas.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

GRUPOS = ("AyP", "100", "iroFactory", "AduSI")  # las pestañas del cuaderno; lo demás es "otros"
CONTEXTO = 90  # caracteres a cada lado de la coincidencia en el fragmento
_ENLACE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_PROYECTO = re.compile(r"^\d+\.\S")  # "37.iroFactory" sí; "0. emprendimiento" no
_PLEGADO: dict[str, str] = {}


def _plegar_letra(c: str) -> str:
    if (p := _PLEGADO.get(c)) is None:
        p = _PLEGADO[c] = "".join(x for x in unicodedata.normalize("NFD", c)
                                  if not unicodedata.combining(x)).casefold()
    return p


def plegar(texto: str) -> tuple[str, list[int]]:
    """Minúsculas y sin acentos, con la posición original de cada carácter plegado ("ß" da dos)."""
    partes, mapa = [], []
    for i, c in enumerate(texto):
        p = _plegar_letra(c)
        partes.append(p)
        mapa.extend([i] * len(p))
    return "".join(partes), mapa


def _frontmatter(texto: str) -> tuple[dict, str]:
    if not texto.startswith("---\n"):
        return {}, texto
    fin = texto.find("\n---", 4)
    if fin < 0:
        return {}, texto
    fm = {}
    for linea in texto[4:fin].splitlines():
        clave, dos, valor = linea.partition(":")
        if dos and clave.strip():
            valor = valor.strip()
            if valor.startswith('"'):
                try:
                    valor = json.loads(valor)  # `pista` de la bandeja va con json.dumps
                except json.JSONDecodeError:
                    pass
            fm[clave.strip()] = valor
    return fm, texto[fin + 4:].lstrip("\n")


def grupos_de(destinos: list[str], pista: str | None = None) -> list[str]:
    grupos = []
    for d in destinos + ([pista] if pista else []):
        d = d.strip()
        g = ("100" if d in ("100", "16.100") else "AyP" if d.lower() == "ayp" else "AduSI" if d.lower() == "adusi"
             else "iroFactory" if _PROYECTO.match(d) or d.lower() == "irofactory" else None)
        if g and g not in grupos:
            grupos.append(g)
    return grupos or ["otros"]


def meta(nombre: str, texto: str, fuente: str) -> dict:
    """Lo que el listado necesita de una nota: título, clase, cuenta, fuente, fecha, destinos y grupo."""
    fm, cuerpo = _frontmatter(texto)
    datos = {}
    for linea in cuerpo.splitlines()[:12]:  # los renglones "- Fuente:", "- Visto:"... van bajo el título
        m = re.match(r"- (Fuente|Formato|Visto|Destino):\s*(.*)", linea)
        if m:
            datos[m[1]] = m[2]
    titulo = next((x[2:].strip() for x in cuerpo.splitlines() if x.startswith("# ")), None)
    url = re.search(r"https?://\S+", datos.get("Fuente", ""))
    cuenta = re.match(r"@[\w.]+", datos.get("Fuente", ""))
    destinos = _ENLACE.findall(datos.get("Destino", ""))
    fecha = datos.get("Visto") or str(fm.get("fecha", ""))[:10] or nombre[:10]
    if fuente == "bandeja" and not titulo:
        titulo = " ".join(cuerpo.split()[:8]) or nombre
    return {"nombre": nombre, "titulo": titulo or nombre.removesuffix(".md"), "clase": fm.get("clase"),
            "cuenta": cuenta[0] if cuenta else None, "url": url[0].rstrip(").,") if url else None,
            "formato": datos.get("Formato"), "fecha": fecha if re.match(r"\d{4}-\d\d-\d\d", fecha) else None,
            "destinos": destinos, "grupos": grupos_de(destinos, fm.get("pista")), "pista": fm.get("pista")}


@dataclass
class _Nota:
    mtime: float
    texto: str
    plegado: str
    mapa: list[int]
    meta: dict


@dataclass
class Carpeta:
    """Las notas `.md` de una carpeta (sin subcarpetas). Las que empiezan con "0. " son índices: no entran."""
    ruta: Path
    fuente: str
    _cache: dict[str, _Nota] = field(default_factory=dict)

    def notas(self) -> dict[str, _Nota]:
        vistas = {}
        for p in self.ruta.glob("*.md") if self.ruta.is_dir() else ():
            if p.name.startswith("0. "):
                continue
            try:
                mtime = p.stat().st_mtime
                nota = self._cache.get(p.name)
                if not nota or nota.mtime != mtime:
                    texto = p.read_text("utf-8", errors="replace").replace("\r\n", "\n")
                    nota = _Nota(mtime, texto, *plegar(texto), meta(p.name, texto, self.fuente))
            except OSError:  # `git pull` de `analizar` a media lectura: la siguiente consulta la ve
                continue
            vistas[p.name] = nota
        self._cache = vistas
        return vistas

    def nota(self, nombre: str) -> dict | None:
        """Solo por nombre exacto de una nota del índice: nada de rutas."""
        n = self.notas().get(nombre)
        return {**n.meta, "fuente": self.fuente, "texto": n.texto} if n else None


def _legible(texto: str) -> str:
    """El fragmento es texto plano: sin la sintaxis de Markdown que lo vuelve ilegible en una línea."""
    texto = re.sub(r"\[\[([^\]|]+?)(?:\\?\|([^\]]+))?\]\]", lambda m: m[2] or m[1], texto)
    texto = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", texto)
    texto = re.sub(r"(?m)^\s*(#{1,6}|[-*+]|>)\s+", "", texto)
    texto = re.sub(r"\s*\|\s*", " · ", texto.replace("\\|", "|")).strip(" ·")
    return " ".join(texto.replace("**", "").replace("`", "").split())


def _fragmento(nota: _Nota, pos: int | None, largo: int) -> str:
    texto = nota.texto
    if pos is None:  # sin búsqueda: el primer párrafo después del encabezado de la nota
        _, cuerpo = _frontmatter(texto)
        lineas = [x for x in cuerpo.splitlines() if x.strip() and not x.startswith(("#", "- ", "|", "---"))]
        return _legible(lineas[0])[:2 * CONTEXTO] if lineas else ""
    ini, fin = nota.mapa[pos], nota.mapa[min(pos + largo, len(nota.mapa)) - 1] + 1
    cuerpo = len(texto) - len(_frontmatter(texto)[1])
    # Si la coincidencia está en el cuerpo, el fragmento no arrastra el frontmatter
    a, b = max(0 if ini < cuerpo else cuerpo, ini - CONTEXTO), min(len(texto), fin + CONTEXTO)
    # Sin cortar una palabra a la mitad en las orillas
    while a > 0 and not texto[a - 1].isspace() and ini - a < CONTEXTO + 20:
        a -= 1
    while b < len(texto) and not texto[b].isspace() and b - fin < CONTEXTO + 20:
        b += 1
    return ("…" if a else "") + _legible(texto[a:b]) + ("…" if b < len(texto) else "")


def buscar(carpeta: Carpeta, q: str = "", grupo: str | None = None, clase: str | None = None,
           mes: str | None = None, estados: dict[str, str] | None = None) -> dict:
    """Notas que contienen `q` y cumplen los filtros, de la más nueva a la más vieja, con conteos por grupo
    y por clase. Cada conteo aplica los demás filtros, para que la pestaña diga cuántas habría al cambiar."""
    qp = plegar(" ".join(q.split()))[0] if q.strip() else ""
    estados = estados or {}
    hallados, todas = [], carpeta.notas()
    for nombre, n in todas.items():
        pos = n.plegado.find(qp) if qp else None
        if qp and pos < 0:
            continue
        hallados.append((nombre, n, pos))

    def pasa(m: dict, sin: str) -> bool:
        return ((sin == "grupo" or not grupo or grupo in m["grupos"]) and (sin == "clase" or not clase or m["clase"] == clase)
                and (sin == "mes" or not mes or (m["fecha"] or "").startswith(mes)))

    conteo = {"todos": 0, "grupos": {}, "clases": {}, "meses": {}}
    for _, n, _ in hallados:
        m = n.meta
        if pasa(m, "grupo"):
            conteo["todos"] += 1
            for g in m["grupos"]:
                conteo["grupos"][g] = conteo["grupos"].get(g, 0) + 1
        if pasa(m, "clase") and m["clase"]:
            conteo["clases"][m["clase"]] = conteo["clases"].get(m["clase"], 0) + 1
        if pasa(m, "mes") and m["fecha"]:
            conteo["meses"][m["fecha"][:7]] = conteo["meses"].get(m["fecha"][:7], 0) + 1
    notas = [{**n.meta, "fuente": carpeta.fuente, "estado": estados.get(nombre),
              "coincidencias": n.plegado.count(qp) if qp else None, "fragmento": _fragmento(n, pos, len(qp))}
             for nombre, n, pos in hallados if pasa(n.meta, "")]
    notas.sort(key=lambda x: (x["fecha"] or "", x["nombre"]), reverse=True)
    return {"total": len(todas), "notas": notas, "conteo": conteo}

// Utilidades comunes. Nada aquí usa innerHTML: todo texto entra como nodo de texto.

export function el(tag, props = {}, ...hijos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat(Infinity)) if (h != null && h !== "" && h !== false) n.append(h);
  return n;
}

// Solo http(s): un `javascript:` o `data:` de una transcripción ajena se queda como texto
export const esWeb = (url) => /^https?:\/\//i.test(url || "");
export const enlace = (url, texto, props = {}) =>
  esWeb(url) ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", ...props }, texto ?? url) : (texto ?? url);

export const hora = (iso) => iso ? new Date(iso).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" }) : "—";
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
export const fecha = (iso) => iso ? `${+iso.slice(8, 10)} ${MESES[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}` : "";
export const mes = (ym) => `${MESES[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}`;

export async function api(ruta, cuerpo, senal) {
  const r = await fetch(ruta, cuerpo
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo), signal: senal }
    : { signal: senal });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}

// Igual que `notas.plegar` del servidor: minúsculas, sin acentos, y la posición original de cada carácter
export function plegar(texto) {
  let p = "";
  const mapa = [];
  for (let i = 0; i < texto.length; i++) {
    const f = texto[i].normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace("ß", "ss");
    p += f;
    for (let j = 0; j < f.length; j++) mapa.push(i);
  }
  return [p, mapa];
}

// Envuelve en <mark> cada aparición de `q` dentro de los nodos de texto de `raiz`; regresa las marcas
export function resaltar(raiz, q) {
  const [qp] = plegar(q.trim().split(/\s+/).join(" "));
  if (!qp) return [];
  const marcas = [];
  const andador = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
  const nodos = [];
  while (andador.nextNode()) nodos.push(andador.currentNode);
  for (const nodo of nodos) {
    const texto = nodo.nodeValue;
    const [p, mapa] = plegar(texto);
    let desde = 0, i, partes = [], ultimo = 0;
    while ((i = p.indexOf(qp, desde)) >= 0) {
      const a = mapa[i], b = mapa[i + qp.length - 1] + 1;
      partes.push(texto.slice(ultimo, a));
      const m = el("mark", {}, texto.slice(a, b));
      partes.push(m); marcas.push(m);
      ultimo = b; desde = i + qp.length;
    }
    if (!partes.length) continue;
    partes.push(texto.slice(ultimo));
    nodo.replaceWith(...partes.filter(x => x !== ""));
  }
  return marcas;
}

// Pestañas con teclado (patrón de tablist): flechas, Inicio y Fin mueven el foco y activan
export function teclasPestanas(lista, activar) {
  lista.addEventListener("keydown", (ev) => {
    const tabs = [...lista.querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    const j = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: tabs.length - 1 }[ev.key];
    if (j == null) return;
    ev.preventDefault();
    const t = tabs[(j + tabs.length) % tabs.length];
    t.focus(); activar(t);
  });
}

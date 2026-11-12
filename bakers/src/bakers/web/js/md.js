// Markdown de la bóveda a nodos del DOM, sin innerHTML: las notas traen texto de terceros (transcripciones),
// así que cualquier etiqueta que venga dentro sale como texto. Cubre lo que usan las plantillas: encabezados,
// listas anidadas, tablas (con `\|` en los wikilinks), citas, código, separadores, negritas, cursivas,
// enlaces y [[wikilinks]]. Los saltos de renglón se respetan, como en Obsidian (los poemas de la bandeja).
import { el, enlace } from "./util.js";

const INLINE = new RegExp([
  String.raw`\[\[([^\]]+)\]\]`,                                  // 1 wikilink
  String.raw`\[([^\]]+)\]\(([^)\s]+)\)`,                          // 2,3 enlace con texto
  String.raw`(https?:\/\/[^\s<>()]*[^\s<>().,;:!?"'»])`,          // 4 URL suelta
  "`([^`]+)`",                                                    // 5 código
  String.raw`\*\*(.+?)\*\*`,                                      // 6 negrita
  String.raw`(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])`,          // 7 cursiva con *
  String.raw`(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])`,              // 8 cursiva con _
].join("|"), "g");

export function inline(texto) {
  const out = [];
  let ultimo = 0;
  for (const m of texto.matchAll(INLINE)) {
    if (m.index > ultimo) out.push(texto.slice(ultimo, m.index));
    if (m[1]) {
      const [destino, alias] = m[1].replace(/\\\|/g, "|").split("|");
      out.push(el("span", { class: "wikilink", title: destino.trim() }, (alias || destino).trim()));
    } else if (m[2]) out.push(enlace(m[3], m[2]));
    else if (m[4]) out.push(enlace(m[4], m[4]));
    else if (m[5]) out.push(el("code", {}, m[5]));
    else if (m[6]) out.push(el("strong", {}, ...inline(m[6])));
    else out.push(el("em", {}, ...inline(m[7] || m[8])));
    ultimo = m.index + m[0].length;
  }
  if (ultimo < texto.length) out.push(texto.slice(ultimo));
  return out;
}

function renglones(lineas) {
  const out = [];
  lineas.forEach((l, i) => { if (i) out.push(el("br")); out.push(...inline(l)); });
  return out;
}

const celdas = (l) => l.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map(c => c.trim());

export function separar(texto) {
  if (!texto.startsWith("---\n")) return [{}, texto];
  const fin = texto.indexOf("\n---", 4);
  if (fin < 0) return [{}, texto];
  const fm = {};
  for (const l of texto.slice(4, fin).split("\n")) {
    const i = l.indexOf(":");
    if (i > 0) fm[l.slice(0, i).trim()] = l.slice(i + 1).trim().replace(/^"(.*)"$/, "$1");
  }
  return [fm, texto.slice(fin + 4).replace(/^\n+/, "")];
}

// Cuerpo de la nota (sin frontmatter) a un fragmento del DOM. `sinTitulo` quita el primer "# " (va en la cabecera).
export function render(cuerpo, { sinTitulo = false } = {}) {
  const lineas = cuerpo.replace(/\r\n/g, "\n").split("\n");
  const raiz = document.createDocumentFragment();
  let i = 0, tituloQuitado = !sinTitulo;
  while (i < lineas.length) {
    const l = lineas[i];
    if (!l.trim()) { i++; continue; }
    let m;
    if (l.startsWith("```")) {
      const codigo = [];
      for (i++; i < lineas.length && !lineas[i].startsWith("```"); i++) codigo.push(lineas[i]);
      raiz.append(el("pre", {}, el("code", {}, codigo.join("\n"))));
      i++;
    } else if ((m = l.match(/^(#{1,6})\s+(.*)$/))) {
      if (!tituloQuitado && m[1] === "#") { tituloQuitado = true; i++; continue; }
      raiz.append(el(`h${Math.min(m[1].length + 1, 6)}`, {}, ...inline(m[2])));
      i++;
    } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) {
      raiz.append(el("hr")); i++;
    } else if (l.trimStart().startsWith("|")) {
      const filas = [];
      for (; i < lineas.length && lineas[i].trimStart().startsWith("|"); i++) filas.push(lineas[i]);
      const sep = filas.length > 1 && /^\s*\|?\s*:?-{2,}/.test(filas[1]);
      const cab = sep ? celdas(filas[0]) : null;
      const cuerpoT = filas.slice(sep ? 2 : 0).map(celdas);
      raiz.append(el("div", { class: "tabla", tabindex: "0", role: "region", "aria-label": "Tabla" },
        el("table", {},
          cab ? el("thead", {}, el("tr", {}, cab.map(c => el("th", { scope: "col" }, ...inline(c))))) : null,
          el("tbody", {}, cuerpoT.map(f => el("tr", {}, f.map(c => el("td", {}, ...inline(c)))))))));
    } else if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
      // Listas anidadas por sangría: una pila de (sangría, lista)
      const pila = [];
      for (; i < lineas.length && (m = lineas[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/)); i++) {
        const sangria = m[1].replace(/\t/g, "  ").length, ordenada = /\d/.test(m[2]);
        while (pila.length && pila.at(-1).sangria > sangria) pila.pop();
        if (!pila.length || pila.at(-1).sangria < sangria) {
          const lista = el(ordenada ? "ol" : "ul");
          if (pila.length) (pila.at(-1).lista.lastElementChild || pila.at(-1).lista).append(lista);
          else raiz.append(lista);
          pila.push({ sangria, lista });
        }
        const tarea = m[3].match(/^\[( |x)\]\s+(.*)$/i);
        pila.at(-1).lista.append(tarea
          ? el("li", { class: "tarea" }, el("span", { "aria-hidden": "true" }, tarea[1] === " " ? "☐ " : "☑ "), ...inline(tarea[2]))
          : el("li", {}, ...inline(m[3])));
      }
    } else if (l.startsWith(">")) {
      const cita = [];
      for (; i < lineas.length && lineas[i].startsWith(">"); i++) cita.push(lineas[i].replace(/^>\s?/, ""));
      raiz.append(el("blockquote", {}, el("p", {}, ...renglones(cita))));
    } else {
      const parrafo = [];
      for (; i < lineas.length && lineas[i].trim() && !/^(#{1,6}\s|```|>|\s*\||\s*([-*+]|\d+[.)])\s)/.test(lineas[i]); i++)
        parrafo.push(lineas[i]);
      if (!parrafo.length) { parrafo.push(l); i++; }
      raiz.append(el("p", {}, ...renglones(parrafo)));
    }
  }
  return raiz;
}

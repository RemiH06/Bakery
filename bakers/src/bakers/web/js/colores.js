// Color de cada grupo (el relleno de su pay). Se guarda en este navegador: es una preferencia de quien mira,
// no un dato del panel. Sin almacenamiento (ventana privada), se usan los de siempre.
import { el } from "./util.js";
import { GRUPOS, pay } from "./inspo.js";

const CLAVE = "bakery.colores";
export const FRUTAS = [
  ["cereza", "#F0566A"], ["fresa", "#FF6F91"], ["frambuesa", "#E0457B"], ["mora", "#A08CF0"],
  ["uva", "#B07CE0"], ["arándano", "#7D9CF0"], ["menta", "#6FD3B0"], ["kiwi", "#8DBF4A"],
  ["limón", "#E6C93A"], ["mango", "#F5A83A"], ["naranja", "#F4874B"], ["pan", "#C9A27A"],
];
const DE_FABRICA = { AyP: "#F0566A", 100: "#A08CF0", iroFactory: "#8DBF4A", AduSI: "#E6C93A", otros: "#C9A27A" };
const HEX = /^#[0-9a-f]{6}$/i;

function leer() {
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE) || "{}");
    return { ...DE_FABRICA, ...Object.fromEntries(Object.entries(guardado).filter(([g, h]) => g in DE_FABRICA && HEX.test(h))) };
  } catch { return { ...DE_FABRICA }; }
}
function guardar(c) { try { localStorage.setItem(CLAVE, JSON.stringify(c)); } catch { /* sin almacenamiento: vale esta visita */ } }

export function aplicar(c = leer()) {
  for (const [g, h] of Object.entries(c)) document.documentElement.style.setProperty(`--g-${g}`, h);
}

// Contraste WCAG contra la hoja: un relleno o una pestaña es componente de interfaz, pide 3:1
function luminancia(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contraste = (a, b) => { const [x, y] = [luminancia(a), luminancia(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const nombreDe = (hex) => FRUTAS.find(([, h]) => h.toLowerCase() === hex.toLowerCase())?.[0];

export function crearDialogo(boton) {
  let colores = leer();
  const filas = el("div", { class: "colores-filas" });
  const dialogo = el("dialog", { class: "colores", "aria-labelledby": "colores-t" },
    el("form", { method: "dialog", class: "pila" },
      el("h2", { id: "colores-t" }, "Colores de los grupos"),
      el("p", { class: "ayuda" }, "Cada grupo es un pay. Elige su fruta o cualquier color; se guarda en este navegador."),
      filas,
      el("div", { class: "fila" },
        el("button", { type: "button", class: "boton", onclick: () => { colores = { ...DE_FABRICA }; guardar(colores); aplicar(colores); pintar(); } }, "Restablecer"),
        el("button", { type: "submit", class: "boton primario" }, "Listo"))));
  document.body.append(dialogo);

  function elegir(g, hex) {
    colores = { ...colores, [g]: hex.toUpperCase() };
    guardar(colores); aplicar(colores); pintar();
  }

  function pintar() {
    const papel = getComputedStyle(document.documentElement).getPropertyValue("--papel").trim() || "#301B25";
    filas.replaceChildren(...GRUPOS.map(g => {
      const hex = colores[g.id];
      const repetido = GRUPOS.find(o => o.id !== g.id && colores[o.id].toLowerCase() === hex.toLowerCase());
      const avisos = [contraste(hex, papel) < 3 ? "poco contraste con la hoja" : null, repetido ? `igual que ${repetido.id}` : null].filter(Boolean);
      const libre = el("input", { type: "color", value: hex.toLowerCase(), id: `color-${g.id}` });
      libre.addEventListener("input", () => elegir(g.id, libre.value));
      return el("fieldset", { class: `color-grupo g-${g.id}` },
        el("legend", {}, pay(g.id), ` ${g.id}`, g.nombre !== g.id ? el("span", { class: "tenue" }, ` · ${g.nombre}`) : null),
        el("div", { class: "muestras", role: "group", "aria-label": `Fruta para ${g.id}` },
          FRUTAS.map(([nombre, h]) => {
            const b = el("button", { type: "button", class: "muestra", "aria-pressed": String(h.toLowerCase() === hex.toLowerCase()),
              onclick: () => elegir(g.id, h) }, el("span", { class: "punto", "aria-hidden": "true" }), nombre);
            b.firstChild.style.background = h;
            return b;
          })),
        el("div", { class: "fila" },
          el("label", { for: `color-${g.id}`, class: "otro" }, "Otro color"), libre,
          el("span", { class: "tenue" }, nombreDe(hex) || hex),
          avisos.length ? el("span", { class: "error" }, `Ojo: ${avisos.join(", ")}`) : null));
    }));
  }

  boton.addEventListener("click", () => { colores = leer(); pintar(); dialogo.showModal(); });
}

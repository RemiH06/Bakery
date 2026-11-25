// Grafo de procesos y servicios: cada uno es una ficha que se arrastra (o se mueve con las flechas del teclado) y cada
// flecha va de lo que se usa a quien lo usa, según lo que declara el latido (`--usa`). Solo se ve: aquí no se edita
// lógica. Las fichas son botones de HTML sobre un SVG con las flechas, así el foco y el texto son los del navegador.
// Dónde quedó cada ficha se guarda en este navegador, como los colores: el teléfono y el escritorio no se acomodan igual.
import { el, svg } from "./util.js";

const CLAVE = "bakery.grafo";
const ANCHO = 190, ALTO = 70;   // los de `.nodo-grafo` en panel.css
const PASO_X = 250, PASO_Y = 94, MARGEN = 16;
const REJILLA = 8;              // al soltar, la ficha cae en múltiplos de esto
const UMBRAL = 4;               // px: menos que esto es un clic con el pulso movido, no un arrastre
const FLECHAS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

function leer() {
  try {
    return Object.fromEntries(Object.entries(JSON.parse(localStorage.getItem(CLAVE) || "{}"))
      .filter(([, p]) => Array.isArray(p) && p.length === 2 && p.every(v => Number.isFinite(v) && v >= 0 && v < 20000)));
  } catch { return {}; }
}
function guardar(p) { try { localStorage.setItem(CLAVE, JSON.stringify(p)); } catch { /* sin almacenamiento: vale esta visita */ } }

// [{ de, a }] con las claves de las fichas; agrega a `nodos` una ficha hueca por cada dependencia que nadie reporta
export function aristas(nodos) {
  const res = [], huecas = new Map();
  for (const n of nodos) {
    for (const id of n.usa) {
      // El mismo servicio puede estar en dos máquinas: gana el de la suya
      const candidatos = nodos.filter(x => x.ids.includes(id));
      let de = candidatos.find(x => x.maquina === n.maquina) || candidatos[0] || huecas.get(id);
      if (!de) {
        de = { clave: `?/${id}`, ids: [id], maquina: "", titulo: id, bajo: "nadie lo reporta", estado: "no se ve", clase: "e-pendiente", mal: true, usa: [] };
        huecas.set(id, de);
      }
      if (de !== n && !res.some(r => r.de === de.clave && r.a === n.clave)) res.push({ de: de.clave, a: n.clave });
    }
  }
  return { aristas: res, nodos: [...nodos, ...huecas.values()] };
}

// Acomodo inicial: lo conectado en columnas, de lo que se usa a quien lo usa; abajo lo suelto, en renglones
export function acomodar(nodos, flechas, anchoVisible) {
  const padres = new Map(nodos.map(n => [n.clave, flechas.filter(f => f.a === n.clave).map(f => f.de)]));
  const unidos = new Set(flechas.flatMap(f => [f.de, f.a]));
  const nivel = new Map();
  const medir = (c, camino = new Set()) => {
    if (nivel.has(c)) return nivel.get(c);
    if (camino.has(c)) return 0;  // un ciclo declarado no cuelga la página
    const previos = padres.get(c).map(p => medir(p, new Set([...camino, c])) + 1);
    nivel.set(c, Math.max(0, ...previos));
    return nivel.get(c);
  };
  const columnas = [];
  for (const n of nodos) if (unidos.has(n.clave)) (columnas[medir(n.clave)] ||= []).push(n.clave);
  const pos = {}, renglon = new Map();
  let abajo = 0;
  for (let x = 0; x < columnas.length; x++) {  // por índice: con ciclos puede quedar una columna vacía
    const media = (c) => {
      const ys = padres.get(c).filter(p => renglon.has(p)).map(p => renglon.get(p));
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Infinity;
    };
    const col = (columnas[x] || []).map(c => [c, media(c)]).sort((a, b) => (a[1] === b[1] ? 0 : a[1] - b[1]));
    col.forEach(([c], y) => {
      renglon.set(c, y);
      pos[c] = [MARGEN + x * PASO_X, MARGEN + y * PASO_Y];
      abajo = Math.max(abajo, y + 1);
    });
  }
  const porRenglon = Math.max(1, Math.floor((anchoVisible - MARGEN) / (ANCHO + 24)));
  const inicio = MARGEN + abajo * PASO_Y + (abajo ? 24 : 0);
  nodos.filter(n => !unidos.has(n.clave)).forEach((n, i) => {
    pos[n.clave] = [MARGEN + (i % porRenglon) * (ANCHO + 24), inicio + Math.floor(i / porRenglon) * PASO_Y];
  });
  return pos;
}

export function crear(alElegir) {
  let movidas = leer();      // solo lo que alguien movió; lo demás se acomoda solo
  let pos = {}, nodos = [], flechas = [], elegida = null, arrastre = null, pendiente = null;
  const fichas = new Map();  // clave -> botón: se reusan entre consultas para no perder el foco
  const punta = (id) => {
    const m = svg("marker", { id, viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 8, markerHeight: 8, orient: "auto", markerUnits: "userSpaceOnUse" });
    m.append(svg("path", { d: "M0,0L8,4L0,8Z", class: id }));
    return m;
  };
  const defs = svg("defs");
  defs.append(punta("punta"), punta("punta-mal"), punta("punta-viva"));
  const capa = svg("svg", { class: "flechas", "aria-hidden": "true" });
  const plano = el("div", { class: "plano" }, capa);
  const marco = el("div", { class: "marco-grafo", role: "group", "aria-label": "Grafo de procesos y servicios", "aria-describedby": "grafo-ayuda" }, plano);
  const raiz = el("div", { class: "pila" },
    el("div", { class: "fila" },
      el("p", { class: "ayuda", id: "grafo-ayuda" }, "La flecha va de lo que se usa a quien lo usa. Arrastra una ficha para moverla, o enfócala y usa las flechas del teclado (con Mayús, más lejos)."),
      el("button", { type: "button", class: "boton", onclick: () => { movidas = {}; guardar(movidas); pintar(nodosDados); } }, "Acomodar solo")),
    marco);
  let nodosDados = [];

  function colocar(clave) {
    const b = fichas.get(clave), [x, y] = pos[clave];
    b.style.left = `${x}px`;  // por CSSOM: la CSP no deja atributos style
    b.style.top = `${y}px`;
  }

  function trazar() {
    const ancho = Math.max(0, ...Object.values(pos).map(p => p[0])) + ANCHO + MARGEN;
    const alto = Math.max(0, ...Object.values(pos).map(p => p[1])) + ALTO + MARGEN;
    plano.style.width = `${ancho}px`;
    plano.style.height = `${alto}px`;
    capa.setAttribute("width", ancho);
    capa.setAttribute("height", alto);
    const mal = new Set(nodos.filter(n => n.mal).map(n => n.clave));
    capa.replaceChildren(defs, ...flechas.map(({ de, a }) => {
      const [x1, y1] = [pos[de][0] + ANCHO, pos[de][1] + ALTO / 2], [x2, y2] = [pos[a][0], pos[a][1] + ALTO / 2];
      const t = Math.max(40, Math.abs(x2 - x1) / 2);  // qué tanto sale derecha antes de doblar
      const tono = elegida === de || elegida === a ? "viva" : mal.has(de) ? "mal" : "";
      return svg("path", { d: `M${x1},${y1}C${x1 + t},${y1} ${x2 - t},${y2} ${x2},${y2}`,
        class: `flecha ${tono} ${mal.has(de) ? "cortada" : ""}`, "marker-end": `url(#punta${tono ? `-${tono}` : ""})` });
    }));
  }

  function mover(clave, x, y) {
    const r = (v) => Math.max(0, Math.round(v / REJILLA) * REJILLA);
    pos[clave] = [r(x), r(y)];
    movidas[clave] = pos[clave];
    colocar(clave);
    trazar();
  }

  function elegir(clave, enfocar = false) {
    elegida = clave;
    for (const [c, b] of fichas) b.setAttribute("aria-pressed", String(c === clave));
    trazar();
    avisar();
    if (enfocar) fichas.get(clave)?.focus();
  }

  const nodo = (c) => nodos.find(n => n.clave === c);
  function avisar() {
    const n = nodo(elegida);
    alElegir(n || null, n ? { usa: flechas.filter(f => f.a === n.clave).map(f => nodo(f.de)),
      loUsan: flechas.filter(f => f.de === n.clave).map(f => nodo(f.a)) } : null);
  }

  function ficha(clave) {
    const b = el("button", { type: "button", class: "nodo-grafo", "aria-pressed": "false" });
    let huboArrastre = false;
    b.addEventListener("click", () => { if (!huboArrastre) elegir(clave); huboArrastre = false; });
    b.addEventListener("pointerdown", (ev) => {
      huboArrastre = false;
      if (ev.button !== 0 || !ev.isPrimary) return;
      arrastre = { clave, x: ev.clientX, y: ev.clientY, base: pos[clave], desplazo: [marco.scrollLeft, marco.scrollTop] };
      b.setPointerCapture(ev.pointerId);
    });
    b.addEventListener("pointermove", (ev) => {
      if (arrastre?.clave !== clave) return;
      const dx = ev.clientX - arrastre.x + marco.scrollLeft - arrastre.desplazo[0], dy = ev.clientY - arrastre.y + marco.scrollTop - arrastre.desplazo[1];
      if (!huboArrastre && Math.hypot(dx, dy) < UMBRAL) return;
      huboArrastre = true;
      b.classList.add("en-mano");
      mover(clave, arrastre.base[0] + dx, arrastre.base[1] + dy);
    });
    b.addEventListener("lostpointercapture", () => {  // al soltar y también si el sistema cancela el gesto
      if (arrastre?.clave !== clave) return;
      arrastre = null;
      b.classList.remove("en-mano");
      if (huboArrastre) guardar(movidas);
      if (pendiente) { const p = pendiente; pendiente = null; pintar(p); }
    });
    b.addEventListener("keydown", (ev) => {
      const d = FLECHAS[ev.key];
      if (!d || ev.altKey || ev.ctrlKey || ev.metaKey) return;
      ev.preventDefault();
      const paso = REJILLA * (ev.shiftKey ? 8 : 2);
      mover(clave, pos[clave][0] + d[0] * paso, pos[clave][1] + d[1] * paso);
      guardar(movidas);
      b.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
    fichas.set(clave, b);
    plano.append(b);
    return b;
  }

  function pintar(dados) {
    if (arrastre) { pendiente = dados; return; }  // una consulta a medio arrastre no le quita la ficha a nadie
    nodosDados = dados;
    ({ aristas: flechas, nodos } = aristas(dados));
    pos = { ...acomodar(nodos, flechas, marco.clientWidth) };
    for (const n of nodos) if (movidas[n.clave]) pos[n.clave] = movidas[n.clave];
    const vivas = new Set(nodos.map(n => n.clave));
    for (const [c, b] of fichas) if (!vivas.has(c)) { b.remove(); fichas.delete(c); }
    for (const n of nodos) {
      const b = fichas.get(n.clave) || ficha(n.clave);
      const usa = flechas.filter(f => f.a === n.clave).map(f => nodo(f.de).titulo);
      b.classList.toggle("con-mal", n.mal);
      b.classList.toggle("hueca", !n.maquina);
      b.title = `${n.titulo}: ${n.estado}`;
      b.setAttribute("aria-label", [n.titulo, n.bajo, n.estado, usa.length ? `usa ${usa.join(", ")}` : null].filter(Boolean).join(", "));
      b.replaceChildren(el("span", { class: "bajo" }, n.bajo), el("b", {}, n.titulo), el("span", { class: `estado ${n.clase}` }, n.estado));
      colocar(n.clave);
    }
    if (elegida && !vivas.has(elegida)) elegida = null;
    elegir(elegida);
  }

  return { raiz, pintar, elegir };
}

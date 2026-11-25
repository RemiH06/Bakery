// Máquinas de Bakery, una a la vez (menú arriba): a la izquierda cada recurso con su gráfica chica, como en el
// rendimiento del Administrador de tareas; a la derecha la gráfica grande del elegido con sus datos; abajo los
// servicios y, al lado, el log del que se pida. La máquina del panel responde por el panel; las demás, por su agente,
// al que el navegador llama directo (el servidor del panel no tiene permisos sobre otras máquinas).
// Arriba del menú va «Bakery»: todas las máquinas a la vez, con sus servicios y procesos agrupados por proyecto
// (Bakery > máquina > proyecto > proceso). El proyecto lo da el latido del proceso o `[proyecto]` del agente.
// Esa vista se ve como lista o como grafo (`v=grafo` en la URL, ver grafo.js).
import { api, el, hora, poner, svg } from "./util.js";
import * as grafo from "./grafo.js";

const CADA = 5000;    // ms entre consultas: lo mismo que tarda el agente en tomar otra muestra
const CADA_TODAS = 30000;  // la vista de todas pide cada máquina completa: más espaciado
const ESPERA = 8000;  // una máquina apagada no responde: no se espera más que esto
const TODAS = "*";    // valor del menú para la vista de Bakery completa
const VERBO = { iniciar: "Iniciar", detener: "Detener", reiniciar: "Reiniciar" };
const verbo = (v, s) => v === "iniciar" && s.proceso ? "Correr ya" : VERBO[v];  // un proceso se corre; un servicio se inicia
const CLASE = { activo: "e-analizado", bien: "e-analizado", arrancando: "e-pendiente", "deteniéndose": "e-pendiente",
  atrasado: "e-pendiente", "falló": "e-fallido", "no existe": "e-fallido" };
const MAL = new Set(["falló", "atrasado", "no existe"]);
const BASE = "bakery";  // lo que no tiene proyecto propio; va primero

// [[proyecto, servicios]], Bakery primero y luego por nombre
function porProyecto(servicios) {
  const grupos = new Map();
  for (const s of servicios) {
    const p = s.proyecto || BASE;
    grupos.set(p, [...(grupos.get(p) || []), s]);
  }
  return [...grupos].sort(([a], [b]) => (a === BASE ? -1 : b === BASE ? 1 : a.localeCompare(b, "es")));
}
const cuenta = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
function resumenDe(ss) {
  const procesos = ss.filter(s => s.proceso).length, servicios = ss.length - procesos;
  return [procesos && cuenta(procesos, "proceso", "procesos"), servicios && cuenta(servicios, "servicio", "servicios")].filter(Boolean).join(", ");
}
const insignia = (s) => el("span", { class: `insignia ${CLASE[s.estado] || ""}` }, s.estado);
// Un proceso dice cuándo terminó la última vez; un servicio, desde cuándo está en su estado
const cuando = (s) => s.desde ? el("span", { class: "tenue" }, `${s.proceso ? "última" : "desde"} ${hora(s.desde)}`) : null;
// Segundos como los diría alguien: «48 s», «3 min 5 s», «1 h 20 min»
function dura(s) {
  if (s < 60) return `${s} s`;
  if (s < 3600) return s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`;
  const m = Math.round(s / 60);
  return m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m / 60} h`;
}
const tardo = (s) => s.duracion_s == null ? null : `tardó ${dura(s.duracion_s)}`;
const motivoDe = (e) => e.name === "TimeoutError" ? "no respondió en 8 s: apagada, dormida o fuera del tailnet" : e.message;

// Cada recurso: de qué serie del historial sale, su tope y cómo se dice su valor
const RECURSOS = [
  { id: "cpu", nombre: "CPU", serie: "cpu", tope: 100, unidad: "%" },
  { id: "ram", nombre: "Memoria", serie: "ram", tope: 100, unidad: "%" },
  { id: "gpu", nombre: "GPU", serie: "gpu", tope: 100, unidad: "%" },
  { id: "vram", nombre: "VRAM", serie: "vram", tope: 100, unidad: "%" },
  { id: "temp_gpu", nombre: "Temperatura GPU", serie: "temp_gpu", tope: 100, unidad: "°C" },
  { id: "temp", nombre: "Temperatura", serie: "temp", tope: 90, unidad: "°C" },
];
const fmt = (v, u) => v == null ? "—" : `${Number.isInteger(v) ? v : v.toFixed(1)} ${u}`;

// Línea y área de una serie en un viewBox de 100 x 100 que se estira al contenedor; el trazo no se deforma
function trazo(valores, tope, conRejilla) {
  const s = svg("svg", { viewBox: "0 0 100 100", preserveAspectRatio: "none", class: "traza", "aria-hidden": "true" });
  if (conRejilla) for (const y of [25, 50, 75]) s.append(svg("line", { x1: 0, x2: 100, y1: y, y2: y, class: "rejilla", "vector-effect": "non-scaling-stroke" }));
  const n = valores.length;
  const pts = valores.map((v, i) => v == null ? null : [n > 1 ? (100 * i) / (n - 1) : 100, 100 - Math.min(100, (100 * v) / tope)]);
  // Un hueco (muestra sin dato) corta la línea en tramos
  let tramo = [];
  const cerrar = () => {
    if (tramo.length > 1) {
      const d = tramo.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join("");
      s.append(svg("path", { d: `${d}L${tramo.at(-1)[0].toFixed(2)},100L${tramo[0][0].toFixed(2)},100Z`, class: "area" }),
        svg("path", { d, class: "linea", "vector-effect": "non-scaling-stroke" }));
    }
    tramo = [];
  };
  for (const p of pts) p ? tramo.push(p) : cerrar();
  cerrar();
  return s;
}

export function crear(raiz, navegar) {
  let maquinas = null, estado = {}, datos = null, reloj = null, pedido = null;
  let logDe = null;  // lo que muestra la tarjeta de al lado: «log:servicio» o «corridas:servicio»
  const menu = el("select", { id: "maquina" });
  const sello = el("span", { class: "tenue", role: "status" });
  const lado = el("div", { class: "recursos", role: "group", "aria-label": "Recursos" });
  const grande = el("div", { class: "grafica-grande" });
  const detalle = el("dl", { class: "detalle" });
  const titulo = el("h3", { id: "rec-t" });
  const lista = el("div", { class: "pila" });
  const log = el("div", { class: "pila log-maquina" }, el("p", { class: "tenue" }, "Elige «Log» en un servicio para verlo aquí."));
  const avisoAccion = el("p", { class: "tenue", role: "status" });
  const todas = el("div", { class: "pila todas", "aria-label": "Bakery: todas las máquinas", hidden: true });
  let resultados = null;         // la última consulta de todas las máquinas: [máquina, datos, error]
  const vistos = new Map();      // máquina -> sus últimos datos: si deja de responder, sus fichas no desaparecen
  const detalleFicha = el("div", { class: "detalle-ficha" });
  const avisoGrafo = el("p", { class: "tenue", role: "status" });
  let firma = null;
  const dibujo = grafo.crear(pintarFicha);
  const vistaGrafo = el("section", { class: "tarjeta vista-grafo", "aria-label": "Grafo de Bakery", hidden: true },
    dibujo.raiz, el("div", { class: "pila" }, detalleFicha, avisoGrafo));
  const modos = el("div", { class: "fila", role: "group", "aria-label": "Vista" }, [["", "Lista"], ["grafo", "Grafo"]].map(([v, texto]) =>
    el("button", { type: "button", class: "boton", "data-v": v, onclick: () => navegar("maquinas", { ...estado, v }) }, texto)));
  const rendimiento = el("section", { class: "tarjeta rendimiento", "aria-labelledby": "rec-t" }, lado,
    el("div", { class: "principal" }, titulo, grande, detalle));
  const abajo = el("div", { class: "maq-abajo" },
    el("section", { class: "tarjeta", "aria-labelledby": "srv-t" }, el("h3", { id: "srv-t" }, "Servicios y procesos"), lista, avisoAccion),
    el("section", { class: "tarjeta", "aria-label": "Log" }, log));

  raiz.append(el("div", { class: "barra-maquinas" }, el("label", { for: "maquina" }, "Máquina"), menu, modos, sello), todas, vistaGrafo, rendimiento, abajo);
  menu.addEventListener("change", () => navegar("maquinas", { ...estado, m: menu.value }));

  const enTodas = () => (estado.m ?? TODAS) === TODAS;
  const enGrafo = () => enTodas() && estado.v === "grafo";
  const actual = () => maquinas?.find(m => m.nombre === estado.m) || maquinas?.[0];
  const pedir = (m, ruta, cuerpo, senal) => api(`${m.url}${ruta}`, cuerpo, senal || AbortSignal.timeout(cuerpo ? 120000 : ESPERA));

  // --- Recursos ---
  const disponibles = (d) => RECURSOS.filter(r => d.historial[r.serie]);
  function valorDe(r, d) {
    const h = d.historial[r.serie];
    return h[h.length - 1];
  }
  function subtitulo(r, d) {
    const x = d.recursos;
    if (r.id === "ram") return `${(x.ram_total_gb - x.ram_libre_gb).toFixed(1)} de ${x.ram_total_gb} GB`;
    if (r.id === "vram" && x.gpu) return `${x.gpu.vram_usada_gb} de ${x.gpu.vram_total_gb} GB`;
    if (r.id === "cpu") return `${x.nucleos} núcleos`;
    if (r.id === "gpu" && x.gpu) return x.gpu.nombre.replace(/^NVIDIA (GeForce )?/, "");
    return "";
  }

  function pintarLado(d) {
    const recursos = disponibles(d);
    const elegido = recursos.find(r => r.id === estado.r) || recursos[0];
    const x = d.recursos;
    const pct = 100 * (x.disco.total_gb - x.disco.libre_gb) / x.disco.total_gb;
    const barra = el("span", {});
    barra.style.width = `${pct}%`;  // por CSSOM: la CSP no deja atributos style
    poner(lado,
      recursos.map(r => el("button", { type: "button", class: "recurso", "aria-pressed": String(r === elegido),
        onclick: () => navegar("maquinas", { ...estado, r: r.id }) },
        el("span", { class: "mini" }, trazo(d.historial[r.serie], r.tope, false)),
        el("span", { class: "texto" }, el("b", {}, r.nombre), el("span", {}, fmt(valorDe(r, d), r.unidad)),
          el("span", { class: "tenue" }, subtitulo(r, d))))),
      // El disco no tiene serie (es capacidad, no actividad): solo su medidor
      el("div", { class: "recurso disco" },
        el("span", { class: "texto" }, el("b", {}, `Disco ${x.disco.montaje.replace(/\\$/, "")}`),
          el("span", {}, `${x.disco.libre_gb} GB libres`), el("span", { class: "tenue" }, `de ${x.disco.total_gb} GB`)),
        el("span", { class: `medidor${pct >= 90 ? " lleno" : ""}`, role: "img", "aria-label": `${Math.round(pct)} % ocupado` }, barra)));
    return elegido;
  }

  function pintarGrande(r, d) {
    const h = d.historial, valores = h[r.serie];
    const conDato = valores.filter(v => v != null);
    const max = conDato.length ? Math.max(...conDato) : null;
    const minutos = Math.round((h.t.length * h.cada) / 60);
    titulo.textContent = `${r.nombre} · ${fmt(valorDe(r, d), r.unidad)}`;
    const cruz = el("div", { class: "cruz", hidden: true });
    const punto = el("div", { class: "punto-cruz", hidden: true });
    const globo = el("div", { class: "globo", hidden: true, role: "status" });
    const lienzo = el("div", { class: "lienzo", role: "img",
      "aria-label": `${r.nombre}, últimos ${minutos} min: ahora ${fmt(valorDe(r, d), r.unidad)}, máximo ${fmt(max, r.unidad)}` },
      trazo(valores, r.tope, true), cruz, punto, globo);
    // Cursor: la muestra más cercana al puntero, con su valor y su hora
    const mover = (ev) => {
      const caja = lienzo.getBoundingClientRect();
      const n = valores.length;
      if (n < 2) return;
      const i = Math.round(Math.min(1, Math.max(0, (ev.clientX - caja.left) / caja.width)) * (n - 1));
      const x = (100 * i) / (n - 1), v = valores[i];
      cruz.hidden = punto.hidden = globo.hidden = false;
      cruz.style.left = punto.style.left = `${x}%`;
      punto.hidden = v == null;
      if (v != null) punto.style.top = `${100 - Math.min(100, (100 * v) / r.tope)}%`;
      globo.textContent = `${fmt(v, r.unidad)} · ${new Date(h.t[i] * 1000).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
      globo.style.left = `${Math.min(80, Math.max(0, x - 10))}%`;
    };
    lienzo.addEventListener("pointermove", mover);
    lienzo.addEventListener("pointerdown", mover);  // en el teléfono, tocar muestra el valor
    lienzo.addEventListener("pointerleave", () => { cruz.hidden = punto.hidden = globo.hidden = true; });
    poner(grande,
      el("div", { class: "eje-y", "aria-hidden": "true" }, el("span", {}, `${r.tope} ${r.unidad}`), el("span", {}, "0")),
      lienzo,
      el("div", { class: "eje-x", "aria-hidden": "true" }, el("span", {}, minutos ? `hace ${minutos} min` : "recién empezó"), el("span", {}, "ahora")));
    const x = d.recursos;
    const filas = [["Ahora", fmt(valorDe(r, d), r.unidad)], ["Máximo", fmt(max, r.unidad)],
      ["Promedio", conDato.length ? fmt(Math.round(10 * conDato.reduce((a, b) => a + b, 0) / conDato.length) / 10, r.unidad) : "—"]];
    if (r.id === "ram") filas.push(["Disponible", `${x.ram_libre_gb} GB`], ["Total", `${x.ram_total_gb} GB`]);
    if (r.id === "cpu") filas.push(["Núcleos", String(x.nucleos)]);
    if (["gpu", "vram", "temp_gpu"].includes(r.id) && x.gpu) filas.push(["Tarjeta", x.gpu.nombre], ["VRAM", `${x.gpu.vram_usada_gb} de ${x.gpu.vram_total_gb} GB`]);
    filas.push(["Encendida desde", hora(x.encendida_desde)]);
    poner(detalle, filas.map(([k, v]) => el("div", {}, el("dt", {}, k), el("dd", {}, v))));
  }

  // --- Servicios, log y órdenes ---
  async function actuar(m, ruta, cuerpo, pregunta, boton, aviso = avisoAccion) {
    if (pregunta && !confirm(pregunta)) return;
    boton.disabled = true;
    aviso.className = "tenue";
    aviso.textContent = "Trabajando…";
    try {
      await pedir(m, ruta, cuerpo);
      aviso.textContent = `Listo (${hora(new Date().toISOString())}).`;
      enTodas() ? consultarTodas() : consultar();
    } catch (e) {
      aviso.className = "error";
      aviso.textContent = `No se pudo: ${e.message}`;
    } finally { boton.disabled = false; }
  }

  function alLado(clave, texto, otraVez) {
    logDe = clave;
    for (const b of lista.querySelectorAll("[data-ver]")) b.setAttribute("aria-pressed", String(b.dataset.ver === clave));
    poner(log, el("div", { class: "fila" }, el("h3", {}, texto),
      el("button", { type: "button", class: "boton", onclick: otraVez }, "Actualizar")),
      el("p", { class: "tenue" }, "Cargando…"));
  }

  async function verCorridas(m, servicio) {
    const clave = `corridas:${servicio}`;
    alLado(clave, `Corridas de ${servicio}`, () => verCorridas(m, servicio));
    try {
      const d = await pedir(m, `/api/corridas?${new URLSearchParams({ servicio })}`);
      if (logDe === clave) log.lastChild.replaceWith(tablaCorridas(d.corridas));
    } catch (e) { if (logDe === clave) log.lastChild.replaceWith(el("p", { class: "error" }, e.message)); }
  }

  function tablaCorridas(cs) {
    if (!cs.length) return el("p", { class: "tenue" }, "Todavía no hay corridas guardadas: la siguiente aparece aquí.");
    const ds = cs.map(c => c.duracion_s).filter(d => d != null).sort((a, b) => a - b);
    const fallas = cs.filter(c => c.codigo).length, max = ds.at(-1) || 1;
    const resumen = [cuenta(cs.length, "corrida", "corridas"), fallas ? cuenta(fallas, "falla", "fallas") : "sin fallas",
      ds.length ? `duración: mediana ${dura(ds[Math.floor((ds.length - 1) / 2)])}, máxima ${dura(ds.at(-1))}` : null];
    return el("div", { class: "pila" }, el("p", { class: "tenue" }, resumen.filter(Boolean).join(" · ")),
      el("div", { class: "corridas", tabindex: "0", role: "region", "aria-label": "Últimas corridas" }, el("table", {},
        el("thead", {}, el("tr", {}, ["Terminó", "Resultado", "Duración", "Resumen"].map(t => el("th", { scope: "col" }, t)))),
        el("tbody", {}, cs.map(c => {
          const barra = el("span", {});
          barra.style.width = `${100 * (c.duracion_s ?? 0) / max}%`;  // por CSSOM: la CSP no deja atributos style
          return el("tr", {}, el("td", {}, hora(c.fin)),
            el("td", {}, el("span", { class: `insignia ${CLASE[c.codigo ? "falló" : "bien"]}` }, c.codigo ? `código ${c.codigo}` : "bien")),
            el("td", {}, c.duracion_s == null ? "—" : [dura(c.duracion_s), el("span", { class: "medidor", "aria-hidden": "true" }, barra)]),
            el("td", {}, c.resumen));
        })))));
  }

  async function verLog(m, servicio) {
    const clave = `log:${servicio}`;
    alLado(clave, `Log de ${servicio}`, () => verLog(m, servicio));
    try {
      const d = await pedir(m, `/api/log?${new URLSearchParams({ servicio })}`);
      if (logDe !== clave) return;
      const pre = el("pre", { tabindex: "0" }, d.renglones.length ? d.renglones.join("\n") : "(vacío)");
      log.lastChild.replaceWith(pre);
      pre.scrollTop = pre.scrollHeight;  // lo último, abajo, como en una terminal
    } catch (e) { if (logDe === clave) log.lastChild.replaceWith(el("p", { class: "error" }, e.message)); }
  }

  function pintarServicios(m, d) {
    const fila = (s) => el("li", {},
      el("div", { class: "fila" }, insignia(s), el("b", {}, s.nombre), cuando(s)),
      el("span", { class: "tenue" }, [s.detalle, tardo(s), s.siguiente ? `siguiente: ${hora(s.siguiente)}` : null].filter(Boolean).join(" · ")),
      el("div", { class: "fila" },
        ...(s.controlable ? Object.keys(VERBO).filter(v => (v === "iniciar") !== (s.estado === "activo")).map(v => {
          const texto = verbo(v, s);
          const b = el("button", { type: "button", class: "boton", "aria-label": `${texto} ${s.nombre}` }, texto);
          b.addEventListener("click", () => actuar(m, "/api/accion", { servicio: s.nombre, accion: v },
            v === "iniciar" ? null : `¿${texto} ${s.nombre} en ${m.nombre}?`, b));
          return b;
        }) : []),
        s.proceso ? el("button", { type: "button", class: "boton", "data-ver": `corridas:${s.nombre}`,
          "aria-pressed": String(logDe === `corridas:${s.nombre}`), "aria-label": `Corridas de ${s.nombre}`,
          onclick: () => verCorridas(m, s.nombre) }, "Corridas") : null,
        el("button", { type: "button", class: "boton", "data-ver": `log:${s.nombre}`,
          "aria-pressed": String(logDe === `log:${s.nombre}`), "aria-label": `Log de ${s.nombre}`,
          onclick: () => verLog(m, s.nombre) }, "Log")));
    const grupos = porProyecto(d.servicios).map(([p, ss]) => el("section", { class: "proyecto", "aria-label": `Proyecto ${p}` },
      el("h4", {}, p, el("span", { class: "tenue" }, ` · ${resumenDe(ss)}`)), el("ul", { class: "items" }, ss.map(fila))));
    const ordenes = d.ordenes.length ? el("div", { class: "fila" }, el("span", { class: "tenue" }, "Órdenes:"), d.ordenes.map(o => {
      const b = el("button", { type: "button", class: "boton" }, o);
      b.addEventListener("click", () => actuar(m, "/api/orden", { orden: o }, `¿Correr «${o}» en ${m.nombre}?`, b));
      return b;
    })) : null;
    poner(lista, grupos.length ? grupos : el("p", { class: "tenue" }, "Sin servicios ni procesos en esta máquina."), ordenes);
  }

  // --- Bakery: todas las máquinas, por proyecto ---
  function pintarTodas() {
    poner(todas, resultados.map(([m, d, e]) => el("section", { class: "tarjeta", "aria-label": m.nombre },
      el("div", { class: "fila" }, el("h3", {}, m.nombre),
        el("span", { class: d ? "tenue" : "error" }, d ? `${d.sistema} · ${new Date(d.hora).toLocaleTimeString("es-MX")}` : `sin respuesta: ${motivoDe(e)}`),
        el("button", { type: "button", class: "boton", onclick: () => navegar("maquinas", { ...estado, m: m.nombre }) }, `Abrir ${m.nombre}`)),
      d ? porProyecto(d.servicios).map(([p, ss]) => {
        const malos = ss.filter(s => MAL.has(s.estado)).length;
        // Cerrado si todo está bien: lo que pide atención se ve sin abrir nada
        return el("details", { class: "proyecto", open: malos > 0 },
          el("summary", {}, el("b", {}, p), ` · ${resumenDe(ss)} `,
            malos ? el("span", { class: "insignia e-fallido" }, cuenta(malos, "pide atención", "piden atención")) : null),
          el("ul", { class: "items" }, ss.map(s => el("li", {},
            el("div", { class: "fila" }, insignia(s), el("b", {}, s.proceso || s.nombre), cuando(s)),
            el("span", { class: "tenue" }, [s.proceso ? s.nombre : null, s.detalle, tardo(s)].filter(Boolean).join(" · "))))));
      }) : null)));
  }

  // --- Bakery como grafo ---
  function pintarGrafo() {
    const nodos = resultados.flatMap(([m, d]) => {
      const visto = d || vistos.get(m.nombre);
      return visto ? porProyecto(visto.servicios).flatMap(([p, ss]) => ss.map(s => ({
        clave: `${m.nombre}/${s.nombre}`, ids: [s.proceso && `${p}.${s.proceso}`, `${p}.${s.nombre}`].filter(Boolean), maquina: m.nombre, m, s,
        titulo: s.proceso || s.nombre, bajo: `${p} · ${m.nombre}`, estado: d ? s.estado : "sin respuesta",
        clase: d ? CLASE[s.estado] || "" : "e-pendiente", mal: !d || MAL.has(s.estado), usa: s.usa || [] }))) : [];
    });
    dibujo.pintar(nodos);
  }

  // Los datos de la ficha elegida. Solo se rehace si cambió algo: cada consulta le quitaría el foco a sus botones
  function pintarFicha(n, lados) {
    const ahora = JSON.stringify(n && [n, lados.usa.map(x => x.clave), lados.loUsan.map(x => x.clave)]);
    if (ahora === firma) return;
    firma = ahora;
    const conFoco = detalleFicha.contains(document.activeElement) ? document.activeElement.textContent : null;
    if (!n) return poner(detalleFicha, el("p", { class: "tenue" }, "Elige una ficha para ver sus datos."));
    const { m, s } = n;
    const ir = (xs) => xs.length ? xs.map(x => el("button", { type: "button", class: "boton", onclick: () => dibujo.elegir(x.clave, true) }, x.titulo))
      : el("span", { class: "tenue" }, "nada declarado");
    let correr = null;
    if (s?.controlable && s.proceso && s.estado !== "activo" && n.estado !== "sin respuesta") {
      correr = el("button", { type: "button", class: "boton primario" }, "Correr ya");
      correr.addEventListener("click", () => actuar(m, "/api/accion", { servicio: s.nombre, accion: "iniciar" },
        `¿Correr ${n.titulo} en ${m.nombre}?`, correr, avisoGrafo));
    }
    poner(detalleFicha,
      el("div", { class: "fila" }, el("span", { class: `insignia ${n.clase}` }, n.estado), el("h3", {}, n.titulo), el("span", { class: "tenue" }, n.bajo)),
      s ? el("p", { class: "tenue" }, [s.proceso ? s.nombre : null, s.detalle, tardo(s), s.desde ? cuando(s).textContent : null].filter(Boolean).join(" · "))
        : el("p", { class: "tenue" }, "Alguien declaró que lo usa, pero ninguna máquina lo reporta: el nombre cambió, o su máquina está apagada."),
      el("div", { class: "fila" }, el("span", { class: "tenue" }, "Usa:"), ir(lados.usa)),
      el("div", { class: "fila" }, el("span", { class: "tenue" }, "Lo usan:"), ir(lados.loUsan)),
      m ? el("div", { class: "fila" }, correr,
        el("button", { type: "button", class: "boton", onclick: () => navegar("maquinas", { ...estado, m: m.nombre }) }, `Abrir ${m.nombre}`)) : null);
    if (conFoco) [...detalleFicha.querySelectorAll("button")].find(b => b.textContent === conFoco)?.focus();
  }

  function pintarBakery() {
    if (!resultados) return;
    enGrafo() ? pintarGrafo() : pintarTodas();
    const mudas = resultados.filter(([, d]) => !d).map(([m]) => m.nombre);
    sello.className = mudas.length ? "error" : "tenue";
    sello.textContent = `actualizado ${new Date().toLocaleTimeString("es-MX")}${mudas.length ? ` · sin respuesta: ${mudas.join(", ")}` : ""}`;
  }

  async function consultarTodas() {
    const lote = maquinas;
    const llegan = await Promise.all(lote.map(m => pedir(m, "/api/maquina").then(d => [m, d], e => [m, null, e])));
    if (!enTodas() || lote !== maquinas) return;
    resultados = llegan;
    for (const [m, d] of llegan) if (d) vistos.set(m.nombre, d);
    pintarBakery();
  }

  function pintar(m, d) {
    sello.textContent = `${d.sistema} · actualizado ${new Date(d.hora).toLocaleTimeString("es-MX")}`;
    pintarGrande(pintarLado(d), d);
    pintarServicios(m, d);
  }

  async function consultar() {
    const m = actual();
    if (!m) return;
    pedido?.abort();
    pedido = new AbortController();
    const senal = AbortSignal.any([pedido.signal, AbortSignal.timeout(ESPERA)]);
    try {
      const d = await pedir(m, "/api/maquina", null, senal);
      if (m !== actual()) return;
      datos = d;
      pintar(m, d);
    } catch (e) {
      if (e.name === "AbortError") return;
      sello.textContent = `sin respuesta: ${motivoDe(e)}`;
      sello.className = "error";
      if (!datos) poner(lado, el("p", { class: "error" }, `Sin datos de ${m.nombre}.`));
      return;
    }
    sello.className = "tenue";
  }

  async function vuelta() {
    if (raiz.hidden || document.hidden) return;
    await (enTodas() ? consultarTodas() : consultar());
  }

  return {
    async mostrar(params) {
      const antes = estado;
      estado = params;
      if (!maquinas) {
        try {
          const d = await api("/api/maquinas");
          maquinas = [{ nombre: d.local, url: "" }, ...Object.entries(d.agentes).map(([nombre, url]) => ({ nombre, url }))];
        } catch (e) { sello.textContent = `Sin lista de máquinas: ${e.message}`; return; }
        menu.replaceChildren(el("option", { value: TODAS }, "Bakery (todas)"), ...maquinas.map(m => el("option", { value: m.nombre }, m.nombre)));
      }
      clearInterval(reloj);
      const vistaTodas = enTodas();
      modos.hidden = !vistaTodas;
      todas.hidden = !vistaTodas || enGrafo();
      vistaGrafo.hidden = !enGrafo();
      for (const b of modos.children) b.setAttribute("aria-pressed", String((b.dataset.v === "grafo") === enGrafo()));
      rendimiento.hidden = abajo.hidden = vistaTodas;
      if (vistaTodas) {
        menu.value = TODAS;
        datos = null;
        if (!todas.childElementCount) poner(todas, el("p", { class: "tenue" }, "Consultando todas las máquinas…"));
        // Cambiar de lista a grafo no espera otra consulta; la hora del sello sí se corrige al llegar
        if (resultados) enGrafo() ? pintarGrafo() : pintarTodas();
        consultarTodas();
        reloj = setInterval(vuelta, CADA_TODAS);
        return;
      }
      menu.value = actual().nombre;
      if (antes.m !== estado.m || !datos) {  // otra máquina: nada de lo de la anterior se queda a la vista
        datos = null; logDe = null;
        poner(lado, el("p", { class: "tenue" }, "Consultando…")); grande.replaceChildren(); detalle.replaceChildren(); lista.replaceChildren();
        titulo.textContent = actual().nombre; avisoAccion.textContent = "";
        poner(log, el("p", { class: "tenue" }, "Elige «Log» en un servicio para verlo aquí."));
        consultar();
      } else if (datos) pintar(actual(), datos);  // solo cambió el recurso elegido
      reloj = setInterval(vuelta, CADA);  // `vuelta` no hace nada con la hoja oculta
    },
  };
}

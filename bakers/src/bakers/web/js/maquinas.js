// Máquinas de Bakery, una a la vez (menú arriba): a la izquierda cada recurso con su gráfica chica, como en el
// rendimiento del Administrador de tareas; a la derecha la gráfica grande del elegido con sus datos; abajo los
// servicios y, al lado, el log del que se pida. La máquina del panel responde por el panel; las demás, por su agente,
// al que el navegador llama directo (el servidor del panel no tiene permisos sobre otras máquinas).
import { api, el, hora, poner } from "./util.js";

const CADA = 5000;    // ms entre consultas: lo mismo que tarda el agente en tomar otra muestra
const ESPERA = 8000;  // una máquina apagada no responde: no se espera más que esto
const VERBO = { iniciar: "Iniciar", detener: "Detener", reiniciar: "Reiniciar" };
const CLASE = { activo: "e-analizado", arrancando: "e-pendiente", "deteniéndose": "e-pendiente", "falló": "e-fallido", "no existe": "e-fallido" };
const SVG = "http://www.w3.org/2000/svg";

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

function svg(tag, attrs = {}) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

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
  let maquinas = null, estado = {}, datos = null, reloj = null, pedido = null, logDe = null;
  const menu = el("select", { id: "maquina" });
  const sello = el("span", { class: "tenue", role: "status" });
  const lado = el("div", { class: "recursos", role: "group", "aria-label": "Recursos" });
  const grande = el("div", { class: "grafica-grande" });
  const detalle = el("dl", { class: "detalle" });
  const titulo = el("h3", { id: "rec-t" });
  const lista = el("div", { class: "pila" });
  const log = el("div", { class: "pila log-maquina" }, el("p", { class: "tenue" }, "Elige «Log» en un servicio para verlo aquí."));
  const avisoAccion = el("p", { class: "tenue", role: "status" });

  raiz.append(
    el("div", { class: "barra-maquinas" }, el("label", { for: "maquina" }, "Máquina"), menu, sello),
    el("section", { class: "tarjeta rendimiento", "aria-labelledby": "rec-t" }, lado,
      el("div", { class: "principal" }, titulo, grande, detalle)),
    el("div", { class: "maq-abajo" },
      el("section", { class: "tarjeta", "aria-labelledby": "srv-t" }, el("h3", { id: "srv-t" }, "Servicios"), lista, avisoAccion),
      el("section", { class: "tarjeta", "aria-label": "Log" }, log)));
  menu.addEventListener("change", () => navegar("maquinas", { m: menu.value, r: estado.r }));

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
        onclick: () => navegar("maquinas", { m: estado.m, r: r.id }) },
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
  async function actuar(m, ruta, cuerpo, pregunta, boton) {
    if (pregunta && !confirm(pregunta)) return;
    boton.disabled = true;
    avisoAccion.className = "tenue";
    avisoAccion.textContent = "Trabajando…";
    try {
      await pedir(m, ruta, cuerpo);
      avisoAccion.textContent = `Listo (${hora(new Date().toISOString())}).`;
      consultar();
    } catch (e) {
      avisoAccion.className = "error";
      avisoAccion.textContent = `No se pudo: ${e.message}`;
    } finally { boton.disabled = false; }
  }

  async function verLog(m, servicio) {
    logDe = servicio;
    poner(log, el("div", { class: "fila" }, el("h3", {}, `Log de ${servicio}`),
      el("button", { type: "button", class: "boton", onclick: () => verLog(m, servicio) }, "Actualizar")),
      el("p", { class: "tenue" }, "Cargando…"));
    try {
      const d = await pedir(m, `/api/log?${new URLSearchParams({ servicio })}`);
      if (logDe !== servicio) return;
      const pre = el("pre", { tabindex: "0" }, d.renglones.length ? d.renglones.join("\n") : "(vacío)");
      log.lastChild.replaceWith(pre);
      pre.scrollTop = pre.scrollHeight;  // lo último, abajo, como en una terminal
    } catch (e) { log.lastChild.replaceWith(el("p", { class: "error" }, e.message)); }
  }

  function pintarServicios(m, d) {
    const filas = d.servicios.map(s => el("li", {},
      el("div", { class: "fila" }, el("span", { class: `insignia ${CLASE[s.estado] || ""}` }, s.estado), el("b", {}, s.nombre),
        s.desde ? el("span", { class: "tenue" }, `desde ${hora(s.desde)}`) : null),
      el("span", { class: "tenue" }, [s.detalle, s.siguiente ? `siguiente: ${hora(s.siguiente)}` : null].filter(Boolean).join(" · ")),
      el("div", { class: "fila" },
        ...(s.controlable ? Object.entries(VERBO).filter(([v]) => (v === "iniciar") !== (s.estado === "activo")).map(([v, texto]) => {
          const b = el("button", { type: "button", class: "boton", "aria-label": `${texto} ${s.nombre}` }, texto);
          b.addEventListener("click", () => actuar(m, "/api/accion", { servicio: s.nombre, accion: v },
            v === "iniciar" ? null : `¿${texto} ${s.nombre} en ${m.nombre}?`, b));
          return b;
        }) : []),
        el("button", { type: "button", class: "boton", "aria-pressed": String(logDe === s.nombre), "aria-label": `Log de ${s.nombre}`,
          onclick: () => verLog(m, s.nombre) }, "Log"))));
    const ordenes = d.ordenes.length ? el("div", { class: "fila" }, el("span", { class: "tenue" }, "Órdenes:"), d.ordenes.map(o => {
      const b = el("button", { type: "button", class: "boton" }, o);
      b.addEventListener("click", () => actuar(m, "/api/orden", { orden: o }, `¿Correr «${o}» en ${m.nombre}?`, b));
      return b;
    })) : null;
    poner(lista, d.servicios.length ? el("ul", { class: "items" }, filas) : el("p", { class: "tenue" }, "Sin servicios en la lista de esta máquina."), ordenes);
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
      const motivo = e.name === "TimeoutError" ? "no respondió en 8 s: apagada, dormida o fuera del tailnet" : e.message;
      sello.textContent = `sin respuesta: ${motivo}`;
      sello.className = "error";
      if (!datos) poner(lado, el("p", { class: "error" }, `Sin datos de ${m.nombre}.`));
      return;
    }
    sello.className = "tenue";
  }

  async function vuelta() {
    if (raiz.hidden || document.hidden) return;
    await consultar();
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
        menu.replaceChildren(...maquinas.map(m => el("option", { value: m.nombre }, m.nombre)));
      }
      menu.value = actual().nombre;
      if (antes.m !== estado.m || !datos) {  // otra máquina: nada de lo de la anterior se queda a la vista
        datos = null; logDe = null;
        poner(lado, el("p", { class: "tenue" }, "Consultando…")); grande.replaceChildren(); detalle.replaceChildren(); lista.replaceChildren();
        titulo.textContent = actual().nombre; avisoAccion.textContent = "";
        poner(log, el("p", { class: "tenue" }, "Elige «Log» en un servicio para verlo aquí."));
        consultar();
      } else if (datos) pintar(actual(), datos);  // solo cambió el recurso elegido
      clearInterval(reloj);
      reloj = setInterval(vuelta, CADA);  // `vuelta` no hace nada con la hoja oculta
    },
  };
}

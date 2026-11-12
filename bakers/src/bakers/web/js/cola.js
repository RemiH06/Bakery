// La cola de reels: indicadores y el camino de una pieza (que filtra), pegar enlaces o un texto, reintentar,
// y en pestañas las piezas y el registro (logs y errores de descarga).
import { api, el, enlace, hora, teclasPestanas } from "./util.js";

const ESTADOS = ["fallido", "bajado", "clasificar", "pendiente", "analizado", "usado"];

export function crear(raiz, refrescar) {
  let ultimo = null, filtro = "todos";
  const resumen = el("div", { class: "indicadores" });
  const texto = el("textarea", { id: "texto", required: true, placeholder: "https://www.instagram.com/reel/… o un texto" });
  const seccion = el("input", { id: "seccion", list: "secciones", autocomplete: "off" });
  const secciones = el("datalist", { id: "secciones" });
  const aviso = el("span", { id: "aviso", role: "status" });
  const cajaFallidos = el("section", { class: "tarjeta", "aria-labelledby": "t-fallidos", hidden: true },
    el("h3", { id: "t-fallidos" }, "Fallidos"));
  const reintentos = el("div", { class: "fila" });
  cajaFallidos.append(reintentos);
  const filtros = el("div", { class: "fila", role: "group", "aria-label": "Filtrar por estado" });
  const buscar = el("input", { id: "buscar-cola", type: "search", autocomplete: "off", placeholder: "código, clase, sección, nota o error" });
  const cuantas = el("p", { class: "cuantas" });
  const items = el("ul", { class: "items" });
  const registro = el("div");

  const avisar = (t, error = false) => { aviso.textContent = t; aviso.className = error ? "error" : "tenue"; };

  const form = el("form", { class: "pila", onsubmit: async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("/api/agregar", { texto: texto.value, seccion: seccion.value });
      if (r.bandeja) {
        avisar(`Guardado en la bandeja: ${r.bandeja}. Llega a la bóveda en la siguiente vuelta (10 min a lo más).`);
        texto.value = "";
        return;
      }
      const partes = [`${r.agregados} agregados`, r.repetidos && `${r.repetidos} ya estaban`, r.ya_bajados && `${r.ya_bajados} ya bajados`, r.sin_enlace && `${r.sin_enlace} renglones sin enlace`];
      avisar(partes.filter(Boolean).join(", ") + `. En cola: ${r.en_cola}.`);
      if (r.agregados) texto.value = "";
      refrescar();
    } catch (e) { avisar(e.message, true); }
  } },
    el("label", { for: "texto", class: "ayuda" }, "Enlaces: uno o varios, uno por renglón. Lo que va antes del enlace (\"Osiris: https://…\") se guarda como etiqueta, y un renglón \"# Política\" cambia la sección. Un texto sin ningún enlace (poema, aforismo, idea) se guarda completo y tal cual en la bandeja de la bóveda."),
    texto,
    el("label", { for: "seccion", class: "ayuda" }, "Sección (opcional): la pista del clasificador o, para un texto, a dónde crees que va"),
    seccion, secciones,
    el("div", { class: "fila" }, el("button", { class: "boton primario", type: "submit" }, "Guardar"), aviso));

  const camino = el("ol", { class: "camino", "aria-label": "Piezas por estado, en el orden en que avanzan" });
  // Piezas y Registro son pestañas de la misma tarjeta: no se ven a la vez
  const panelPiezas = el("div", { class: "pila", id: "cola-piezas", role: "tabpanel", "aria-labelledby": "tab-piezas" },
    filtros, el("label", { for: "buscar-cola", class: "sr-only" }, "Buscar piezas"), buscar, cuantas, items);
  const panelRegistro = el("div", { id: "cola-registro", role: "tabpanel", "aria-labelledby": "tab-registro", hidden: true }, registro);
  const pestanas = el("div", { class: "pestanas pestanas-cola", role: "tablist", "aria-label": "Piezas o registro" },
    ...[["piezas", "Piezas"], ["registro", "Registro"]].map(([id, t]) => el("button", { type: "button", role: "tab", class: "pestana",
      id: `tab-${id}`, "data-hoja": id, "aria-controls": `cola-${id}`, onclick: () => verHoja(id) }, t)));
  teclasPestanas(pestanas, (t) => verHoja(t.dataset.hoja));

  function verHoja(id) {
    for (const t of pestanas.children) {
      const activa = t.dataset.hoja === id;
      t.setAttribute("aria-selected", String(activa)); t.tabIndex = activa ? 0 : -1;
    }
    panelPiezas.hidden = id !== "piezas"; panelRegistro.hidden = id !== "registro";
  }
  verHoja("piezas");

  raiz.append(
    el("section", { class: "tarjeta", "aria-labelledby": "t-resumen" }, el("h3", { id: "t-resumen" }, "Ahora"), resumen, camino),
    el("section", { class: "tarjeta", "aria-labelledby": "t-agregar" }, el("h3", { id: "t-agregar" }, "Agregar enlaces o un texto"), form),
    cajaFallidos,
    el("section", { class: "tarjeta tarjeta-pestanas", "aria-label": "Piezas y registro" }, pestanas, panelPiezas, panelRegistro));
  buscar.addEventListener("input", () => ultimo && pintarItems(ultimo));

  function indicador(rotulo, valor, sub, extra) {
    return el("div", { class: "indicador" }, el("span", { class: "rotulo" }, rotulo), el("b", { class: "valor" }, valor),
      sub ? el("span", { class: "sub" }, sub) : null, extra);
  }

  function pintarResumen(d) {
    const r = d.resumen, c = r.conteo;
    const enPausa = r.proximo && new Date(r.proximo) > new Date();
    const pct = Math.min(100, Math.round(100 * r.bajados_hoy / d.tope));
    const medidor = el("span", { class: "medidor", role: "img", "aria-label": `${pct} % del tope del día` }, el("span", {}));
    medidor.firstChild.style.width = `${pct}%`;
    const fallidos = c.fallido || 0;
    resumen.replaceChildren(
      // El panel no sabe todavía si la tarea `cola` corre (fase 3): solo dice si la cola tiene una pausa
      indicador("Descargas", enPausa ? "En pausa" : "Sin pausa",
        enPausa ? `${r.motivo}; sigue ${hora(r.proximo)}` : "si la tarea corre, baja de 9:00 a 22:59 con 5 a 15 min entre una y otra"),
      indicador("Bajadas hoy", `${r.bajados_hoy} de ${d.tope}`, r.bajados_hoy >= d.tope ? "tope lleno: sigue mañana" : null, medidor),
      indicador("Disco", `${d.libre_gb} GB libres`, `analizar pide ${d.min_libre} GB`),
      indicador("Fallidos", String(fallidos), fallidos ? "se reintentan abajo" : "ninguno",
        fallidos ? el("button", { type: "button", class: "boton", "aria-pressed": String(filtro === "fallido"),
          onclick: () => { filtro = filtro === "fallido" ? "todos" : "fallido"; verHoja("piezas"); pintar(); } }, "Ver cuáles") : null));
    resumen.lastChild.classList.toggle("alerta", !!fallidos);
    // El camino de una pieza, sin los fallidos (ya tienen su indicador): cada paso filtra la lista
    const pasos = ["pendiente", "bajado", "clasificar", "analizado", "usado"];
    camino.replaceChildren(...pasos.map(e => el("li", {},
      el("button", { type: "button", class: `paso e-${e}`, "aria-pressed": String(filtro === e),
        onclick: () => { filtro = filtro === e ? "todos" : e; verHoja("piezas"); pintar(); } },
        el("span", { class: "punto", "aria-hidden": "true" }), el("span", {}, e), el("b", {}, String(c[e] || 0))))));
  }

  function pintarFallidos(d) {
    const n = d.resumen.conteo.fallido || 0;
    cajaFallidos.hidden = !n;
    const botones = [["todos", null], ["enlaces rotos", "enlace"], ["bloqueos", "bloqueo"], ["análisis", "analisis"]];
    reintentos.replaceChildren(el("span", { class: "tenue" }, `Reintentar ${n}:`),
      ...botones.map(([t, tipo]) => el("button", { type: "button", class: "boton", onclick: async () => {
        try { const res = await api("/api/reintentar", { tipo }); avisar(`${res.reintentados} de vuelta a la cola`); refrescar(); }
        catch (e) { avisar(e.message, true); }
      } }, t)));
  }

  // El filtro se elige arriba (el camino y el indicador de fallidos); aquí solo se dice cuál está puesto
  function pintarFiltros() {
    filtros.replaceChildren(el("span", { class: "tenue" }, filtro === "todos" ? "Todas las piezas. Un paso del camino de arriba filtra por estado."
      : `Solo «${filtro}».`),
      filtro === "todos" ? null : el("button", { type: "button", class: "boton", onclick: () => { filtro = "todos"; pintar(); } }, "Ver todas"));
  }

  function pintarItems(d) {
    const q = buscar.value.trim().toLowerCase();
    const orden = Object.fromEntries(ESTADOS.map((e, i) => [e, i]));
    const lista = d.items.map((it, i) => ({ ...it, i }))
      .filter(it => filtro === "todos" || it.estado === filtro)
      .filter(it => !q || [it.clave, it.clase, it.seccion, it.etiqueta, it.nota, it.error, it.url].some(x => (x || "").toLowerCase().includes(q)))
      .sort((a, b) => (orden[a.estado] - orden[b.estado]) || (b.i - a.i));  // lo más nuevo primero
    cuantas.textContent = `${lista.length} piezas` + (lista.length > 300 ? " (se muestran 300; filtra o busca)" : "");
    items.replaceChildren(...lista.slice(0, 300).map(it => {
      const pista = [it.seccion, it.etiqueta].filter(Boolean).join(" / ");
      const intentos = [it.intentos ? `${it.intentos} bloqueos` : "", it.intentos_analisis ? `${it.intentos_analisis} análisis fallidos` : ""].filter(Boolean).join(", ");
      const nota = it.nota ? el("a", { href: `#inspo?${new URLSearchParams({ n: it.nota })}` }, it.nota) : null;
      return el("li", {},
        el("div", { class: "fila" }, el("span", { class: `insignia e-${it.estado}` }, it.estado), enlace(it.url, it.clave),
          it.clase ? el("span", { class: "insignia" }, it.clase) : null),
        pista ? el("span", { class: "tenue" }, `Sección: ${pista}`) : null,
        nota && it.estado !== "usado" ? el("span", { class: "tenue" }, "Nota: ", nota) : it.nota ? el("span", { class: "tenue" }, `Nota: ${it.nota}`) : null,
        intentos ? el("span", { class: "tenue" }, intentos) : null,
        it.error ? el("span", { class: "error" }, it.error) : null);
    }));
  }

  function pintarRegistro(d) {
    const abiertos = new Set([...registro.querySelectorAll("details[open]")].map(x => x.dataset.nombre));
    const caja = (nombre, titulo, t) => el("details", { "data-nombre": nombre, open: abiertos.has(nombre) }, el("summary", {}, titulo), el("pre", {}, t));
    const bloques = Object.entries(d.logs).map(([n, lineas]) => caja(n, `${n}.log`, lineas.join("\n") || "vacío"));
    const errores = d.errores.map(e => `${hora(e.ts)}  ${e.tipo}  ${e.clave}\n  ${e.error.slice(-240)}`).join("\n");
    bloques.push(caja("errores", `errores de descarga (${d.errores.length} recientes)`, errores || "ninguno"));
    registro.replaceChildren(...bloques);
  }

  function pintar() {
    if (!ultimo) return;
    pintarResumen(ultimo); pintarFallidos(ultimo); pintarFiltros(ultimo); pintarItems(ultimo);
    const ss = [...new Set(ultimo.items.map(i => i.seccion).filter(Boolean))].sort();
    secciones.replaceChildren(...ss.map(s => el("option", { value: s })));
  }

  return {
    actualizar(d) { ultimo = d; pintar(); pintarRegistro(d); },
    mostrar() {},
    enfocar() { texto.focus(); },
  };
}

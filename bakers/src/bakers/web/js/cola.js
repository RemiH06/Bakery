// La cola de reels: lo mismo que el panel de antes (resumen, pegar enlaces o un texto, reintentar, piezas, registro).
import { api, el, enlace, hora } from "./util.js";

const ESTADOS = ["fallido", "bajado", "clasificar", "pendiente", "analizado", "usado"];

export function crear(raiz, refrescar) {
  let ultimo = null, filtro = "todos";
  const resumen = el("div", { class: "datos" });
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

  raiz.append(
    el("section", { class: "tarjeta", "aria-labelledby": "t-resumen" }, el("h3", { id: "t-resumen" }, "Ahora"), resumen),
    el("section", { class: "tarjeta", "aria-labelledby": "t-agregar" }, el("h3", { id: "t-agregar" }, "Agregar enlaces o un texto"), form),
    cajaFallidos,
    el("section", { class: "tarjeta", "aria-labelledby": "t-piezas" }, el("h3", { id: "t-piezas" }, "Piezas"),
      el("div", { class: "pila" }, filtros, el("label", { for: "buscar-cola", class: "sr-only" }, "Buscar piezas"), buscar, cuantas, items)),
    el("section", { class: "tarjeta", "aria-labelledby": "t-registro" }, el("h3", { id: "t-registro" }, "Registro"), registro));
  buscar.addEventListener("input", () => ultimo && pintarItems(ultimo));

  function pintarResumen(d) {
    const r = d.resumen, c = r.conteo;
    const pausa = r.proximo && new Date(r.proximo) > new Date() ? `${r.motivo}, sigue ${hora(r.proximo)}` : "bajando";
    const datos = [
      [d.marcha, "marcha (analizar solo en alta)"],
      [`${r.bajados_hoy} de ${d.tope}`, "bajados hoy"],
      [pausa, "descargas"],
      [`${d.libre_gb} GB`, `libres (mínimo ${d.min_libre})`],
      ...ESTADOS.map(e => [c[e] || 0, e]),
    ];
    resumen.replaceChildren(...datos.map(([v, t]) => el("div", { class: "dato" }, el("b", {}, String(v)), el("span", {}, t))));
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

  function pintarFiltros(d) {
    const c = d.resumen.conteo;
    filtros.replaceChildren(...[["todos", d.items.length], ...ESTADOS.map(e => [e, c[e] || 0])].map(([e, n]) =>
      el("button", { type: "button", class: "boton", "aria-pressed": String(filtro === e), onclick: () => { filtro = e; pintar(); } }, `${e} ${n}`)));
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

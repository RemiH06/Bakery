// Explorador de la inspo y la bandeja: filtro literal, pestañas por grupo (un pay de fruta por grupo) y visor.
import { api, el, enlace, fecha, mes, poner, resaltar, teclasPestanas } from "./util.js";
import { render, separar } from "./md.js";

export const GRUPOS = [
  { id: "AyP", nombre: "Anhelo y Plétora", fruta: "cereza" },
  { id: "100", nombre: "100", fruta: "mora" },
  { id: "iroFactory", nombre: "iroFactory", fruta: "kiwi" },
  { id: "AduSI", nombre: "Axiomas de una Sociedad Indiferente", fruta: "limon" },
  { id: "otros", nombre: "Otros destinos", fruta: "pan" },
];
const grupo = (g) => (GRUPOS.some(x => x.id === g) ? g : "otros");
const POR_PAGINA = 60;
const SVG = "http://www.w3.org/2000/svg";

// Un pay visto desde arriba: corteza, relleno del color del grupo y el enrejado
export function pay(g, titulo) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 16 16");
  s.setAttribute("class", `pay g-${g}`);
  s.setAttribute("aria-hidden", "true");
  const forma = (tag, attrs) => { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); s.append(n); };
  forma("circle", { cx: 8, cy: 8, r: 7.2, class: "corteza" });
  forma("circle", { cx: 8, cy: 8, r: 5.2, class: "relleno" });
  forma("path", { d: "M6.2 3.2v9.6M9.8 3.2v9.6M3.2 6.2h9.6M3.2 9.8h9.6", class: "reja" });
  if (titulo) s.setAttribute("data-titulo", titulo);
  return s;
}

export function crear(raiz, navegar) {
  let estado = {}, pedido = null, resultados = null, mostradas = POR_PAGINA, notaActual = null, marcas = [], marca = -1;

  const buscar = el("input", { id: "q", type: "search", autocomplete: "off", spellcheck: "false", enterkeyhint: "search",
    placeholder: "una palabra, una frase, @cuenta, un enlace…", "aria-describedby": "q-ayuda" });
  const fuentes = el("div", { class: "segmento", role: "group", "aria-label": "Fuente" });
  const clase = el("select", { id: "clase" });
  const floppy = el("select", { id: "floppy" });  // se llena al entrar al modo Doll
  const meses = el("select", { id: "mes" });
  const pestanas = el("div", { class: "pestanas", role: "tablist", "aria-label": "Grupos" });
  const cuantas = el("p", { class: "cuantas", role: "status" });
  const fichas = el("ol", { class: "fichas", "aria-label": "Notas" });
  const mas = el("button", { type: "button", class: "boton", hidden: true, onclick: () => { mostradas += POR_PAGINA; pintarFichas(); } });
  const hoja = el("article", { class: "hoja", "aria-label": "Nota", tabindex: "-1" });
  const respuesta = el("section", { class: "respuesta", "aria-live": "polite", hidden: true });
  const lista = el("div", { class: "lista", id: "panel-grupo", role: "tabpanel" }, respuesta, cuantas, fichas, mas);
  const ayuda = el("span", { id: "q-ayuda", class: "ayuda" });
  const modos = el("div", { class: "segmento", role: "group", "aria-label": "Cómo buscar" },
    ...[["Literal", null], ["Doll", "doll"]].map(([t, m]) => el("button", { type: "button", class: "boton", "data-modo": m || "",
      onclick: () => cambiar({ modo: m, g: null, c: null, m: null, f: null }) }, t)));
  const preguntar = el("button", { type: "button", class: "boton primario preguntar", onclick: () => hacerPregunta() }, "Preguntar a Doll");

  raiz.append(
    el("div", { class: "barra" },
      el("div", { class: "campo campo-q" },
        el("label", { for: "q" }, "Buscar en todas las notas"),
        el("div", { class: "q-fila" }, buscar, preguntar),
        ayuda),
      el("div", { class: "campo" }, el("span", { class: "etiqueta", id: "modo-t" }, "Búsqueda"), modos),
      el("div", { class: "campo solo-doll" }, el("label", { for: "floppy" }, "Floppy"), floppy),
      el("div", { class: "campo solo-literal" }, el("span", { class: "etiqueta", id: "fuente-t" }, "Cuaderno"), fuentes),
      el("div", { class: "campo solo-literal" }, el("label", { for: "clase" }, "Clase"), clase),
      el("div", { class: "campo solo-literal" }, el("label", { for: "mes" }, "Visto en"), meses)),
    pestanas,
    el("div", { class: "mesa" }, lista, hoja));
  fuentes.setAttribute("aria-labelledby", "fuente-t");
  modos.setAttribute("aria-labelledby", "modo-t");

  const cambiar = (cambios, push = false) => navegar("inspo", { ...estado, ...cambios }, push);
  // Doll corre un proceso por búsqueda: espera a que se deje de escribir un poco más
  let espera;
  buscar.addEventListener("input", () => {
    clearTimeout(espera);
    espera = setTimeout(() => cambiar({ q: buscar.value || null, n: estado.n }), estado.modo === "doll" ? 700 : 220);
  });
  buscar.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && estado.modo === "doll") { clearTimeout(espera); cambiar({ q: buscar.value || null }); }
  });

  // En modo Doll se resaltan las palabras de la consulta, no la frase: Doll no busca la frase literal
  const terminos = () => estado.modo === "doll"
    ? (estado.q || "").split(/[^\p{L}\p{N}@#]+/u).filter(t => t.length >= 4)
    : [estado.q || ""];
  const resaltarTodo = (raiz) => terminos().flatMap(t => resaltar(raiz, t));

  let preguntaDe = null;  // la respuesta se queda visible mientras la lista sea de la misma consulta

  // Floppies de Doll en la máquina del panel. Se elige por consulta (`fl` en la URL): no monta nada allá.
  let floppies = null, montado = null;
  const elegido = () => estado.fl || montado || "";
  async function cargarFloppies() {
    if (!floppies) {
      try { ({ floppies, montado } = await api("/api/doll/floppies")); }
      catch (e) { floppy.replaceChildren(el("option", {}, "sin lista")); floppy.disabled = true; floppy.title = e.message; return; }
    }
    const lista = elegido() && !floppies.includes(elegido()) ? [...floppies, elegido()] : floppies;
    floppy.replaceChildren(...lista.map(f => el("option", { value: f, selected: f === elegido() }, f === montado ? `${f} (montado)` : f)));
    floppy.disabled = lista.length < 2;
  }
  floppy.addEventListener("change", () => cambiar({ fl: floppy.value === montado ? null : floppy.value, n: null }));

  function porQueNo(r) {
    if (r.faltan?.length)
      return `Doll no llamó al modelo: la pregunta nombra ${r.faltan.map(n => `«${n}»`).join(", ")}, y eso no sale en lo que encontró. ` +
        "Si es un nombre, escríbelo como aparece en la nota; si no, pruébalo en minúsculas.";
    if (!r.intentos)
      return "Doll no encontró notas con esas palabras. Prueba con otras o con el modo Literal.";
    return `Bonsai leyó ${r.leidos} fragmentos y ninguno dice la respuesta con todas sus letras. Doll solo responde con citas ` +
      "textuales: sirve para datos concretos («¿qué herramienta…?», «¿quién dijo…?»). Para «resume», «dame ideas» o «¿cuántas…?», " +
      "la lista de abajo ya trae las notas que encontró.";
  }

  async function hacerPregunta() {
    const q = buscar.value.trim();
    if (!q) { buscar.focus(); return; }
    preguntaDe = q;
    if (estado.q !== q) cambiar({ q });  // la lista de abajo muestra lo que Doll encontró para la misma consulta
    respuesta.hidden = false;
    respuesta.replaceChildren(el("p", { class: "tenue" }, "Doll está pensando… Puede tardar un minuto si el horno está tibio."));
    preguntar.disabled = true;
    try {
      const r = await api("/api/doll/preguntar", limpio({ q, floppy: estado.fl }));
      // Lo que no está en la inspo (otra nota de la bóveda, un PDF) no se abre en el visor: se cita su ruta
      const nota = (c) => {
        const nombre = c.ruta.split("/").pop();
        if (!c.abrible) return el("span", { class: "tenue" }, c.ruta);
        return el("a", { href: `#inspo?${new URLSearchParams(limpio({ modo: "doll", fl: estado.fl, q, n: nombre }))}`,
          onclick: (ev) => { ev.preventDefault(); cambiar({ q, n: nombre }, true); } }, nombre.replace(/\.md$/, ""));
      };
      poner(respuesta,
        el("h3", {}, "Respuesta de Doll"),
        r.fallo ? el("p", { class: "error" }, `Sin respuesta del modelo: ${r.fallo}. Abajo, lo que encontró.`)
          : r.no_encontrado ? [el("p", {}, `No encontrado en «${r.floppy}». Es una respuesta real: Doll no inventa.`), el("p", { class: "ayuda" }, porQueNo(r))]
          : el("p", { class: "dicho" }, r.respuesta),
        r.citas.length ? el("ol", { class: "citas" }, r.citas.map(c => el("li", {}, el("q", {}, c.texto), " ", nota(c)))) : null,
        r.citas.length ? el("p", { class: "ayuda" }, "Cada cita se comprobó contra el texto de la nota." +
          (r.citas_descartadas ? ` Se descartaron ${r.citas_descartadas} que no aparecían.` : "")) : null);
    } catch (e) {
      respuesta.replaceChildren(el("p", { class: "error" }, e.message));
    } finally { preguntar.disabled = false; }
  }
  clase.addEventListener("change", () => cambiar({ c: clase.value || null }));
  meses.addEventListener("change", () => cambiar({ m: meses.value || null }));
  let focoEnPestanas = false;  // las pestañas se repintan con los conteos nuevos: el foco pasa a la activa
  teclasPestanas(pestanas, (t) => { focoEnPestanas = true; cambiar({ g: t.dataset.grupo || null }); });

  function opciones(select, conteo, actual, todas, etiqueta = (x) => x) {
    const claves = Object.keys(conteo).sort();
    if (actual && !claves.includes(actual)) claves.push(actual);
    select.replaceChildren(el("option", { value: "" }, todas),
      ...claves.map(k => el("option", { value: k, selected: k === actual }, `${etiqueta(k)} (${conteo[k] || 0})`)));
  }

  function pintarControles(d) {
    fuentes.replaceChildren(...d.fuentes.map(f => el("button", { type: "button", class: "boton", "aria-pressed": String((estado.f || "inspo") === f),
      onclick: () => cambiar({ f: f === "inspo" ? null : f, g: null, c: null, m: null, n: null }) }, f === "inspo" ? "Inspo" : "Bandeja")));
    opciones(clase, d.conteo.clases, estado.c, "Todas");
    clase.disabled = !Object.keys(d.conteo.clases).length && !estado.c;
    const ms = Object.fromEntries(Object.entries(d.conteo.meses).sort().reverse());
    meses.replaceChildren(el("option", { value: "" }, "Cualquier fecha"),
      ...Object.keys(ms).map(k => el("option", { value: k, selected: k === estado.m }, `${mes(k)} (${ms[k]})`)));
    const tabs = [{ id: null, nombre: "Todos los grupos", corto: "Todos" }, ...GRUPOS].map(g => {
      const n = g.id ? (d.conteo.grupos[g.id] || 0) : d.conteo.todos;
      const activa = (estado.g || null) === g.id;
      return el("button", { type: "button", role: "tab", class: `pestana${g.id ? ` g-${g.id}` : ""}`, "data-grupo": g.id || "",
        "aria-selected": String(activa), "aria-controls": "panel-grupo", tabindex: activa ? "0" : "-1", title: g.nombre,
        onclick: () => cambiar({ g: g.id }) },
        g.id ? pay(g.id) : null, el("span", {}, g.corto || g.id), n != null ? el("span", { class: "n" }, String(n)) : null);
    });
    pestanas.replaceChildren(...tabs);
    if (focoEnPestanas) { pestanas.querySelector('[aria-selected="true"]')?.focus(); focoEnPestanas = false; }
  }

  function ficha(n) {
    const activa = n.nombre === estado.n;
    // Fuera de la inspo no hay fecha ni cuenta: la carpeta dice de dónde salió
    const carpeta = n.abrible === false && n.ruta?.includes("/") ? n.ruta.slice(0, n.ruta.lastIndexOf("/")) : null;
    const meta = [carpeta, fecha(n.fecha), n.cuenta, n.clase, n.estado && n.estado !== "analizado" ? n.estado : null].filter(Boolean);
    const contenido = [
      el("span", { class: "pays" }, n.grupos.map(g => pay(grupo(g)))),
      el("span", { class: "titulo" }, n.titulo),
      el("span", { class: "meta" }, meta.join(" · ") + (n.coincidencias > 1 ? ` · ${n.coincidencias} veces` : "")),
      n.fragmento ? el("span", { class: "fragmento" }, n.fragmento) : null,
      // Doll: cada fragmento con el encabezado de la sección donde salió
      ...(n.fragmentos || []).slice(0, 2).map(f => {
        const seccion = (f.encabezado || "").split(" > ").slice(1).join(" › ");  // Doll antepone el título de la nota
        return el("span", { class: "fragmento" }, seccion ? el("span", { class: "seccion" }, `${seccion}: `) : null,
          f.texto.replace(/^#+ .*\n/, "").replace(/\s+/g, " ").slice(0, 260));
      }),
    ];
    const clase = `ficha g-${grupo(n.grupos[0])}${activa ? " activa" : ""}`;
    if (n.abrible === false) return el("li", { class: clase }, el("div", { class: "no-abrible" }, ...contenido));
    return el("li", { class: clase },
      el("a", { href: `#inspo?${new URLSearchParams(limpio({ ...estado, n: n.nombre }))}`, "aria-current": activa ? "true" : null,
        onclick: (ev) => { if (ev.metaKey || ev.ctrlKey) return; ev.preventDefault(); cambiar({ n: n.nombre }, true); } },
        ...contenido));
  }

  function pintarFichas() {
    const d = resultados, doll = estado.modo === "doll";
    const vis = d.notas.slice(0, mostradas);
    fichas.replaceChildren(...vis.map(ficha));
    if (estado.q) resaltarTodo(fichas);
    const sufijo = estado.q ? ` con «${estado.q}»` : "";
    cuantas.textContent = doll && !estado.q ? "Escribe qué buscas. Doll ordena por sentido: encuentra la idea aunque la nota use otras palabras."
      : d.notas.length ? (doll ? `${d.notas.length} notas de «${d.floppy}» para «${estado.q}», ${d.como === "sentido" ? "de la más cercana a la menos" : "por palabras, de la más relevante a la menos"}` : `${d.notas.length} de ${d.total} notas${sufijo}`)
      : !doll && !d.total ? "Este cuaderno todavía no tiene notas."
      : `Nada en el horno${sufijo}. Prueba con menos palabras${doll ? " u otras" : ", otra pestaña o sin filtros"}.`;
    mas.hidden = d.notas.length <= mostradas;
    mas.textContent = `Mostrar ${Math.min(POR_PAGINA, d.notas.length - mostradas)} más`;
  }

  async function cargarLista() {
    pedido?.abort();
    pedido = new AbortController();
    raiz.setAttribute("aria-busy", "true");
    if (estado.q !== preguntaDe || estado.modo !== "doll") { respuesta.hidden = true; preguntaDe = null; }
    try {
      if (estado.modo === "doll") {
        resultados = estado.q ? await api(`/api/doll?${new URLSearchParams(limpio({ q: estado.q, floppy: estado.fl }))}`, null, pedido.signal) : { notas: [] };
        mostradas = POR_PAGINA;
        pintarFichas();
        return;
      }
      const p = limpio({ fuente: estado.f || "inspo", q: estado.q, grupo: estado.g, clase: estado.c, mes: estado.m });
      resultados = await api(`/api/notas?${new URLSearchParams(p)}`, null, pedido.signal);
      mostradas = POR_PAGINA;
      pintarControles(resultados);
      pintarFichas();
    } catch (e) {
      if (e.name === "AbortError") return;
      fichas.replaceChildren();
      cuantas.textContent = `Sin notas: ${e.message}`;
    } finally { raiz.removeAttribute("aria-busy"); }
  }

  function saltar(paso) {
    if (!marcas.length) return;
    marcas[marca]?.classList.remove("actual");
    marca = (marca + paso + marcas.length) % marcas.length;
    marcas[marca].classList.add("actual");
    marcas[marca].scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    hoja.querySelector(".contador").textContent = `${marca + 1} de ${marcas.length}`;
  }

  async function cargarNota() {
    if (!estado.n) { raiz.classList.remove("con-nota"); hoja.replaceChildren(vacia()); notaActual = null; return; }
    raiz.classList.add("con-nota");
    if (notaActual?.nombre !== estado.n || notaActual?.fuente !== (estado.f || "inspo")) {
      try {
        notaActual = await api(`/api/nota?${new URLSearchParams({ fuente: estado.f || "inspo", nombre: estado.n })}`);
      } catch (e) {
        hoja.replaceChildren(el("p", { class: "aviso error" }, `No se pudo abrir la nota: ${e.message}`), volver());
        return;
      }
    }
    pintarNota(notaActual);
  }

  function volver() {
    return el("button", { type: "button", class: "boton volver", onclick: () => history.state?.nota ? history.back() : cambiar({ n: null }) }, "← Volver a la lista");
  }

  function vacia() {
    return el("div", { class: "hoja-vacia" }, pay("otros"), el("p", {}, "Abre una nota para leerla aquí."));
  }

  function pintarNota(n) {
    const [, cuerpo] = separar(n.texto);
    const datos = [fecha(n.fecha), n.cuenta, n.formato, n.clase, n.estado ? `cola: ${n.estado}` : null, n.pista ? `pista: ${n.pista}` : null].filter(Boolean);
    const copiar = el("button", { type: "button", class: "boton", onclick: async () => {
      try { await navigator.clipboard.writeText(`[[${n.nombre.replace(/\.md$/, "")}]]`); copiar.textContent = "Copiado"; }
      catch { copiar.textContent = "No se pudo copiar"; }
      setTimeout(() => (copiar.textContent = "Copiar enlace de Obsidian"), 1800);
    } }, "Copiar enlace de Obsidian");
    const contenido = el("div", { class: "texto" }, render(cuerpo, { sinTitulo: !!n.titulo }));
    hoja.replaceChildren(
      el("header", { class: "hoja-cab" },
        volver(),
        el("div", { class: "pays" }, n.grupos.map(g => pay(grupo(g)))),
        el("h2", { id: "nota-t" }, n.titulo),
        el("p", { class: "meta" }, datos.join(" · ")),
        n.destinos.length ? el("p", { class: "destinos" }, "Destino: ", n.destinos.map((d, i) => [i ? ", " : "", el("span", { class: "wikilink" }, d)])) : null,
        el("div", { class: "acciones" },
          n.url ? enlace(n.url, "Ver la fuente original", { class: "boton primario" }) : null, copiar,
          estado.q ? el("span", { class: "buscador" },
            el("button", { type: "button", class: "boton", "aria-label": "Coincidencia anterior", onclick: () => saltar(-1) }, "↑"),
            el("span", { class: "contador", "aria-live": "polite" }, ""),
            el("button", { type: "button", class: "boton", "aria-label": "Coincidencia siguiente", onclick: () => saltar(1) }, "↓")) : null)),
      contenido);
    hoja.setAttribute("aria-labelledby", "nota-t");
    marcas = estado.q ? resaltarTodo(contenido) : [];
    marcas.sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
    marca = -1;
    const contador = hoja.querySelector(".contador");
    if (contador) contador.textContent = marcas.length ? `${marcas.length} en la nota` : "no aparece en el texto";
    hoja.scrollTop = 0;
    if (matchMedia("(max-width: 979px)").matches) { window.scrollTo(0, 0); hoja.focus({ preventScroll: true }); }
  }

  return {
    async mostrar(params) {
      const antes = estado;
      estado = params;
      if (document.activeElement !== buscar) buscar.value = estado.q || "";
      const doll = estado.modo === "doll";
      raiz.classList.toggle("modo-doll", doll);
      for (const b of modos.children) b.setAttribute("aria-pressed", String((b.dataset.modo || null) === (estado.modo || null)));
      if (doll) await cargarFloppies();
      ayuda.textContent = doll
        ? "Doll busca por sentido en un floppy de pura inspo y por palabras en uno con notas tuyas. Enter busca; «Preguntar» responde con citas comprobadas."
        : "Texto literal en cualquier parte de la nota, sin importar mayúsculas ni acentos.";
      buscar.placeholder = doll ? "costos de entrenar modelos, fondos animados con shaders…" : "una palabra, una frase, @cuenta, un enlace…";
      const clave = (e) => [e.modo, e.fl, e.f, e.q, e.g, e.c, e.m].join("\u0000");
      if (!resultados || clave(antes) !== clave(estado)) await cargarLista();
      else if (antes.n !== estado.n) pintarFichas();
      await cargarNota();
    },
    enfocar() { buscar.focus(); },
  };
}

export const limpio = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v != null && v !== ""));

// Máquinas de Bakery: una tarjeta por máquina con recursos, servicios (iniciar, detener, reiniciar los de la lista
// blanca), su log y las órdenes fijas. La máquina del panel responde por el panel; las demás, por su agente, al que
// el navegador llama directo (el servidor del panel no tiene permisos sobre otras máquinas).
import { api, el, hora, poner } from "./util.js";

const CADA = 10000;   // ms entre consultas mientras la hoja está a la vista
const ESPERA = 8000;  // una máquina apagada no responde: no se espera más que esto
const VERBO = { iniciar: "Iniciar", detener: "Detener", reiniciar: "Reiniciar" };
const CLASE = { activo: "e-analizado", arrancando: "e-pendiente", "deteniéndose": "e-pendiente", "falló": "e-fallido", "no existe": "e-fallido" };

export function crear(raiz) {
  let maquinas = null, reloj = null;
  const tarjetas = new Map();  // nombre -> { cuerpo, log }
  const aviso = el("p", { class: "tenue", role: "status" });
  raiz.append(aviso);

  const base = (m) => m.url || "";  // "" es el panel mismo
  const pedir = (m, ruta, cuerpo) => api(`${base(m)}${ruta}`, cuerpo, AbortSignal.timeout(cuerpo ? 120000 : ESPERA));

  function indicador(rotulo, valor, sub, pct) {
    let medidor = null;
    if (pct != null) {
      const barra = el("span", {});
      barra.style.width = `${Math.min(100, Math.max(0, pct))}%`;  // por CSSOM: la CSP no deja atributos style
      medidor = el("span", { class: "medidor", role: "img", "aria-label": `${Math.round(pct)} % ocupado` }, barra);
    }
    return el("div", { class: `indicador${pct >= 90 ? " alerta" : ""}` }, el("span", { class: "rotulo" }, rotulo), el("b", { class: "valor" }, valor),
      sub ? el("span", { class: "sub" }, sub) : null, medidor);
  }

  function recursos(r) {
    const ram = r.ram_total_gb - r.ram_libre_gb;
    const disco = r.disco.total_gb - r.disco.libre_gb;
    return el("div", { class: "indicadores" },
      indicador("CPU", `${r.cpu} %`, `${r.nucleos} núcleos${r.temperatura != null ? ` · ${r.temperatura} °C` : ""}`, r.cpu),
      indicador("RAM", `${ram.toFixed(1)} de ${r.ram_total_gb} GB`, `${r.ram_libre_gb} GB disponibles`, 100 * ram / r.ram_total_gb),
      indicador("Disco", `${r.disco.libre_gb} GB libres`, `de ${r.disco.total_gb} GB en ${r.disco.montaje}`, 100 * disco / r.disco.total_gb),
      r.gpu ? indicador("GPU", `${r.gpu.vram_usada_gb} de ${r.gpu.vram_total_gb} GB`, `${r.gpu.uso} % de uso · ${r.gpu.temperatura} °C`,
        100 * r.gpu.vram_usada_gb / r.gpu.vram_total_gb) : null,
      indicador("Encendida desde", hora(r.encendida_desde), null, null));
  }

  async function actuar(m, t, ruta, cuerpo, pregunta, boton) {
    if (pregunta && !confirm(pregunta)) return;
    boton.disabled = true;
    t.estado.textContent = "Trabajando…";
    try {
      await pedir(m, ruta, cuerpo);
      t.estado.textContent = `Listo (${hora(new Date().toISOString())}).`;
    } catch (e) {
      t.estado.textContent = `No se pudo: ${e.message}`;
      t.estado.className = "error";
      return;
    } finally { boton.disabled = false; }
    t.estado.className = "tenue";
    consultar(m);
  }

  async function verLog(m, t, servicio) {
    t.log.hidden = false;
    poner(t.log, el("div", { class: "fila" }, el("b", {}, `Log de ${servicio}`),
      el("button", { type: "button", class: "boton", onclick: () => verLog(m, t, servicio) }, "Actualizar"),
      el("button", { type: "button", class: "boton", onclick: () => { t.log.hidden = true; } }, "Cerrar")),
      el("p", { class: "tenue" }, "Cargando…"));
    try {
      const d = await pedir(m, `/api/log?${new URLSearchParams({ servicio })}`);
      t.log.lastChild.replaceWith(el("pre", { tabindex: "0" }, d.renglones.length ? d.renglones.join("\n") : "(vacío)"));
    } catch (e) { t.log.lastChild.replaceWith(el("p", { class: "error" }, e.message)); }
  }

  function servicios(m, t, lista) {
    if (!lista.length) return el("p", { class: "tenue" }, "Sin servicios en la lista de esta máquina.");
    return el("ul", { class: "items" }, lista.map(s => el("li", {},
      el("div", { class: "fila" }, el("span", { class: `insignia ${CLASE[s.estado] || ""}` }, s.estado), el("b", {}, s.nombre),
        s.desde ? el("span", { class: "tenue" }, `desde ${hora(s.desde.replace(" ", "T"))}`) : null),
      el("span", { class: "tenue" }, [s.detalle, s.siguiente ? `siguiente: ${hora(s.siguiente)}` : null].filter(Boolean).join(" · ")),
      el("div", { class: "fila" },
        ...(s.controlable ? Object.entries(VERBO).filter(([v]) => (v === "iniciar") !== (s.estado === "activo")).map(([v, texto]) => {
          const b = el("button", { type: "button", class: "boton", "aria-label": `${texto} ${s.nombre}` }, texto);
          b.addEventListener("click", () => actuar(m, t, "/api/accion", { servicio: s.nombre, accion: v },
            v === "iniciar" ? null : `¿${texto} ${s.nombre} en ${m.nombre}?`, b));
          return b;
        }) : []),
        el("button", { type: "button", class: "boton", "aria-label": `Log de ${s.nombre}`, onclick: () => verLog(m, t, s.nombre) }, "Log")))));
  }

  function ordenes(m, t, lista) {
    if (!lista.length) return null;
    return el("div", { class: "fila" }, el("span", { class: "tenue" }, "Órdenes:"), lista.map(o => {
      const b = el("button", { type: "button", class: "boton" }, o);
      b.addEventListener("click", () => actuar(m, t, "/api/orden", { orden: o }, `¿Correr «${o}» en ${m.nombre}?`, b));
      return b;
    }));
  }

  function tarjeta(m) {
    if (!tarjetas.has(m.nombre)) {
      const t = { titulo: el("span", { class: "tenue" }), cuerpo: el("div", { class: "pila" }, el("p", { class: "tenue" }, "Consultando…")),
        estado: el("p", { class: "tenue", role: "status" }), log: el("div", { class: "pila", hidden: true }) };
      raiz.append(el("section", { class: "tarjeta", "aria-labelledby": `m-${m.nombre}` },
        el("h3", { id: `m-${m.nombre}` }, m.nombre, " ", t.titulo), t.cuerpo, t.estado, t.log));
      tarjetas.set(m.nombre, t);
    }
    return tarjetas.get(m.nombre);
  }

  async function consultar(m) {
    const t = tarjeta(m);
    try {
      const d = await pedir(m, "/api/maquina");
      t.titulo.textContent = `· ${d.sistema} · ${hora(d.hora)}`;
      poner(t.cuerpo, recursos(d.recursos), servicios(m, t, d.servicios), ordenes(m, t, d.ordenes));
    } catch (e) {
      t.titulo.textContent = "· sin respuesta";
      const motivo = e.name === "TimeoutError" ? "no respondió en 8 s: apagada, dormida o fuera del tailnet" : e.message;
      poner(t.cuerpo, el("p", { class: "error" }, `Sin datos de ${m.nombre}: ${motivo}.`));
    }
  }

  async function vuelta() {
    if (raiz.hidden || document.hidden) return;
    if (!maquinas) {
      try {
        const d = await api("/api/maquinas");
        maquinas = [{ nombre: d.local, url: "" }, ...Object.entries(d.agentes).map(([nombre, url]) => ({ nombre, url }))];
        aviso.textContent = `${maquinas.length} ${maquinas.length === 1 ? "máquina" : "máquinas"}. Se actualiza cada ${CADA / 1000} s mientras esta hoja está abierta.`;
      } catch (e) { aviso.textContent = `Sin lista de máquinas: ${e.message}`; return; }
    }
    await Promise.all(maquinas.map(consultar));
  }

  return {
    mostrar() {
      vuelta();
      clearInterval(reloj);
      reloj = setInterval(vuelta, CADA);  // `vuelta` no hace nada con la hoja oculta
    },
  };
}

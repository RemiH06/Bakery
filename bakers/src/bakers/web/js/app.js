// Arranque: pestañas del cuaderno (cada vista es una hoja), estado en la URL y el horno (la marcha de Pixilate).
import { api, el, hora } from "./util.js";
import * as inspo from "./inspo.js";
import * as cola from "./cola.js";

const HORNO = { alta: "caliente", media: "tibio", ninguna: "apagado" };
const hojas = {
  inspo: { titulo: "Inspo", raiz: document.getElementById("v-inspo") },
  cola: { titulo: "Cola", raiz: document.getElementById("v-cola") },
};
let ultimoEstado = null;

function leer() {
  const [vista, consulta] = location.hash.slice(1).split("?");
  return { vista: hojas[vista] ? vista : "inspo", params: Object.fromEntries(new URLSearchParams(consulta || "")) };
}

function navegar(vista, params, push = false) {
  const q = new URLSearchParams(inspo.limpio(params)).toString();
  const hash = `#${vista}${q ? `?${q}` : ""}`;
  if (hash !== location.hash) history[push ? "pushState" : "replaceState"]({ nota: push && !!params.n }, "", hash);
  mostrar();
}

function mostrar() {
  const { vista, params } = leer();
  for (const [id, h] of Object.entries(hojas)) {
    h.raiz.hidden = id !== vista;
    document.getElementById(`ir-${id}`).setAttribute("aria-current", id === vista ? "page" : "false");
  }
  document.title = `${hojas[vista].titulo} · Bakery`;
  hojas[vista].vista.mostrar(params);
}

function pintarHorno(d) {
  const horno = document.getElementById("horno");
  const marcha = (d?.marcha || "").startsWith("sin respuesta") ? "sin respuesta" : d?.marcha;
  horno.dataset.marcha = HORNO[marcha] ? marcha : "otra";
  horno.replaceChildren(el("span", { class: "llama", "aria-hidden": "true" }),
    el("span", {}, d ? `Horno ${HORNO[marcha] || marcha} · marcha ${marcha}` : "Horno sin datos"));
  horno.title = d ? `Pixilate: marcha ${d.marcha}. Actualizado ${hora(new Date().toISOString())}.` : "";
}

async function refrescar() {
  try {
    ultimoEstado = await api("/api/estado");
    pintarHorno(ultimoEstado);
    hojas.cola.vista.actualizar(ultimoEstado);
  } catch { pintarHorno(null); }
}

hojas.inspo.vista = inspo.crear(hojas.inspo.raiz, navegar);
hojas.cola.vista = cola.crear(hojas.cola.raiz, refrescar);
for (const id of Object.keys(hojas)) {
  document.getElementById(`ir-${id}`).addEventListener("click", (ev) => {
    if (ev.metaKey || ev.ctrlKey) return;
    ev.preventDefault();
    navegar(id, id === leer().vista ? leer().params : {}, true);
  });
}
// "/" lleva al buscador desde cualquier parte, como en muchos sitios; no estorba al escribir en un campo
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "/" || ev.target.closest("input, textarea, select")) return;
  ev.preventDefault();
  if (leer().vista !== "inspo") navegar("inspo", {}, true);
  hojas.inspo.vista.enfocar();
});
addEventListener("popstate", mostrar);
document.documentElement.classList.add("listo");
mostrar();
refrescar();
setInterval(() => { if (!document.hidden) refrescar(); }, 20000);

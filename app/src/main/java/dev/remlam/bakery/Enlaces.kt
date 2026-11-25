package dev.remlam.bakery

import java.net.URI
import java.net.URISyntaxException

private val ENLACE = Regex("""https?://[^\s<>"]+""", RegexOption.IGNORE_CASE)
private const val CIERRES = ".,;:!?)]}'”’»…"

/** El primer enlace del texto que comparte una app, sin lo que la app le pone alrededor ("Mira este video de..."). */
fun sacarEnlace(texto: String): String? {
    val e = ENLACE.find(texto)?.value?.trimEnd { it in CIERRES } ?: return null
    val resto = e.substringAfter("://")
    return if (resto.isEmpty()) null else e.substringBefore("://").lowercase() + "://" + resto
}

/** Lo que espera `cola.agregar_texto`: la etiqueta antes del enlace, en un solo renglón. Un enlace dentro de la
 *  etiqueta se tomaría como el bueno y un `#` al principio como encabezado, así que se quitan. */
fun textoParaCola(enlace: String, etiqueta: String?): String {
    val e = etiqueta.orEmpty().replace(ENLACE, " ").replace(Regex("""\s+"""), " ").trim().trimStart('#', ' ')
    return if (e.isEmpty()) enlace else "$e: $enlace"
}

/** `https://maquina.tailnet.ts.net:8093`, o null. Solo el tailnet: un error de dedo no debe mandar enlaces a otro lado. */
fun direccionValida(texto: String): String? {
    val t = texto.trim().let { if ("://" in it) it else "https://$it" }
    val u = try {
        URI(t)
    } catch (e: URISyntaxException) {
        return null
    }
    val host = u.host?.lowercase() ?: return null
    val sobra = u.rawUserInfo != null || u.rawQuery != null || u.rawFragment != null || u.rawPath !in listOf("", "/")
    if (u.scheme.lowercase() != "https" || !host.endsWith(".ts.net") || sobra || u.port == 0 || u.port > 65535) return null
    return "https://$host:${if (u.port == -1) 8093 else u.port}"
}

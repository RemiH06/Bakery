package dev.remlam.bakery

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.UnknownHostException
import javax.net.ssl.SSLException
import org.json.JSONException
import org.json.JSONObject

sealed class Resultado {
    abstract val aviso: String

    /** El panel lo confirmó. */
    data class Hecho(override val aviso: String) : Resultado()

    /** El panel dijo que no: reintentar igual daría lo mismo. */
    data class Rechazado(override val aviso: String) : Resultado()

    /** No llegó o no se sabe si llegó. Reintentar es seguro: un enlace ya agregado sale como repetido. */
    data class Falla(override val aviso: String) : Resultado()
}

/** La API del panel (`bakers/src/bakers/panel.py`). Sin token: la identidad la pone Tailscale. */
class Panel(private val direccion: String) {
    fun agregar(p: Pendiente): Resultado {
        val cuerpo = JSONObject().put("texto", textoParaCola(p.enlace, p.etiqueta))
        if (p.seccion != null) cuerpo.put("seccion", p.seccion)
        return pedir("/api/agregar", cuerpo) { r ->
            when {
                r.optInt("agregados") > 0 -> Resultado.Hecho("Agregado · ${r.optInt("en_cola")} en cola")
                r.optInt("repetidos") > 0 -> Resultado.Hecho("Repetido: ya estaba en la cola")
                r.optInt("ya_bajados") > 0 -> Resultado.Hecho("Ya estaba bajado")
                r.optInt("sin_enlace") > 0 -> Resultado.Rechazado("El panel no vio un enlace")
                else -> null
            }
        }
    }

    fun probar(): Resultado = pedir("/api/maquinas", null) { r ->
        if (r.has("local")) Resultado.Hecho("Listo: responde ${r.optString("local")}") else null
    }

    private fun pedir(ruta: String, cuerpo: JSONObject?, leer: (JSONObject) -> Resultado?): Resultado {
        val c = URL(direccion + ruta).openConnection() as HttpURLConnection
        try {
            c.connectTimeout = 4_000
            c.readTimeout = 15_000 // el panel tarda hasta 8 s en resolver un enlace corto
            c.instanceFollowRedirects = false
            c.useCaches = false
            if (cuerpo != null) {
                val datos = cuerpo.toString().toByteArray()
                c.requestMethod = "POST"
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.setFixedLengthStreamingMode(datos.size)
                c.outputStream.use { it.write(datos) }
            }
            val codigo = c.responseCode
            val flujo = if (codigo < 400) c.inputStream else c.errorStream
            val texto = flujo?.use { it.readNBytes(65_536).toString(Charsets.UTF_8) }.orEmpty()
            val json = try {
                JSONObject(texto)
            } catch (e: JSONException) {
                null
            }
            return when {
                codigo == 200 -> json?.let(leer) ?: Resultado.Falla("Esa dirección respondió, pero no es el panel")
                codigo == 400 -> Resultado.Rechazado("El panel lo rechazó: ${json?.optString("error") ?: "400"}")
                codigo == 403 -> Resultado.Falla("El panel no reconoce tu cuenta de Tailscale (403)")
                codigo in 502..504 -> Resultado.Falla("Pixilate responde, pero el panel está apagado ($codigo)")
                else -> Resultado.Falla("Respuesta inesperada del panel ($codigo)")
            }
        } catch (e: UnknownHostException) {
            return Resultado.Falla("No se encuentra el panel: ¿está prendido Tailscale?")
        } catch (e: SSLException) {
            return Resultado.Falla("La conexión segura falló; no se mandó nada")
        } catch (e: IOException) {
            return Resultado.Falla("El panel no responde: ¿Pixilate está apagada?")
        } finally {
            c.disconnect()
        }
    }
}

package dev.remlam.bakery

import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption.ATOMIC_MOVE
import java.nio.file.StandardCopyOption.REPLACE_EXISTING
import java.util.UUID
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/** Un enlace que el panel todavía no confirma. `rechazado`: el panel dijo que no, así que no se reintenta solo. */
data class Pendiente(
    val id: String, val enlace: String, val etiqueta: String?, val seccion: String?, val creado: Long,
    val intentos: Int = 0, val motivo: String? = null, val rechazado: Boolean = false,
)

/** Lo que falta por mandar, en un JSON que se escribe entero y se cambia de nombre: un corte deja el anterior. */
class Cola(private val archivo: File) {
    @Synchronized
    fun todos(): List<Pendiente> {
        if (!archivo.exists()) return emptyList()
        return try {
            val lista = JSONArray(archivo.readText())
            List(lista.length()) { leer(lista.getJSONObject(it)) }
        } catch (e: JSONException) { // no se pisa: queda al lado para rescatarlo a mano
            archivo.renameTo(File(archivo.path + ".roto-" + System.currentTimeMillis()))
            emptyList()
        }
    }

    /** El mismo enlace dos veces es un solo pendiente con la nota más nueva. El id cambia para que, si el anterior
     *  va de camino, su confirmación no borre la nota. */
    @Synchronized
    fun agregar(enlace: String, etiqueta: String?, seccion: String?): Pendiente {
        val (previos, otros) = todos().partition { it.enlace == enlace }
        val previo = previos.firstOrNull()
        val p = Pendiente(
            UUID.randomUUID().toString(), enlace, etiqueta ?: previo?.etiqueta, seccion ?: previo?.seccion,
            previo?.creado ?: System.currentTimeMillis(),
        )
        guardar(otros + p)
        return p
    }

    @Synchronized
    fun quitar(id: String) = guardar(todos().filter { it.id != id })

    @Synchronized
    fun fallo(id: String, motivo: String, rechazado: Boolean) = guardar(todos().map {
        if (it.id == id) it.copy(intentos = it.intentos + 1, motivo = motivo, rechazado = rechazado) else it
    })

    private fun leer(o: JSONObject): Pendiente {
        fun texto(k: String) = if (o.isNull(k)) null else o.getString(k)
        return Pendiente(
            o.getString("id"), o.getString("enlace"), texto("etiqueta"), texto("seccion"), o.getLong("creado"),
            o.getInt("intentos"), texto("motivo"), o.getBoolean("rechazado"),
        )
    }

    private fun guardar(lista: List<Pendiente>) {
        val json = JSONArray()
        for (p in lista) json.put(JSONObject().apply {
            put("id", p.id)
            put("enlace", p.enlace)
            put("etiqueta", p.etiqueta ?: JSONObject.NULL)
            put("seccion", p.seccion ?: JSONObject.NULL)
            put("creado", p.creado)
            put("intentos", p.intentos)
            put("motivo", p.motivo ?: JSONObject.NULL)
            put("rechazado", p.rechazado)
        })
        val tmp = File(archivo.path + ".tmp")
        FileOutputStream(tmp).use {
            it.write(json.toString().toByteArray())
            it.fd.sync()
        }
        Files.move(tmp.toPath(), archivo.toPath(), REPLACE_EXISTING, ATOMIC_MOVE)
    }
}

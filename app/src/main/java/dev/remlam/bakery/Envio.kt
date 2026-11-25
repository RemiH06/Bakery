package dev.remlam.bakery

import android.app.Activity
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

private const val TRABAJO = "mandar"
private const val ESPERA_MS = 2_500L // lo más que compartir tarda en regresar a la otra app

object Envio {
    private val turno = Any() // un envío a la vez
    private val programa = Any() // agregar y programar van juntos, igual que ver que no queda nada y cancelar
    private val principal = Handler(Looper.getMainLooper())
    private var cola: Cola? = null

    /** La pantalla abierta, para repintarse. Solo en el hilo principal. */
    var alCambiar: (() -> Unit)? = null

    @Synchronized
    fun cola(c: Context): Cola = cola ?: Cola(File(c.applicationContext.filesDir, "cola.json")).also { cola = it }

    private fun ajustes(c: Context) = c.getSharedPreferences("ajustes", Context.MODE_PRIVATE)

    fun direccion(c: Context): String? = ajustes(c).getString("direccion", null)

    fun guardarDireccion(c: Context, d: String) = ajustes(c).edit().putString("direccion", d).apply()

    private fun guardar(c: Context, enlace: String, etiqueta: String?, seccion: String?): Pendiente =
        synchronized(programa) {
            val p = cola(c).agregar(enlace, etiqueta, seccion)
            programar(c)
            p
        }

    private fun programar(c: Context) {
        val trabajo = PeriodicWorkRequest.Builder(EnvioWorker::class.java, 15, TimeUnit.MINUTES) // el mínimo de Android
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInitialDelay(1, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(c).enqueueUniquePeriodicWork(TRABAJO, ExistingPeriodicWorkPolicy.KEEP, trabajo)
    }

    /** Manda uno si todavía hace falta; null si ya no está. */
    private fun mandar(c: Context, id: String): Resultado? {
        synchronized(turno) {
            val cola = cola(c)
            val p = cola.todos().find { it.id == id } ?: return null
            val d = direccion(c)
            val r = if (d == null) Resultado.Falla("Falta la dirección del panel en Bakery") else Panel(d).agregar(p)
            if (r is Resultado.Hecho) cola.quitar(id) else cola.fallo(id, r.aviso, r is Resultado.Rechazado)
            principal.post { alCambiar?.invoke() }
            return r
        }
    }

    /** Los más viejos primero. A la primera falla de conexión se detiene: los demás darían lo mismo. */
    fun vaciar(c: Context) {
        for (p in cola(c).todos().filter { !it.rechazado }) if (mandar(c, p.id) is Resultado.Falla) break
        synchronized(programa) {
            if (cola(c).todos().all { it.rechazado }) WorkManager.getInstance(c).cancelUniqueWork(TRABAJO)
        }
    }

    fun borrar(c: Context, id: String) {
        cola(c).quitar(id)
        principal.post { alCambiar?.invoke() }
    }

    fun uno(c: Context, id: String) {
        thread { mandar(c.applicationContext, id) }
    }

    fun todo(c: Context) {
        thread { vaciar(c.applicationContext) }
    }

    /** Compartir: avisa qué pasó y cierra; sin respuesta a tiempo, queda guardado y el envío sigue aparte. */
    fun compartir(a: Activity, enlace: String, etiqueta: String?, seccion: String?) {
        val c = a.applicationContext
        var cerrada = false
        fun cerrar(aviso: String) {
            if (cerrada) return
            cerrada = true
            Toast.makeText(c, aviso, Toast.LENGTH_SHORT).show()
            a.finish()
        }
        thread {
            val p = try {
                guardar(c, enlace, etiqueta, seccion)
            } catch (e: IOException) {
                principal.post { cerrar("No se pudo guardar en el teléfono: ${e.message}") }
                return@thread
            }
            principal.postDelayed({ cerrar("Guardado: se manda solo") }, ESPERA_MS)
            val r = mandar(c, p.id)
            principal.post {
                cerrar(
                    when (r) {
                        null -> "Ya se había mandado"
                        is Resultado.Falla -> "Guardado. ${r.aviso}"
                        else -> r.aviso
                    }
                )
            }
            if (r !is Resultado.Falla) vaciar(c)
        }
    }
}

class EnvioWorker(c: Context, p: WorkerParameters) : Worker(c, p) {
    override fun doWork(): Result {
        Envio.vaciar(applicationContext)
        return Result.success() // lo que falte, en la siguiente vuelta
    }
}

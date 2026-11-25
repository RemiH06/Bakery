package dev.remlam.bakery

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.concurrent.thread

/** Lo que falta por mandar y los ajustes. */
class MainActivity : Activity() {
    override fun onCreate(estado: Bundle?) {
        super.onCreate(estado)
        setContentView(R.layout.principal)
        publicarConNota(this)
        val direccion = findViewById<EditText>(R.id.direccion)
        if (estado == null) direccion.setText(Envio.direccion(this))
        findViewById<Button>(R.id.mandar_todo).setOnClickListener { Envio.todo(this) }
        findViewById<Button>(R.id.probar).setOnClickListener { probar(direccion.text.toString()) }
    }

    override fun onStart() {
        super.onStart()
        Envio.alCambiar = ::pintar
        pintar()
        Envio.todo(this)
    }

    override fun onStop() {
        Envio.alCambiar = null
        super.onStop()
    }

    private fun probar(texto: String) {
        val resultado = findViewById<TextView>(R.id.resultado)
        val d = direccionValida(texto)
        if (d == null) {
            resultado.setText(R.string.direccion_mala)
            return
        }
        Envio.guardarDireccion(this, d)
        findViewById<EditText>(R.id.direccion).setText(d)
        resultado.setText(R.string.probando)
        thread {
            val r = Panel(d).probar()
            runOnUiThread { resultado.text = r.aviso }
            if (r is Resultado.Hecho) Envio.vaciar(applicationContext)
        }
    }

    private fun pintar() {
        val pendientes = Envio.cola(this).todos()
        findViewById<TextView>(R.id.titulo_cola).text =
            getString(R.string.por_mandar) + if (pendientes.isEmpty()) "" else " (${pendientes.size})"
        findViewById<View>(R.id.nada).visibility = if (pendientes.isEmpty()) View.VISIBLE else View.GONE
        findViewById<View>(R.id.mandar_todo).visibility = if (pendientes.isEmpty()) View.GONE else View.VISIBLE
        val lista = findViewById<LinearLayout>(R.id.lista)
        lista.removeAllViews()
        for (p in pendientes) {
            val fila = layoutInflater.inflate(R.layout.pendiente, lista, false)
            fila.findViewById<TextView>(R.id.enlace).text = p.enlace
            fila.findViewById<TextView>(R.id.nota).text =
                listOfNotNull(p.etiqueta, p.seccion?.let { "# $it" }, DateUtils.getRelativeTimeSpanString(p.creado))
                    .joinToString(" · ")
            fila.findViewById<TextView>(R.id.motivo).text = when {
                p.motivo == null -> "En espera"
                p.rechazado -> "${p.motivo}. No se reintenta solo."
                else -> "${p.motivo} (${p.intentos} ${if (p.intentos == 1) "intento" else "intentos"})"
            }
            fila.findViewById<Button>(R.id.reintentar).setOnClickListener { Envio.uno(this, p.id) }
            fila.findViewById<Button>(R.id.borrar).setOnClickListener {
                AlertDialog.Builder(this).setMessage(R.string.borrar_pregunta)
                    .setPositiveButton(R.string.borrar) { _, _ -> Envio.borrar(this, p.id) }
                    .setNegativeButton(R.string.cancelar, null).show()
            }
            lista.addView(fila)
        }
    }
}

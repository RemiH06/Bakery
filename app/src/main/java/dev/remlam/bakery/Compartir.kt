package dev.remlam.bakery

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.ShortcutInfo
import android.content.pm.ShortcutManager
import android.graphics.drawable.Icon
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast

private const val NOTA = "nota"
private const val CATEGORIA = "dev.remlam.bakery.NOTA"
private const val MAX_TEXTO = 20_000

/** «Con nota» en la fila de Compartir. No es otra actividad con SEND: Android juntaría las dos en un ícono y
 *  preguntaría cada vez. */
fun publicarConNota(c: Context) {
    c.getSystemService(ShortcutManager::class.java).dynamicShortcuts = listOf(
        ShortcutInfo.Builder(c, NOTA)
            .setShortLabel(c.getString(R.string.con_nota_corto))
            .setLongLabel(c.getString(R.string.con_nota))
            .setIcon(Icon.createWithResource(c, R.mipmap.ic_launcher))
            .setIntent(Intent(c, NotaActivity::class.java).setAction(Intent.ACTION_VIEW))
            .setCategories(setOf(CATEGORIA))
            .setLongLived(true)
            .build()
    )
}

/** Recibe lo compartido, lo manda y regresa a la app de donde vino. No se ve. */
class CompartirActivity : Activity() {
    override fun onCreate(estado: Bundle?) {
        super.onCreate(estado)
        if (estado != null) return finish() // recreada por el sistema: lo compartido ya se guardó
        val texto = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.take(MAX_TEXTO)?.toString().orEmpty()
        val enlace = sacarEnlace(texto)
        when {
            enlace == null -> {
                Toast.makeText(applicationContext, "Sin enlace: no se guardó nada", Toast.LENGTH_SHORT).show()
                finish()
            }
            intent.getStringExtra(Intent.EXTRA_SHORTCUT_ID) == NOTA -> {
                getSystemService(ShortcutManager::class.java).reportShortcutUsed(NOTA)
                startActivity(Intent(this, NotaActivity::class.java).putExtra(Intent.EXTRA_TEXT, enlace))
                finish()
            }
            else -> Envio.compartir(this, enlace, null, null)
        }
    }
}

/** La hoja de etiqueta y sección. También sale al dejar presionado el ícono, con el enlace vacío. */
class NotaActivity : Activity() {
    override fun onCreate(estado: Bundle?) {
        super.onCreate(estado)
        setContentView(R.layout.nota)
        val enlace = findViewById<EditText>(R.id.enlace)
        val etiqueta = findViewById<EditText>(R.id.etiqueta)
        val seccion = findViewById<EditText>(R.id.seccion)
        if (estado == null) intent.getStringExtra(Intent.EXTRA_TEXT)?.let {
            enlace.setText(it)
            etiqueta.requestFocus()
        }
        findViewById<Button>(R.id.cancelar).setOnClickListener { finish() }
        findViewById<Button>(R.id.mandar).setOnClickListener { boton ->
            val e = sacarEnlace(enlace.text.toString())
            if (e == null) {
                enlace.error = "Falta un enlace"
                return@setOnClickListener
            }
            boton.isEnabled = false
            fun EditText.valor() = text.toString().trim().ifEmpty { null }
            Envio.compartir(this, e, etiqueta.valor(), seccion.valor())
        }
    }
}

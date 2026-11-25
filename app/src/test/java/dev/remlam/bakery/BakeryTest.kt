package dev.remlam.bakery

import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.concurrent.thread
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class EnlacesTest {
    @Test
    fun `saca solo el enlace de lo que comparte cada app`() {
        val casos = mapOf(
            "https://www.instagram.com/reel/AAA/?igsh=x" to "https://www.instagram.com/reel/AAA/?igsh=x",
            "Mira este video de Ana: https://vm.tiktok.com/ZMa/ #parati" to "https://vm.tiktok.com/ZMa/",
            "Título\nhttps://youtu.be/dQw4w9WgXcQ?si=x" to "https://youtu.be/dQw4w9WgXcQ?si=x",
            "(https://www.facebook.com/share/r/1AbC/)." to "https://www.facebook.com/share/r/1AbC/",
            "HTTPS://Ejemplo.com/a y https://otro.com" to "https://Ejemplo.com/a",
            "sin nada" to null, "" to null, "https://" to null, "https://..." to null,
        )
        assertEquals(casos, casos.mapValues { sacarEnlace(it.key) })
    }

    @Test
    fun `la etiqueta va en un renglon y no cuela otro enlace ni un encabezado`() {
        val e = "https://youtu.be/a"
        assertEquals(e, textoParaCola(e, null))
        assertEquals(e, textoParaCola(e, "  # "))
        assertEquals("gatos y ñandúes: $e", textoParaCola(e, "# gatos\ny ñandúes https://malo.com/x"))
    }

    @Test
    fun `solo acepta direcciones https del tailnet`() {
        val buena = "https://maquina.red.ts.net:8093"
        assertEquals(buena, direccionValida(" maquina.red.ts.net "))
        assertEquals(buena, direccionValida("https://Maquina.red.ts.net:8093/"))
        for (mala in listOf(
            "", "http://maquina.red.ts.net", "https://ejemplo.com", "https://ts.net.ejemplo.com",
            "https://u@maquina.red.ts.net", "https://maquina.red.ts.net/api", "https://maquina.red.ts.net?x", "a b",
        )) assertNull(mala, direccionValida(mala))
    }
}

class ColaTest {
    @get:Rule
    val carpeta = TemporaryFolder()
    private val archivo get() = File(carpeta.root, "cola.json")

    @Test
    fun `sobrevive a un reinicio con todo y el motivo`() {
        val p = Cola(archivo).agregar("https://a.com", "ñandú", "Aves")
        Cola(archivo).fallo(p.id, "sin red", false)

        assertEquals(listOf(p.copy(intentos = 1, motivo = "sin red")), Cola(archivo).todos())
    }

    @Test
    fun `el mismo enlace es un solo pendiente y confirmar el anterior no borra la nota nueva`() {
        val cola = Cola(archivo)
        val uno = cola.agregar("https://a.com", null, "Aves")
        cola.fallo(uno.id, "rechazado", true)
        val dos = cola.agregar("https://a.com", "nota", null)
        cola.quitar(uno.id)

        assertEquals(listOf(dos), cola.todos())
        assertEquals(listOf("nota", "Aves", false), listOf(dos.etiqueta, dos.seccion, dos.rechazado))
        cola.quitar(dos.id)
        assertTrue(cola.todos().isEmpty())
    }

    @Test
    fun `un archivo roto se aparta en vez de perderse`() {
        archivo.writeText("[{")

        assertTrue(Cola(archivo).todos().isEmpty())
        assertEquals("[{", carpeta.root.listFiles()!!.single { ".roto-" in it.name }.readText())
    }
}

class PanelTest {
    private val p = Pendiente("1", "https://youtu.be/a", "gatos", "Aves", 0)

    /** Un panel de mentira que responde una vez. Devuelve el resultado y la petición tal cual llegó. */
    private fun con(codigo: Int, cuerpo: String): Pair<Resultado, String> {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { s ->
            var peticion = ""
            val hilo = thread {
                s.accept().use { x ->
                    val entra = x.getInputStream()
                    val datos = StringBuilder()
                    while (!datos.endsWith("\r\n\r\n")) datos.append(entra.read().toChar())
                    val largo = Regex("""(?i)content-length: (\d+)""").find(datos)!!.groupValues[1].toInt()
                    peticion = datos.toString() + entra.readNBytes(largo).toString(Charsets.UTF_8)
                    val b = cuerpo.toByteArray()
                    x.getOutputStream().write("HTTP/1.1 $codigo X\r\nContent-Length: ${b.size}\r\nConnection: close\r\n\r\n".toByteArray() + b)
                }
            }
            val r = Panel("http://127.0.0.1:${s.localPort}").agregar(p)
            hilo.join()
            return r to peticion
        }
    }

    @Test
    fun `manda el JSON que espera el panel`() {
        val (r, peticion) = con(200, """{"agregados":1,"repetidos":0,"ya_bajados":0,"sin_enlace":0,"en_cola":7}""")

        assertEquals(Resultado.Hecho("Agregado · 7 en cola"), r)
        assertTrue(peticion, peticion.startsWith("POST /api/agregar ") && "Content-Type: application/json\r\n" in peticion)
        val o = JSONObject(peticion.substringAfter("\r\n\r\n"))
        assertEquals("gatos: https://youtu.be/a", o.getString("texto"))
        assertEquals("Aves", o.getString("seccion"))
    }

    @Test
    fun `repetido y ya bajado cuentan como hechos`() {
        assertTrue(con(200, """{"agregados":0,"repetidos":1}""").first is Resultado.Hecho)
        assertTrue(con(200, """{"agregados":0,"ya_bajados":1}""").first is Resultado.Hecho)
    }

    @Test
    fun `solo un 400 o sin enlace se rechazan y lo demas se reintenta`() {
        assertEquals(Resultado.Rechazado("El panel lo rechazó: solo JSON"), con(400, """{"error":"solo JSON"}""").first)
        assertTrue(con(200, """{"sin_enlace":1}""").first is Resultado.Rechazado)
        for ((codigo, cuerpo) in listOf(403 to "{}", 502 to "", 500 to "x", 302 to "", 200 to "<html>", 200 to "{}"))
            assertTrue("$codigo", con(codigo, cuerpo).first is Resultado.Falla)
    }

    @Test
    fun `sin servidor es una falla que se reintenta`() {
        val libre = ServerSocket(0).use { it.localPort }

        assertTrue(Panel("http://127.0.0.1:$libre").agregar(p) is Resultado.Falla)
    }
}

package io.github.christianlealreyes.purrr.player

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/** Resuelve una URL `.pls` (formato playlist de Winamp/Shoutcast, usado por
 * RadioTunes) a la URL de stream real — confirmado que Media3/ExoPlayer no lo
 * hace solo (`google/ExoPlayer#1947`: "ExoPlayer 2's default Extractors do not
 * support the PLS format"), mismo problema que `playbin` de GStreamer en el
 * escritorio. Espejo de `player/pls_resolver.py`.
 *
 * Formato típico:
 *     [playlist]
 *     NumberOfEntries=2
 *     File1=http://prem1.radiotunes.com:80/00scountry_hi
 *     Title1=RadioTunes - 00s Country
 */
object PlsResolver {
    private const val USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"
    private val client = OkHttpClient()

    fun isPlsUrl(url: String): Boolean = url.substringBefore('?').substringBefore('#').endsWith(".pls")

    /** Devuelve la primera URL de stream (`File1=`) del `.pls`. Lanza si no hay
     * ninguna entrada — mejor un error visible que un intento de reproducir un
     * texto vacío en silencio. */
    suspend fun resolvePlsUrl(url: String): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url).header("User-Agent", USER_AGENT).build()
        val text = client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("No se pudo bajar el .pls: ${response.code}")
            response.body?.string() ?: error("El .pls no tiene cuerpo")
        }
        text.lineSequence()
            .map { it.trim() }
            .firstOrNull { it.lowercase().startsWith("file1=") }
            ?.substringAfter('=')
            ?.trim()
            ?: error("El archivo .pls no tiene ninguna entrada de stream: $url")
    }
}

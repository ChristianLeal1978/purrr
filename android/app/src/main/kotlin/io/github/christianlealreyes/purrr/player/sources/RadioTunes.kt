package io.github.christianlealreyes.purrr.player.sources

import io.github.christianlealreyes.purrr.player.Station
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request

/** Catálogo dinámico de RadioTunes (red AudioAddict) — a diferencia de
 * Rainwave/Bío-Bío/SmoothJazz, necesita la Listen Key de una cuenta Premium (ver
 * [RadioTunesConfig]): sin ella no hay audio (confirmado desde el escritorio,
 * `401 Authentication Required` sin key). El catálogo de canales en sí es
 * público, sin auth — confirmado con `curl` contra `listen.radiotunes.com/streamlist`
 * (99 canales). Cada canal resuelve a un `.pls` con la key en la query — ver
 * [io.github.christianlealreyes.purrr.player.PlsResolver], que lo resuelve recién
 * al momento de reproducir. Espejo de `player/sources/radiotunes.py`. */
object RadioTunes {
    private const val STREAMLIST_URL = "http://listen.radiotunes.com/streamlist"
    private const val STREAM_URL_TEMPLATE = "http://listen.radiotunes.com/premium_high/%s.pls?%s"
    private const val USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"

    private val client = OkHttpClient()
    private val json = Json { ignoreUnknownKeys = true }

    @Serializable
    private data class Channel(val key: String, val name: String)

    /** Pega a la red — llamar siempre desde un hilo de fondo. Devuelve vacío si
     * no hay Listen Key guardada — la UI lo interpreta como "falta configurar". */
    suspend fun listStations(listenKey: String?): List<Station> {
        if (listenKey.isNullOrBlank()) return emptyList()
        val body = withContext(Dispatchers.IO) {
            val request = Request.Builder().url(STREAMLIST_URL).header("User-Agent", USER_AGENT).build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) error("RadioTunes devolvió ${response.code}")
                response.body?.string() ?: error("RadioTunes no devolvió cuerpo en la respuesta")
            }
        }
        val channels: List<Channel> = json.decodeFromString(body)
        return channels.map { channel ->
            Station(
                provider = "radiotunes",
                slug = channel.key,
                displayName = channel.name,
                streamUrl = STREAM_URL_TEMPLATE.format(channel.key, listenKey),
                subtitle = null,
            )
        }
    }
}

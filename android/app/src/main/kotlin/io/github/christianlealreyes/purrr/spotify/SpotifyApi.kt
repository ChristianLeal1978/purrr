package io.github.christianlealreyes.purrr.spotify

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

private const val API_BASE = "https://api.spotify.com/v1"

/** Wrapper delgado sobre la Web API de Spotify — mismo rol que `drive/DriveApi.kt`
 * para Drive. Los mismos endpoints REST que ya usa `spotipy` en el escritorio
 * (`spotify_connect.py`/`spotify/client.py`), sin ningún SDK. */
class SpotifyApi(private val accessTokenProvider: suspend () -> String) {
    private val client = OkHttpClient()
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun search(query: String, limit: Int = 15): List<SpotifyTrack> {
        val url = "$API_BASE/search".toHttpUrl().newBuilder()
            .addQueryParameter("q", query)
            .addQueryParameter("type", "track")
            .addQueryParameter("limit", limit.toString())
            .build()
        val response: SearchResponse = get(url.toString())
        return response.tracks.items.map { it.toSpotifyTrack() }
    }

    suspend fun devices(): List<SpotifyDevice> {
        val response: DevicesResponse = get("$API_BASE/me/player/devices")
        return response.devices.map { SpotifyDevice(id = it.id, name = it.name, isActive = it.isActive) }
    }

    suspend fun currentPlayback(): SpotifyPlaybackState? = withContext(Dispatchers.IO) {
        val request = authorizedRequest("$API_BASE/me/player").build()
        client.newCall(request).execute().use { response ->
            if (response.code == 204 || !response.isSuccessful) return@withContext null
            val text = response.body?.string() ?: return@withContext null
            val state = json.decodeFromString<PlaybackStateResponse>(text)
            SpotifyPlaybackState(
                isPlaying = state.isPlaying,
                positionSeconds = (state.progressMs ?: 0) / 1000.0,
                durationSeconds = (state.item?.durationMs ?: 0) / 1000.0,
                trackUri = state.item?.uri,
            )
        }
    }

    suspend fun startPlayback(deviceId: String, uri: String) = withContext(Dispatchers.IO) {
        val url = "$API_BASE/me/player/play".toHttpUrl().newBuilder()
            .addQueryParameter("device_id", deviceId)
            .build()
        val body = json.encodeToString(StartPlaybackBody.serializer(), StartPlaybackBody(listOf(uri)))
            .toRequestBody("application/json".toMediaType())
        val request = authorizedRequest(url.toString()).put(body).build()
        execute(request)
    }

    suspend fun pausePlayback(deviceId: String) = withContext(Dispatchers.IO) {
        val url = "$API_BASE/me/player/pause".toHttpUrl().newBuilder()
            .addQueryParameter("device_id", deviceId)
            .build()
        val body = "".toRequestBody(null)
        val request = authorizedRequest(url.toString()).put(body).build()
        execute(request)
    }

    private suspend fun authorizedRequest(url: String) =
        Request.Builder().url(url).header("Authorization", "Bearer ${accessTokenProvider()}")

    private suspend inline fun <reified T> get(url: String): T = withContext(Dispatchers.IO) {
        val request = authorizedRequest(url).build()
        val text = execute(request)
        json.decodeFromString(text)
    }

    private fun execute(request: Request): String =
        client.newCall(request).execute().use { response ->
            val text = response.body?.string()
            if (!response.isSuccessful) error("Spotify devolvió ${response.code}: $text")
            text ?: ""
        }
}

@Serializable
private data class StartPlaybackBody(val uris: List<String>)

@Serializable
private data class SearchResponse(val tracks: TracksPage)

@Serializable
private data class TracksPage(val items: List<TrackItem>)

@Serializable
private data class TrackItem(
    val id: String,
    val name: String,
    val artists: List<ArtistItem> = emptyList(),
    val album: AlbumItem? = null,
    @SerialName("duration_ms") val durationMs: Long? = null,
    val uri: String,
) {
    fun toSpotifyTrack(): SpotifyTrack {
        val artistNames = artists.joinToString(", ") { it.name }.ifEmpty { null }
        // El array de imágenes viene de mayor a menor resolución; la más chica
        // alcanza de sobra para una miniatura de lista (mismo criterio que
        // `spotify/client.py:_track_from_item` del escritorio).
        val artUrl = album?.images?.lastOrNull()?.url
        return SpotifyTrack(
            id = id,
            title = name,
            artist = artistNames,
            album = album?.name,
            durationSeconds = durationMs?.let { it / 1000.0 },
            artUrl = artUrl,
            uri = uri,
        )
    }
}

@Serializable
private data class ArtistItem(val name: String)

@Serializable
private data class AlbumItem(val name: String? = null, val images: List<ImageItem> = emptyList())

@Serializable
private data class ImageItem(val url: String)

@Serializable
private data class DevicesResponse(val devices: List<DeviceItem> = emptyList())

@Serializable
private data class DeviceItem(val id: String, val name: String, @SerialName("is_active") val isActive: Boolean = false)

@Serializable
private data class PlaybackStateResponse(
    @SerialName("is_playing") val isPlaying: Boolean = false,
    @SerialName("progress_ms") val progressMs: Long? = null,
    val item: PlaybackItem? = null,
)

@Serializable
private data class PlaybackItem(val uri: String? = null, @SerialName("duration_ms") val durationMs: Long? = null)

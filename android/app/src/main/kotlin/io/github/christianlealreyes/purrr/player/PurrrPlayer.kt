package io.github.christianlealreyes.purrr.player

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import java.io.File
import kotlinx.coroutines.guava.await

/**
 * Conecta con [PlaybackService] y expone su `MediaController` — que ya implementa
 * la interfaz `Player` de Media3 (play/pause/seek/siguiente/anterior/shuffle/repeat
 * vienen gratis). A diferencia del escritorio, no hace falta reimplementar una cola
 * propia como `player/queue.py`: `setMediaItems` + `shuffleModeEnabled` +
 * `repeatMode` de Media3 ya cubren lo mismo.
 */
class PurrrPlayer(context: Context) {
    private val appContext = context.applicationContext
    private var controller: MediaController? = null

    suspend fun connect(): MediaController {
        controller?.let { return it }
        val token = SessionToken(appContext, ComponentName(appContext, PlaybackService::class.java))
        val newController = MediaController.Builder(appContext, token).buildAsync().await()
        controller = newController
        return newController
    }

    fun disconnect() {
        controller?.release()
        controller = null
    }

    /** Arma la cola a partir de tracks ya cacheados localmente (con `localPath` no
     * nulo) y arranca la reproducción en `startIndex`. */
    suspend fun setQueue(tracks: List<TrackEntity>, startIndex: Int = 0) {
        val mediaController = connect()
        val items = tracks.mapNotNull { it.toMediaItem() }
        if (items.isEmpty()) return
        mediaController.setMediaItems(items, startIndex.coerceIn(0, items.lastIndex), 0L)
        mediaController.prepare()
        mediaController.play()
    }

    /** Reproduce una estación en vivo — sin cola (no hay "siguiente" para un
     * stream). Resuelve `.pls` primero si hace falta (RadioTunes). */
    suspend fun playStation(station: Station) {
        val streamUrl = if (PlsResolver.isPlsUrl(station.streamUrl)) {
            PlsResolver.resolvePlsUrl(station.streamUrl)
        } else {
            station.streamUrl
        }
        val metadata = MediaMetadata.Builder()
            .setTitle(station.displayName)
            .setArtist(station.subtitle)
            .build()
        val item = MediaItem.Builder()
            .setMediaId("station:${station.provider}:${station.slug}")
            .setUri(Uri.parse(streamUrl))
            .setMediaMetadata(metadata)
            .build()
        val mediaController = connect()
        mediaController.setMediaItem(item)
        mediaController.prepare()
        mediaController.play()
    }
}

private fun TrackEntity.toMediaItem(): MediaItem? {
    val path = localPath ?: return null
    val metadata = MediaMetadata.Builder()
        .setTitle(displayTitle)
        .setArtist(artist)
        .setAlbumTitle(album)
        .build()
    return MediaItem.Builder()
        .setMediaId(trackRef)
        .setUri(Uri.fromFile(File(path)))
        .setMediaMetadata(metadata)
        .build()
}

package io.github.christianlealreyes.purrr.player

import androidx.media3.common.Player
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import io.github.christianlealreyes.purrr.spotify.SpotifyConnectController
import io.github.christianlealreyes.purrr.spotify.SpotifyConnectEvent
import io.github.christianlealreyes.purrr.spotify.SpotifyTrack
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

enum class PlaybackSourceKind { LOCAL, SPOTIFY }

data class NowPlaying(
    val source: PlaybackSourceKind,
    val title: String?,
    val artist: String?,
    val isPlaying: Boolean,
    val isLive: Boolean,
)

/** Punto único que sabe "quién está sonando ahora" — equivalente Android del
 * `_playback_mode` de `ui/playback_bar.py` en el escritorio. Envuelve
 * [PurrrPlayer] (local/radio, vía Media3) y [SpotifyConnectController] (control
 * remoto — el audio suena en *otro* dispositivo, no pasa por Media3), y se
 * asegura de que nunca sueñen los dos a la vez. */
class PlaybackCoordinator(
    private val purrrPlayer: PurrrPlayer,
    private val spotifyController: SpotifyConnectController,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val _nowPlaying = MutableStateFlow<NowPlaying?>(null)
    val nowPlaying: StateFlow<NowPlaying?> = _nowPlaying

    init {
        scope.launch {
            val controller = purrrPlayer.connect()
            controller.addListener(object : Player.Listener {
                override fun onEvents(player: Player, events: Player.Events) {
                    if (_nowPlaying.value?.source == PlaybackSourceKind.SPOTIFY && player.mediaItemCount == 0) {
                        return // el listener sigue conectado aunque estemos en modo Spotify
                    }
                    _nowPlaying.value = NowPlaying(
                        source = PlaybackSourceKind.LOCAL,
                        title = player.mediaMetadata.title?.toString(),
                        artist = player.mediaMetadata.artist?.toString(),
                        isPlaying = player.isPlaying,
                        isLive = player.isCurrentMediaItemLive,
                    )
                }
            })
        }
        scope.launch {
            spotifyController.events.collect { event ->
                val current = _nowPlaying.value
                when (event) {
                    is SpotifyConnectEvent.PositionUpdated -> {
                        if (current != null && current.source == PlaybackSourceKind.SPOTIFY) {
                            _nowPlaying.value = current.copy(isPlaying = event.isPlaying)
                        }
                    }
                    is SpotifyConnectEvent.Ended, is SpotifyConnectEvent.NoDevice, is SpotifyConnectEvent.Error -> {
                        if (current?.source == PlaybackSourceKind.SPOTIFY) _nowPlaying.value = null
                    }
                }
            }
        }
    }

    suspend fun playQueue(tracks: List<TrackEntity>, startIndex: Int = 0) {
        spotifyController.stop()
        purrrPlayer.setQueue(tracks, startIndex)
    }

    suspend fun playStation(station: Station) {
        spotifyController.stop()
        purrrPlayer.playStation(station)
    }

    fun playSpotifyTrack(track: SpotifyTrack) {
        scope.launch { purrrPlayer.connect().pause() }
        _nowPlaying.value = NowPlaying(
            source = PlaybackSourceKind.SPOTIFY,
            title = track.title,
            artist = track.artist,
            isPlaying = true,
            isLive = false,
        )
        spotifyController.play(track)
    }

    fun togglePlayPause() {
        when (_nowPlaying.value?.source) {
            PlaybackSourceKind.SPOTIFY -> {
                if (_nowPlaying.value?.isPlaying == true) spotifyController.pause() else spotifyController.resume()
            }
            PlaybackSourceKind.LOCAL -> scope.launch {
                val controller = purrrPlayer.connect()
                if (controller.isPlaying) controller.pause() else controller.play()
            }
            null -> Unit
        }
    }

    fun seekToPrevious() {
        if (_nowPlaying.value?.source != PlaybackSourceKind.LOCAL) return
        scope.launch { purrrPlayer.connect().seekToPrevious() }
    }

    fun seekToNext() {
        if (_nowPlaying.value?.source != PlaybackSourceKind.LOCAL) return
        scope.launch { purrrPlayer.connect().seekToNext() }
    }
}

package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import io.github.christianlealreyes.purrr.player.PlaybackSourceKind

/** Barra de reproducción persistente abajo — equivalente Android de
 * `ui/playback_bar.py` del escritorio. Observa [PlaybackCoordinator] en vez del
 * `MediaController` directo, porque ahora hay dos fuentes posibles (local/radio
 * vía Media3, o Spotify Connect por control remoto) — mismo rol que el
 * `_playback_mode` del escritorio. */
@Composable
fun PlayerBar(coordinator: PlaybackCoordinator) {
    val nowPlaying by coordinator.nowPlaying.collectAsState()
    val current = nowPlaying ?: return
    val title = current.title ?: return
    // Sin "siguiente/anterior" para una estación en vivo (no tiene cola) ni para
    // Spotify (la cola vive en el dispositivo remoto, no acá) — mismo criterio que
    // `ui/playback_bar.py:_set_station_mode` en el escritorio.
    val showQueueControls = current.source == PlaybackSourceKind.LOCAL && !current.isLive

    Surface(tonalElevation = 4.dp) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(title)
                current.artist?.let { Text(it) }
            }
            if (showQueueControls) {
                IconButton(onClick = { coordinator.seekToPrevious() }) {
                    Icon(Icons.Filled.SkipPrevious, contentDescription = "Anterior")
                }
            }
            IconButton(onClick = { coordinator.togglePlayPause() }) {
                Icon(if (current.isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Reproducir/Pausar")
            }
            if (showQueueControls) {
                IconButton(onClick = { coordinator.seekToNext() }) {
                    Icon(Icons.Filled.SkipNext, contentDescription = "Siguiente")
                }
            }
        }
    }
}

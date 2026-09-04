package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.cache.AudioCache
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import io.github.christianlealreyes.purrr.drive.DriveApi
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import java.time.Instant
import kotlinx.coroutines.launch

/** Pantalla "Biblioteca" (Fase 6.4 del plan): lista buscable de tracks ya
 * escaneados. Tocar una fila descarga el archivo si hace falta (mismo patrón de
 * `sync/controller.py:download_track`) y arranca la cola desde ahí. */
@Composable
fun LibraryScreen(
    db: AppDatabase,
    driveApi: DriveApi,
    audioCache: AudioCache,
    coordinator: PlaybackCoordinator,
) {
    val tracks by db.trackDao().observeAll().collectAsState(initial = emptyList())
    val playlists by db.playlistDao().observeAll().collectAsState(initial = emptyList())
    var query by remember { mutableStateOf("") }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var menuOpenFor by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    val filtered = if (query.isBlank()) {
        tracks
    } else {
        tracks.filter {
            it.displayTitle.contains(query, ignoreCase = true) ||
                it.artist?.contains(query, ignoreCase = true) == true ||
                it.album?.contains(query, ignoreCase = true) == true
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("Buscar") },
            modifier = Modifier.fillMaxWidth(),
        )
        statusMessage?.let { Text(it) }
        LazyColumn {
            items(filtered, key = { it.driveFileId }) { track ->
                ListItem(
                    headlineContent = { Text(track.displayTitle) },
                    supportingContent = { Text(listOfNotNull(track.artist, track.album).joinToString(" — ")) },
                    modifier = Modifier.clickable {
                        scope.launch {
                            statusMessage = "Preparando ${track.displayTitle}…"
                            runCatching { playTrack(track, filtered, db, driveApi, audioCache, coordinator) }
                                .onSuccess { statusMessage = null }
                                .onFailure { statusMessage = "Error: ${it.message}" }
                        }
                    },
                    trailingContent = {
                        IconButton(onClick = { menuOpenFor = track.driveFileId }) {
                            Icon(Icons.AutoMirrored.Filled.PlaylistAdd, contentDescription = "Agregar a playlist")
                        }
                        AddToPlaylistMenu(
                            expanded = menuOpenFor == track.driveFileId,
                            onDismiss = { menuOpenFor = null },
                            playlists = playlists,
                            trackRef = "drive:${track.driveFileId}",
                            db = db,
                            scope = scope,
                            onAdded = { name -> statusMessage = "Agregado a $name." },
                        )
                    },
                )
            }
        }
    }
}

private suspend fun playTrack(
    track: TrackEntity,
    allTracks: List<TrackEntity>,
    db: AppDatabase,
    driveApi: DriveApi,
    audioCache: AudioCache,
    coordinator: PlaybackCoordinator,
) {
    val dest = audioCache.ensureDownloaded(driveApi, track.driveFileId, track.fileName)
    db.trackDao().updateCache(track.driveFileId, dest.absolutePath, "cached", Instant.now().toString())
    val refreshed = db.trackDao().getByDriveFileId(track.driveFileId) ?: track
    val startIndex = allTracks.indexOfFirst { it.driveFileId == track.driveFileId }.coerceAtLeast(0)
    val queue = allTracks.toMutableList().also { it[startIndex] = refreshed }
    coordinator.playQueue(queue, startIndex)
}

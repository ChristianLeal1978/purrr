package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.cloud.enqueuePlaylistUpsert
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.data.entities.PlaylistEntity
import io.github.christianlealreyes.purrr.data.entities.SpotifyTrackEntity
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import io.github.christianlealreyes.purrr.spotify.SpotifyTrack
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.launch

/** Un item de playlist ya resuelto contra la tabla que corresponda según el
 * prefijo de su `trackRef` — mismo split que `db/database.py:list_playlist_tracks`
 * en el escritorio (playlists mixtas Drive + Spotify, Fase 7.2 del plan). */
private sealed interface PlaylistRow {
    data class Drive(val track: TrackEntity) : PlaylistRow
    data class Spotify(val track: SpotifyTrackEntity) : PlaylistRow
}

/** Pantalla "Playlists" (Fase 6.4 del plan): crear playlists (los tracks se agregan
 * desde "Biblioteca"/"Spotify") y reproducirlas. El botón de cabecera reproduce la
 * subsecuencia de Drive como cola local; cada fila de Spotify se reproduce aparte
 * por control remoto — no hay todavía una cola única que avance sola entre las dos
 * fuentes (ver el plan, Fase 7.2). */
@Composable
fun PlaylistsScreen(db: AppDatabase, coordinator: PlaybackCoordinator) {
    val playlists by db.playlistDao().observeAll().collectAsState(initial = emptyList())
    var selected by remember { mutableStateOf<PlaylistEntity?>(null) }
    var newPlaylistName by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    val current = selected
    if (current == null) {
        Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(
                value = newPlaylistName,
                onValueChange = { newPlaylistName = it },
                label = { Text("Nueva playlist") },
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = {
                val name = newPlaylistName.trim()
                if (name.isEmpty()) return@Button
                scope.launch {
                    val uuid = UUID.randomUUID().toString()
                    db.playlistDao().upsert(PlaylistEntity(uuid = uuid, name = name, updatedAt = Instant.now().toString()))
                    db.syncOpDao().enqueuePlaylistUpsert(uuid, name)
                    newPlaylistName = ""
                }
            }) { Text("Crear") }

            LazyColumn {
                items(playlists, key = { it.uuid }) { playlist ->
                    ListItem(
                        headlineContent = { Text(playlist.name) },
                        modifier = Modifier.clickable { selected = playlist },
                    )
                }
            }
        }
    } else {
        val items by db.playlistDao().observeItems(current.uuid).collectAsState(initial = emptyList())
        var resolvedRows by remember { mutableStateOf<List<PlaylistRow>>(emptyList()) }
        LaunchedEffect(items) {
            resolvedRows = items.mapNotNull { item ->
                when {
                    item.trackRef.startsWith("drive:") ->
                        db.trackDao().getByDriveFileId(item.trackRef.removePrefix("drive:"))?.let { PlaylistRow.Drive(it) }
                    item.trackRef.startsWith("spotify:") ->
                        db.spotifyTrackDao().get(item.trackRef.removePrefix("spotify:"))?.let { PlaylistRow.Spotify(it) }
                    else -> null
                }
            }
        }
        Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { selected = null }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver") }
                Text(current.name, modifier = Modifier.fillMaxWidth().padding(start = 4.dp).weight(1f))
                IconButton(onClick = {
                    val driveTracks = resolvedRows.filterIsInstance<PlaylistRow.Drive>().map { it.track }
                    if (driveTracks.isNotEmpty()) scope.launch { coordinator.playQueue(driveTracks, 0) }
                }) { Icon(Icons.Filled.PlayArrow, contentDescription = "Reproducir") }
            }
            LazyColumn {
                items(
                    resolvedRows,
                    key = { row -> when (row) { is PlaylistRow.Drive -> row.track.driveFileId; is PlaylistRow.Spotify -> "spotify:${row.track.id}" } },
                ) { row ->
                    when (row) {
                        is PlaylistRow.Drive -> ListItem(
                            headlineContent = { Text(row.track.displayTitle) },
                            supportingContent = { Text(listOfNotNull(row.track.artist, row.track.album).joinToString(" — ")) },
                            modifier = Modifier.clickable {
                                val driveTracks = resolvedRows.filterIsInstance<PlaylistRow.Drive>().map { it.track }
                                val startIndex = driveTracks.indexOfFirst { it.driveFileId == row.track.driveFileId }.coerceAtLeast(0)
                                scope.launch { coordinator.playQueue(driveTracks, startIndex) }
                            },
                        )
                        is PlaylistRow.Spotify -> ListItem(
                            headlineContent = { Text(row.track.title) },
                            supportingContent = { Text(listOfNotNull(row.track.artist, row.track.album).joinToString(" — ") + " · Spotify") },
                            modifier = Modifier.clickable { coordinator.playSpotifyTrack(row.track.toSpotifyTrack()) },
                        )
                    }
                }
            }
        }
    }
}

private fun SpotifyTrackEntity.toSpotifyTrack() = SpotifyTrack(
    id = id, title = title, artist = artist, album = album,
    durationSeconds = durationSeconds, artUrl = artUrl, uri = uri,
)

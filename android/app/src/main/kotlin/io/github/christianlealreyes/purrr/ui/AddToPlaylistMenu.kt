package io.github.christianlealreyes.purrr.ui

import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import io.github.christianlealreyes.purrr.cloud.enqueuePlaylistItemUpsert
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.data.entities.PlaylistEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistItemEntity
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Menú "agregar a playlist" — reusado desde Biblioteca (tracks de Drive) y
 * Spotify (tracks de Spotify): los dos casos son solo un `trackRef` distinto
 * (`"drive:<id>"` / `"spotify:<id>"`), la mecánica de agregar es idéntica
 * (mismo split que `db/database.py:list_playlist_tracks` en el escritorio). */
@Composable
fun AddToPlaylistMenu(
    expanded: Boolean,
    onDismiss: () -> Unit,
    playlists: List<PlaylistEntity>,
    trackRef: String,
    db: AppDatabase,
    scope: CoroutineScope,
    onAdded: (playlistName: String) -> Unit,
) {
    DropdownMenu(expanded = expanded, onDismissRequest = onDismiss) {
        if (playlists.isEmpty()) {
            DropdownMenuItem(text = { Text("No hay playlists todavía") }, onClick = onDismiss)
        }
        playlists.forEach { playlist ->
            DropdownMenuItem(
                text = { Text(playlist.name) },
                onClick = {
                    onDismiss()
                    scope.launch {
                        val position = db.playlistDao().nextPosition(playlist.uuid)
                        db.playlistDao().upsertItem(
                            PlaylistItemEntity(
                                playlistUuid = playlist.uuid,
                                trackRef = trackRef,
                                position = position,
                                updatedAt = Instant.now().toString(),
                            )
                        )
                        db.syncOpDao().enqueuePlaylistItemUpsert(playlist.uuid, trackRef, position)
                        onAdded(playlist.name)
                    }
                },
            )
        }
    }
}

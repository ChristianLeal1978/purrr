package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.auth.SpotifyAuth
import io.github.christianlealreyes.purrr.auth.SpotifyAuthConfig
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.data.entities.SpotifyTrackEntity
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import io.github.christianlealreyes.purrr.spotify.SpotifyApi
import io.github.christianlealreyes.purrr.spotify.SpotifyConnectController
import io.github.christianlealreyes.purrr.spotify.SpotifyDevice
import io.github.christianlealreyes.purrr.spotify.SpotifyTrack
import java.time.Instant
import kotlinx.coroutines.launch

/** Pantalla "Spotify" (Fase 7.2 del plan): Client ID → conectar (PKCE vía Custom
 * Tabs) → buscador con resultados que se pueden reproducir (control remoto, ver
 * [PlaybackCoordinator]) o agregar a una playlist mixta — mismo esquema que
 * `ui/spotify_view.py` del escritorio. */
@Composable
fun SpotifyScreen(
    db: AppDatabase,
    spotifyAuth: SpotifyAuth,
    spotifyApi: SpotifyApi,
    spotifyController: SpotifyConnectController,
    coordinator: PlaybackCoordinator,
) {
    val context = LocalContext.current
    val authConfig = remember { SpotifyAuthConfig(context) }
    var clientIdInput by remember { mutableStateOf(authConfig.loadClientId() ?: "") }
    var configured by remember { mutableStateOf(spotifyAuth.isConfigured()) }
    var connected by remember { mutableStateOf(spotifyAuth.isConnected()) }
    var query by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<SpotifyTrack>>(emptyList()) }
    var devices by remember { mutableStateOf<List<SpotifyDevice>>(emptyList()) }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var menuOpenForId by remember { mutableStateOf<String?>(null) }
    val playlists by db.playlistDao().observeAll().collectAsState(initial = emptyList())
    val scope = rememberCoroutineScope()

    LaunchedEffect(connected) {
        if (connected) devices = spotifyController.listDevices()
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (!configured) {
            OutlinedTextField(
                value = clientIdInput,
                onValueChange = { clientIdInput = it },
                label = { Text("Client ID de Spotify") },
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = {
                authConfig.saveClientId(clientIdInput.trim())
                configured = true
            }) { Text("Guardar") }
        } else if (!connected) {
            Button(onClick = {
                scope.launch {
                    runCatching { spotifyAuth.connect() }
                        .onSuccess { connected = true }
                        .onFailure { statusMessage = "Error: ${it.message}" }
                }
            }) { Text("Conectar con Spotify") }
        } else {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text("Buscar en Spotify") },
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = {
                scope.launch {
                    runCatching { spotifyApi.search(query) }
                        .onSuccess { results = it }
                        .onFailure { statusMessage = "Error: ${it.message}" }
                }
            }) { Text("Buscar") }

            statusMessage?.let { Text(it) }

            LazyColumn(modifier = Modifier.weight(1f, fill = false)) {
                items(results, key = { it.id }) { track ->
                    ListItem(
                        headlineContent = { Text(track.title) },
                        supportingContent = { Text(listOfNotNull(track.artist, track.album).joinToString(" — ")) },
                        leadingContent = {
                            IconButton(onClick = { coordinator.playSpotifyTrack(track) }) {
                                Icon(Icons.Filled.PlayArrow, contentDescription = "Reproducir")
                            }
                        },
                        trailingContent = {
                            IconButton(onClick = { menuOpenForId = track.id }) {
                                Icon(Icons.AutoMirrored.Filled.PlaylistAdd, contentDescription = "Agregar a playlist")
                            }
                            AddToPlaylistMenu(
                                expanded = menuOpenForId == track.id,
                                onDismiss = { menuOpenForId = null },
                                playlists = playlists,
                                trackRef = "spotify:${track.id}",
                                db = db,
                                scope = scope,
                                onAdded = { name ->
                                    scope.launch { cacheSpotifyTrack(db, track) }
                                    statusMessage = "Agregado a $name."
                                },
                            )
                        },
                    )
                }
            }

            Text("Dispositivos Spotify Connect disponibles")
            LazyColumn {
                items(devices, key = { it.id }) { device ->
                    ListItem(headlineContent = { Text(device.name) }, supportingContent = if (device.isActive) { { Text("Activo") } } else null)
                }
            }
        }
    }
}

private suspend fun cacheSpotifyTrack(db: AppDatabase, track: SpotifyTrack) {
    db.spotifyTrackDao().upsert(
        SpotifyTrackEntity(
            id = track.id,
            title = track.title,
            artist = track.artist,
            album = track.album,
            durationSeconds = track.durationSeconds,
            artUrl = track.artUrl,
            uri = track.uri,
            cachedAt = Instant.now().toString(),
        )
    )
}

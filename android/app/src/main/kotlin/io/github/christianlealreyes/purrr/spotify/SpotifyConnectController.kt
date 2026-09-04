package io.github.christianlealreyes.purrr.spotify

import io.github.christianlealreyes.purrr.auth.SpotifyAuth
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch

private const val POLL_INTERVAL_MS = 3_000L

sealed interface SpotifyConnectEvent {
    data class PositionUpdated(val positionSeconds: Double, val durationSeconds: Double, val isPlaying: Boolean) : SpotifyConnectEvent
    data object Ended : SpotifyConnectEvent
    data object NoDevice : SpotifyConnectEvent
    data class Error(val message: String) : SpotifyConnectEvent
}

/** Control remoto de Spotify Connect — espejo de `player/spotify_connect.py` del
 * escritorio (corrutinas en vez de hilos + `GLib.idle_add`): Purrr nunca decodifica
 * el audio de Spotify, solo le manda comandos a un dispositivo Connect ya activo y
 * consulta su estado por polling. */
class SpotifyConnectController(private val auth: SpotifyAuth, private val api: SpotifyApi) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var pollJob: Job? = null
    private var deviceId: String? = null

    private val _events = MutableSharedFlow<SpotifyConnectEvent>(extraBufferCapacity = 4)
    val events: SharedFlow<SpotifyConnectEvent> = _events

    fun play(track: SpotifyTrack) {
        stop()
        if (!auth.isConnected()) {
            _events.tryEmit(SpotifyConnectEvent.Error("No hay una sesión de Spotify activa."))
            return
        }
        pollJob = scope.launch { startAndPoll(track) }
    }

    /** Para el polling — no manda pausa a Spotify: el usuario puede querer seguir
     * escuchando ahí mismo aunque Purrr pase a otra cosa. */
    fun stop() {
        pollJob?.cancel()
        pollJob = null
        deviceId = null
    }

    fun pause() {
        val id = deviceId ?: return
        scope.launch {
            runCatching { api.pausePlayback(id) }
                .onFailure { _events.emit(SpotifyConnectEvent.Error(it.message ?: "error")) }
        }
    }

    fun resume() {
        val id = deviceId ?: return
        val uri = lastTrackUri ?: return
        scope.launch {
            runCatching { api.startPlayback(id, uri) }
                .onFailure { _events.emit(SpotifyConnectEvent.Error(it.message ?: "error")) }
        }
    }

    /** Lectura de solo consulta para la UI ("Dispositivos disponibles"). */
    suspend fun listDevices(): List<SpotifyDevice> {
        if (!auth.isConnected()) return emptyList()
        return runCatching { api.devices() }.getOrDefault(emptyList())
    }

    private var lastTrackUri: String? = null

    private suspend fun startAndPoll(track: SpotifyTrack) {
        val devices = runCatching { api.devices() }.getOrElse {
            _events.emit(SpotifyConnectEvent.Error(it.message ?: "error"))
            return
        }
        if (devices.isEmpty()) {
            _events.emit(SpotifyConnectEvent.NoDevice)
            return
        }
        val device = devices.firstOrNull { it.isActive } ?: devices.first()
        deviceId = device.id
        lastTrackUri = track.uri
        runCatching { api.startPlayback(device.id, track.uri) }.onFailure {
            _events.emit(SpotifyConnectEvent.Error(it.message ?: "error"))
            return
        }
        pollLoop(track)
    }

    private suspend fun pollLoop(track: SpotifyTrack) {
        while (true) {
            delay(POLL_INTERVAL_MS)
            val state = runCatching { api.currentPlayback() }.getOrElse {
                _events.emit(SpotifyConnectEvent.Error(it.message ?: "error"))
                return
            }
            if (state == null) {
                _events.emit(SpotifyConnectEvent.Ended)
                return
            }
            val duration = if (state.durationSeconds > 0) state.durationSeconds else (track.durationSeconds ?: 0.0)
            val sameTrack = state.trackUri == track.uri
            val finished = !sameTrack || (!state.isPlaying && duration > 0 && state.positionSeconds >= duration - 1)
            if (finished) {
                _events.emit(SpotifyConnectEvent.Ended)
                return
            }
            _events.emit(SpotifyConnectEvent.PositionUpdated(state.positionSeconds, duration, state.isPlaying))
        }
    }
}

package io.github.christianlealreyes.purrr.cloud

import android.content.Context
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.data.entities.AlbumEntity
import io.github.christianlealreyes.purrr.data.entities.AlbumItemEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistItemEntity
import io.github.christianlealreyes.purrr.data.entities.TrackMoodEntity
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.realtime.HasRecord
import io.github.jan.supabase.realtime.PostgresAction
import io.github.jan.supabase.realtime.channel
import io.github.jan.supabase.realtime.decodeRecord
import io.github.jan.supabase.realtime.postgresChangeFlow
import io.github.jan.supabase.realtime.realtime
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Motor de sync en tiempo real con Supabase — espejo de `cloud/sync_engine.py` del
 * escritorio. Sincroniza `playlists`/`playlist_items`/`albums`/`album_items` (push +
 * pull, Fase 6.2) y `track_moods` (**solo pull** — Android nunca calcula vectores de
 * ánimo, solo los recibe del escritorio, Fase 7.3). Sin carátulas compartidas ni
 * Spotify (Spotify no tiene tabla propia que sincronizar: solo agrega tracks a
 * `playlist_items`, que ya sincroniza igual que cualquier otro `track_ref`).
 * A diferencia del escritorio (que necesita un hilo aparte con su propio event loop
 * de asyncio porque el cliente realtime de `supabase-py` no tiene variante sync),
 * acá corrutinas alcanzan directo: `postgresChangeFlow` ya es suspend-friendly de
 * punta a punta.
 *
 * **Contrato de `pending_sync_ops.payloadJson`**: cada mutación local (capa de
 * Repository, todavía no escrita) serializa uno de los `*PushPayload` de abajo con
 * `Json.encodeToString` antes de encolar la fila — mismo campo `tableName` que el
 * `Push*Payload` correspondiente.
 */
class CloudSyncEngine(context: Context) {
    private val appContext = context.applicationContext
    private val db = AppDatabase.get(appContext)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    private val _playlistsChanged = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val playlistsChanged: SharedFlow<Unit> = _playlistsChanged

    private val _albumsChanged = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val albumsChanged: SharedFlow<Unit> = _albumsChanged

    private val _syncErrors = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val syncErrors: SharedFlow<String> = _syncErrors

    /** Idempotente — no hace nada si Supabase todavía no está configurado o no hay
     * sesión iniciada, así se puede llamar siempre al arrancar la app. */
    fun start() {
        if (job?.isActive == true) return
        val client = SupabaseClientProvider.get(appContext) ?: return
        job = scope.launch {
            launch { flushLoop(client) }
            launch { realtimeLoop(client) }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    // --- push: drena pending_sync_ops -------------------------------------

    private suspend fun flushLoop(client: SupabaseClient) {
        while (true) {
            try {
                flushOnce(client)
            } catch (e: Exception) {
                _syncErrors.emit("push: ${e.message}")
            }
            delay(FLUSH_INTERVAL_MS)
        }
    }

    private suspend fun flushOnce(client: SupabaseClient) {
        val ops = db.syncOpDao().listPending()
        for (op in ops) {
            pushOp(client, op.tableName, op.payloadJson)
            // Si pushOp de arriba lanza, esta fila (y las siguientes del batch) se
            // quedan en la cola para el próximo ciclo — no se llega a este delete.
            db.syncOpDao().delete(op)
        }
    }

    private suspend fun pushOp(client: SupabaseClient, tableName: String, payloadJson: String) {
        val postgrest = client.postgrest
        when (tableName) {
            "playlists" -> pushPlaylist(postgrest, JSON.decodeFromString(payloadJson))
            "playlist_items" -> pushPlaylistItem(postgrest, JSON.decodeFromString(payloadJson))
            "albums" -> pushAlbum(postgrest, JSON.decodeFromString(payloadJson))
            "album_items" -> pushAlbumItem(postgrest, JSON.decodeFromString(payloadJson))
        }
    }

    private suspend fun pushPlaylist(postgrest: io.github.jan.supabase.postgrest.Postgrest, payload: PlaylistPushPayload) {
        if (payload.deleted) {
            postgrest.from("playlists").update({ set("deleted_at", nowIso()) }) {
                filter { eq("uuid", payload.uuid) }
            }
            return
        }
        postgrest.from("playlists").upsert(
            RemotePlaylist(uuid = payload.uuid, name = payload.name ?: "", updatedAt = nowIso(), deletedAt = null)
        ) { onConflict = "uuid" }
    }

    private suspend fun pushPlaylistItem(postgrest: io.github.jan.supabase.postgrest.Postgrest, payload: PlaylistItemPushPayload) {
        if (payload.deleted) {
            postgrest.from("playlist_items").update({ set("deleted_at", nowIso()) }) {
                filter {
                    eq("playlist_uuid", payload.playlistUuid)
                    eq("track_ref", payload.trackRef)
                }
            }
            return
        }
        postgrest.from("playlist_items").upsert(
            RemotePlaylistItem(
                playlistUuid = payload.playlistUuid,
                trackRef = payload.trackRef,
                position = payload.position,
                updatedAt = nowIso(),
                deletedAt = null,
            )
        ) { onConflict = "playlist_uuid,track_ref" }
    }

    private suspend fun pushAlbum(postgrest: io.github.jan.supabase.postgrest.Postgrest, payload: AlbumPushPayload) {
        if (payload.deleted) {
            postgrest.from("albums").update({ set("deleted_at", nowIso()) }) {
                filter { eq("uuid", payload.uuid) }
            }
            return
        }
        postgrest.from("albums").upsert(
            RemoteAlbum(uuid = payload.uuid, name = payload.name ?: "", artist = payload.artist, updatedAt = nowIso(), deletedAt = null)
        ) { onConflict = "uuid" }
    }

    private suspend fun pushAlbumItem(postgrest: io.github.jan.supabase.postgrest.Postgrest, payload: AlbumItemPushPayload) {
        if (payload.deleted) {
            postgrest.from("album_items").update({ set("deleted_at", nowIso()) }) {
                filter {
                    eq("album_uuid", payload.albumUuid)
                    eq("track_ref", payload.trackRef)
                }
            }
            return
        }
        postgrest.from("album_items").upsert(
            RemoteAlbumItem(albumUuid = payload.albumUuid, trackRef = payload.trackRef, updatedAt = nowIso(), deletedAt = null)
        ) { onConflict = "album_uuid,track_ref" }
    }

    // --- pull: suscripción realtime -----------------------------------------

    private suspend fun realtimeLoop(client: SupabaseClient) {
        while (true) {
            try {
                realtimeSession(client)
            } catch (e: Exception) {
                _syncErrors.emit("realtime: ${e.message}")
            }
            delay(RECONNECT_DELAY_MS)
        }
    }

    private suspend fun realtimeSession(client: SupabaseClient) {
        val channel = client.channel("purrr-sync")

        channel.postgresChangeFlow<PostgresAction>(schema = "public") { table = "playlists" }
            .onEach { applyPlaylist(it) }.launchIn(scope)
        channel.postgresChangeFlow<PostgresAction>(schema = "public") { table = "playlist_items" }
            .onEach { applyPlaylistItem(it) }.launchIn(scope)
        channel.postgresChangeFlow<PostgresAction>(schema = "public") { table = "albums" }
            .onEach { applyAlbum(it) }.launchIn(scope)
        channel.postgresChangeFlow<PostgresAction>(schema = "public") { table = "album_items" }
            .onEach { applyAlbumItem(it) }.launchIn(scope)
        channel.postgresChangeFlow<PostgresAction>(schema = "public") { table = "track_moods" }
            .onEach { applyTrackMood(it) }.launchIn(scope)

        channel.subscribe(blockUntilSubscribed = true)
        try {
            while (true) delay(1_000)
        } finally {
            client.realtime.removeChannel(channel)
        }
    }

    private fun recordOf(action: PostgresAction): HasRecord? = when (action) {
        is PostgresAction.Insert -> action
        is PostgresAction.Update -> action
        else -> null // Deletes son siempre soft (UPDATE con deleted_at) — ver cloud/schema.sql
    }

    private suspend fun applyPlaylist(action: PostgresAction) {
        val record = recordOf(action)?.decodeRecord<RemotePlaylist>() ?: return
        val local = db.playlistDao().get(record.uuid)
        if (local != null && !isNewerOrEqual(record.updatedAt, local.updatedAt)) return
        db.playlistDao().upsert(
            PlaylistEntity(
                uuid = record.uuid,
                name = record.name,
                updatedAt = record.updatedAt ?: nowIso(),
                deletedAt = record.deletedAt,
            )
        )
        _playlistsChanged.emit(Unit)
    }

    private suspend fun applyPlaylistItem(action: PostgresAction) {
        val record = recordOf(action)?.decodeRecord<RemotePlaylistItem>() ?: return
        if (db.playlistDao().get(record.playlistUuid) == null) {
            // La playlist todavía no llegó por sync a este dispositivo — se resuelve
            // sola cuando llegue (mismo caso conocido que en el escritorio).
            return
        }
        val local = db.playlistDao().getItem(record.playlistUuid, record.trackRef)
        if (local != null && !isNewerOrEqual(record.updatedAt, local.updatedAt)) return
        db.playlistDao().upsertItem(
            PlaylistItemEntity(
                playlistUuid = record.playlistUuid,
                trackRef = record.trackRef,
                position = record.position,
                updatedAt = record.updatedAt ?: nowIso(),
                deletedAt = record.deletedAt,
            )
        )
        _playlistsChanged.emit(Unit)
    }

    private suspend fun applyAlbum(action: PostgresAction) {
        val record = recordOf(action)?.decodeRecord<RemoteAlbum>() ?: return
        val local = db.albumDao().get(record.uuid)
        if (local != null && !isNewerOrEqual(record.updatedAt, local.updatedAt)) return
        db.albumDao().upsert(
            AlbumEntity(
                uuid = record.uuid,
                name = record.name,
                artist = record.artist,
                updatedAt = record.updatedAt ?: nowIso(),
                deletedAt = record.deletedAt,
            )
        )
        _albumsChanged.emit(Unit)
    }

    private suspend fun applyAlbumItem(action: PostgresAction) {
        val record = recordOf(action)?.decodeRecord<RemoteAlbumItem>() ?: return
        if (db.albumDao().get(record.albumUuid) == null) return
        val local = db.albumDao().getItem(record.albumUuid, record.trackRef)
        if (local != null && !isNewerOrEqual(record.updatedAt, local.updatedAt)) return
        db.albumDao().upsertItem(
            AlbumItemEntity(
                albumUuid = record.albumUuid,
                trackRef = record.trackRef,
                updatedAt = record.updatedAt ?: nowIso(),
                deletedAt = record.deletedAt,
            )
        )
        _albumsChanged.emit(Unit)
    }

    private suspend fun applyTrackMood(action: PostgresAction) {
        val record = recordOf(action)?.decodeRecord<RemoteTrackMood>() ?: return
        val local = db.trackMoodDao().get(record.trackRef)
        if (local != null && !isNewerOrEqual(record.updatedAt, local.updatedAt)) return
        db.trackMoodDao().upsert(
            TrackMoodEntity(
                trackRef = record.trackRef,
                happy = record.happy,
                sad = record.sad,
                relaxed = record.relaxed,
                aggressive = record.aggressive,
                updatedAt = record.updatedAt ?: nowIso(),
            )
        )
        // A diferencia de playlists/álbumes, nada en la UI necesita refrescarse en
        // vivo por esto todavía — por eso no emite señal, solo aplica el guardado
        // (mismo criterio que `cloud/sync_engine.py:_apply_track_mood`).
    }

    companion object {
        private const val FLUSH_INTERVAL_MS = 3_000L
        private const val RECONNECT_DELAY_MS = 5_000L
        private val JSON = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
    }
}

private fun nowIso(): String = Instant.now().toString()

/** True si `incoming` no es más viejo que `local` — last-write-wins. Sin dato local
 * todavía, o sin timestamp entrante, gana igual (se aplica). */
private fun isNewerOrEqual(incoming: String?, local: String?): Boolean {
    if (local == null || incoming == null) return true
    return try {
        !Instant.parse(incoming).isBefore(Instant.parse(local))
    } catch (e: Exception) {
        true
    }
}

// --- Payloads locales encolados en pending_sync_ops (ver el contrato arriba) ----

@Serializable
data class PlaylistPushPayload(val uuid: String, val name: String? = null, val deleted: Boolean = false)

@Serializable
data class PlaylistItemPushPayload(
    val playlistUuid: String,
    val trackRef: String,
    val position: Int = 0,
    val deleted: Boolean = false,
)

@Serializable
data class AlbumPushPayload(val uuid: String, val name: String? = null, val artist: String? = null, val deleted: Boolean = false)

@Serializable
data class AlbumItemPushPayload(val albumUuid: String, val trackRef: String, val deleted: Boolean = false)

// --- Forma de las filas remotas en Postgres (cloud/schema.sql del escritorio) ---

@Serializable
data class RemotePlaylist(
    val uuid: String,
    val name: String,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class RemotePlaylistItem(
    @SerialName("playlist_uuid") val playlistUuid: String,
    @SerialName("track_ref") val trackRef: String,
    val position: Int,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class RemoteAlbum(
    val uuid: String,
    val name: String,
    val artist: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class RemoteAlbumItem(
    @SerialName("album_uuid") val albumUuid: String,
    @SerialName("track_ref") val trackRef: String,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class RemoteTrackMood(
    @SerialName("track_ref") val trackRef: String,
    val happy: Float,
    val sad: Float,
    val relaxed: Float,
    val aggressive: Float,
    @SerialName("updated_at") val updatedAt: String? = null,
)

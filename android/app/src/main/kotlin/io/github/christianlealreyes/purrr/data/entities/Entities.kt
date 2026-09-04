package io.github.christianlealreyes.purrr.data.entities

import androidx.room.Entity
import androidx.room.PrimaryKey

/** Una carpeta de Drive agregada como fuente — igual que `sources` en el escritorio,
 * sin la columna `provider` (acá siempre es Drive). */
@Entity(tableName = "sources")
data class SourceEntity(
    @PrimaryKey val driveFolderId: String,
    val displayName: String,
    val lastScannedAt: String? = null,
)

/** Espejo recortado de `tracks` del escritorio — sin las columnas de escaneo parcial
 * por partes ni portada de carpeta, que en v1 de Android no aplican (ver el plan). */
@Entity(tableName = "tracks")
data class TrackEntity(
    @PrimaryKey val driveFileId: String,
    val sourceFolderId: String,
    val driveParentId: String?,
    val driveFolderPath: String?,
    val fileName: String,
    val mimeType: String,
    val driveMd5: String?,
    val driveModifiedTime: String?,
    val localPath: String?,
    val cacheStatus: String, // pending | downloading | cached | error | missing
    val title: String?,
    val artist: String?,
    val album: String?,
    val trackNumber: Int?,
    val discNumber: Int?,
    val durationSeconds: Double?,
    val artPath: String?,
    val updatedAt: String,
) {
    /** Misma identidad estable que usa el escritorio para sincronizar
     * (`cloud/identity.py` en Python) — "drive:<drive_file_id>". */
    val trackRef: String get() = "drive:$driveFileId"

    val displayTitle: String get() = title ?: fileName
}

@Entity(tableName = "playlists")
data class PlaylistEntity(
    @PrimaryKey val uuid: String,
    val name: String,
    val updatedAt: String,
    val deletedAt: String? = null,
)

@Entity(tableName = "playlist_items", primaryKeys = ["playlistUuid", "trackRef"])
data class PlaylistItemEntity(
    val playlistUuid: String,
    val trackRef: String,
    val position: Int,
    val updatedAt: String,
    val deletedAt: String? = null,
)

@Entity(tableName = "albums")
data class AlbumEntity(
    @PrimaryKey val uuid: String,
    val name: String,
    val artist: String?,
    val updatedAt: String,
    val deletedAt: String? = null,
)

@Entity(tableName = "album_items", primaryKeys = ["albumUuid", "trackRef"])
data class AlbumItemEntity(
    val albumUuid: String,
    val trackRef: String,
    val updatedAt: String,
    val deletedAt: String? = null,
)

/** Cola de salida hacia Supabase — mismo rol que `pending_sync_ops` en
 * `db/schema.sql` del escritorio: un "flusher" la drena y borra lo ya enviado. */
@Entity(tableName = "pending_sync_ops")
data class PendingSyncOpEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val tableName: String,
    val payloadJson: String,
    val createdAt: String,
)

/** Metadata cacheada de un track de Spotify agregado a una playlist mixta — mismas
 * columnas que `spotify_tracks` del escritorio (Fase 4). Purrr nunca descarga el
 * audio de Spotify, solo lo necesario para mostrar la fila y controlar Connect. */
@Entity(tableName = "spotify_tracks")
data class SpotifyTrackEntity(
    @PrimaryKey val id: String,
    val title: String,
    val artist: String?,
    val album: String?,
    val durationSeconds: Double?,
    val artUrl: String?,
    val uri: String, // 'spotify:track:<id>'
    val cachedAt: String,
)

/** Vector de ánimo (happy/sad/relaxed/aggressive) de un track — Android nunca lo
 * calcula, solo lo recibe por sync desde el escritorio (Fase 7.3 del plan, tabla
 * remota `track_moods`). Clave por `trackRef`, no por id local: la tabla remota ya
 * usa `track_ref text primary key` (Fase 5.2 del escritorio) y acá no hace falta
 * el esquema dual id-local/uuid que sí necesita el escritorio. */
@Entity(tableName = "track_moods")
data class TrackMoodEntity(
    @PrimaryKey val trackRef: String,
    val happy: Float,
    val sad: Float,
    val relaxed: Float,
    val aggressive: Float,
    val updatedAt: String,
)

package io.github.christianlealreyes.purrr.cloud

import io.github.christianlealreyes.purrr.data.dao.SyncOpDao
import io.github.christianlealreyes.purrr.data.entities.PendingSyncOpEntity
import java.time.Instant
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/** Encola una mutación local para que [CloudSyncEngine] la empuje a Supabase —
 * equivalente Android de `_enqueue_sync_op` en `db/database.py` del escritorio.
 * Mismo contrato de payload documentado en `SyncEngine.kt`. */
private val json = Json

suspend fun SyncOpDao.enqueuePlaylistUpsert(uuid: String, name: String) {
    enqueue(pendingOp("playlists", json.encodeToString(PlaylistPushPayload(uuid = uuid, name = name))))
}

suspend fun SyncOpDao.enqueuePlaylistDelete(uuid: String) {
    enqueue(pendingOp("playlists", json.encodeToString(PlaylistPushPayload(uuid = uuid, deleted = true))))
}

suspend fun SyncOpDao.enqueuePlaylistItemUpsert(playlistUuid: String, trackRef: String, position: Int) {
    enqueue(
        pendingOp(
            "playlist_items",
            json.encodeToString(PlaylistItemPushPayload(playlistUuid = playlistUuid, trackRef = trackRef, position = position)),
        )
    )
}

suspend fun SyncOpDao.enqueuePlaylistItemDelete(playlistUuid: String, trackRef: String) {
    enqueue(
        pendingOp(
            "playlist_items",
            json.encodeToString(PlaylistItemPushPayload(playlistUuid = playlistUuid, trackRef = trackRef, deleted = true)),
        )
    )
}

suspend fun SyncOpDao.enqueueAlbumUpsert(uuid: String, name: String, artist: String?) {
    enqueue(pendingOp("albums", json.encodeToString(AlbumPushPayload(uuid = uuid, name = name, artist = artist))))
}

suspend fun SyncOpDao.enqueueAlbumItemUpsert(albumUuid: String, trackRef: String) {
    enqueue(pendingOp("album_items", json.encodeToString(AlbumItemPushPayload(albumUuid = albumUuid, trackRef = trackRef))))
}

private fun pendingOp(tableName: String, payloadJson: String) =
    PendingSyncOpEntity(tableName = tableName, payloadJson = payloadJson, createdAt = Instant.now().toString())

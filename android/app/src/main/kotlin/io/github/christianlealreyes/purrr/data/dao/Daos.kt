package io.github.christianlealreyes.purrr.data.dao

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Upsert
import io.github.christianlealreyes.purrr.data.entities.AlbumEntity
import io.github.christianlealreyes.purrr.data.entities.AlbumItemEntity
import io.github.christianlealreyes.purrr.data.entities.PendingSyncOpEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistItemEntity
import io.github.christianlealreyes.purrr.data.entities.SourceEntity
import io.github.christianlealreyes.purrr.data.entities.SpotifyTrackEntity
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import io.github.christianlealreyes.purrr.data.entities.TrackMoodEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface SourceDao {
    @Query("SELECT * FROM sources ORDER BY displayName")
    fun observeAll(): Flow<List<SourceEntity>>

    @Upsert
    suspend fun upsert(source: SourceEntity)

    @Query("UPDATE sources SET lastScannedAt = :timestamp WHERE driveFolderId = :driveFolderId")
    suspend fun touchScanned(driveFolderId: String, timestamp: String)
}

@Dao
interface TrackDao {
    @Query("SELECT * FROM tracks WHERE cacheStatus != 'missing' ORDER BY artist, album, trackNumber")
    fun observeAll(): Flow<List<TrackEntity>>

    @Query("SELECT * FROM tracks WHERE driveFileId = :driveFileId")
    suspend fun getByDriveFileId(driveFileId: String): TrackEntity?

    @Query("SELECT * FROM tracks WHERE driveFileId IN (:driveFileIds)")
    suspend fun getByDriveFileIds(driveFileIds: List<String>): List<TrackEntity>

    @Upsert
    suspend fun upsert(track: TrackEntity)

    @Query(
        "UPDATE tracks SET localPath = :localPath, cacheStatus = :status, updatedAt = :updatedAt " +
            "WHERE driveFileId = :driveFileId"
    )
    suspend fun updateCache(driveFileId: String, localPath: String?, status: String, updatedAt: String)
}

@Dao
interface PlaylistDao {
    @Query("SELECT * FROM playlists WHERE deletedAt IS NULL ORDER BY name")
    fun observeAll(): Flow<List<PlaylistEntity>>

    @Query("SELECT * FROM playlists WHERE uuid = :uuid")
    suspend fun get(uuid: String): PlaylistEntity?

    @Upsert
    suspend fun upsert(playlist: PlaylistEntity)

    @Query("SELECT * FROM playlist_items WHERE playlistUuid = :playlistUuid AND deletedAt IS NULL ORDER BY position")
    fun observeItems(playlistUuid: String): Flow<List<PlaylistItemEntity>>

    @Query("SELECT * FROM playlist_items WHERE playlistUuid = :playlistUuid AND trackRef = :trackRef")
    suspend fun getItem(playlistUuid: String, trackRef: String): PlaylistItemEntity?

    @Upsert
    suspend fun upsertItem(item: PlaylistItemEntity)

    @Query("SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_items WHERE playlistUuid = :playlistUuid")
    suspend fun nextPosition(playlistUuid: String): Int
}

@Dao
interface AlbumDao {
    @Query(
        "SELECT a.* FROM albums a WHERE a.deletedAt IS NULL AND EXISTS (" +
            "SELECT 1 FROM album_items ai WHERE ai.albumUuid = a.uuid AND ai.deletedAt IS NULL" +
            ") ORDER BY a.name"
    )
    fun observeAll(): Flow<List<AlbumEntity>>

    @Query("SELECT * FROM albums WHERE uuid = :uuid")
    suspend fun get(uuid: String): AlbumEntity?

    @Query("SELECT * FROM albums WHERE name = :name COLLATE NOCASE AND artist IS :artist COLLATE NOCASE LIMIT 1")
    suspend fun findByNameAndArtist(name: String, artist: String?): AlbumEntity?

    @Upsert
    suspend fun upsert(album: AlbumEntity)

    @Query("SELECT * FROM album_items WHERE albumUuid = :albumUuid AND deletedAt IS NULL")
    fun observeItems(albumUuid: String): Flow<List<AlbumItemEntity>>

    @Query("SELECT * FROM album_items WHERE albumUuid = :albumUuid AND trackRef = :trackRef")
    suspend fun getItem(albumUuid: String, trackRef: String): AlbumItemEntity?

    @Upsert
    suspend fun upsertItem(item: AlbumItemEntity)
}

@Dao
interface SyncOpDao {
    @Query("SELECT * FROM pending_sync_ops ORDER BY id LIMIT :limit")
    suspend fun listPending(limit: Int = 100): List<PendingSyncOpEntity>

    @Insert
    suspend fun enqueue(op: PendingSyncOpEntity)

    @Delete
    suspend fun delete(op: PendingSyncOpEntity)
}

@Dao
interface SpotifyTrackDao {
    @Query("SELECT * FROM spotify_tracks WHERE id = :id")
    suspend fun get(id: String): SpotifyTrackEntity?

    @Upsert
    suspend fun upsert(track: SpotifyTrackEntity)
}

@Dao
interface TrackMoodDao {
    @Query("SELECT * FROM track_moods")
    fun observeAll(): Flow<List<TrackMoodEntity>>

    @Query("SELECT * FROM track_moods WHERE trackRef = :trackRef")
    suspend fun get(trackRef: String): TrackMoodEntity?

    @Upsert
    suspend fun upsert(mood: TrackMoodEntity)
}

package io.github.christianlealreyes.purrr.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import io.github.christianlealreyes.purrr.data.dao.AlbumDao
import io.github.christianlealreyes.purrr.data.dao.PlaylistDao
import io.github.christianlealreyes.purrr.data.dao.SourceDao
import io.github.christianlealreyes.purrr.data.dao.SpotifyTrackDao
import io.github.christianlealreyes.purrr.data.dao.SyncOpDao
import io.github.christianlealreyes.purrr.data.dao.TrackDao
import io.github.christianlealreyes.purrr.data.dao.TrackMoodDao
import io.github.christianlealreyes.purrr.data.entities.AlbumEntity
import io.github.christianlealreyes.purrr.data.entities.AlbumItemEntity
import io.github.christianlealreyes.purrr.data.entities.PendingSyncOpEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistEntity
import io.github.christianlealreyes.purrr.data.entities.PlaylistItemEntity
import io.github.christianlealreyes.purrr.data.entities.SourceEntity
import io.github.christianlealreyes.purrr.data.entities.SpotifyTrackEntity
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import io.github.christianlealreyes.purrr.data.entities.TrackMoodEntity

@Database(
    entities = [
        SourceEntity::class,
        TrackEntity::class,
        PlaylistEntity::class,
        PlaylistItemEntity::class,
        AlbumEntity::class,
        AlbumItemEntity::class,
        PendingSyncOpEntity::class,
        SpotifyTrackEntity::class,
        TrackMoodEntity::class,
    ],
    version = 2,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun sourceDao(): SourceDao
    abstract fun trackDao(): TrackDao
    abstract fun playlistDao(): PlaylistDao
    abstract fun albumDao(): AlbumDao
    abstract fun syncOpDao(): SyncOpDao
    abstract fun spotifyTrackDao(): SpotifyTrackDao
    abstract fun trackMoodDao(): TrackMoodDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "purrr.db",
                )
                    // Todavía no se distribuyó ningún APK de v1 a usuarios reales —
                    // no hay datos que preservar entre versiones de schema todavía.
                    .fallbackToDestructiveMigration(dropAllTables = true)
                    .build()
                    .also { instance = it }
            }
    }
}

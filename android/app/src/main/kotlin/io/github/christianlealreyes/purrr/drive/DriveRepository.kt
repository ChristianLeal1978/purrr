package io.github.christianlealreyes.purrr.drive

import io.github.christianlealreyes.purrr.data.dao.SourceDao
import io.github.christianlealreyes.purrr.data.dao.TrackDao
import io.github.christianlealreyes.purrr.data.entities.SourceEntity
import io.github.christianlealreyes.purrr.data.entities.TrackEntity
import java.time.Instant
import kotlinx.coroutines.flow.collect

/** Escanea una carpeta de Drive y guarda lo encontrado en Room — equivalente Android
 * de `sync/controller.py:_run_scan`, recortado a solo metadatos (nada de audio se
 * descarga acá, ver [io.github.christianlealreyes.purrr.cache.AudioCache]; tampoco
 * hay lectura de etiquetas ID3 por fragmentos ni carátula de carpeta en v1 — el
 * título mostrado cae al nombre de archivo, ver `TrackEntity.displayTitle`). */
class DriveRepository(
    private val sourceDao: SourceDao,
    private val trackDao: TrackDao,
) {
    suspend fun addSource(folderId: String, displayName: String) {
        sourceDao.upsert(SourceEntity(driveFolderId = folderId, displayName = displayName))
    }

    suspend fun scan(api: DriveApi, folderId: String, onProgress: (Int) -> Unit = {}) {
        var count = 0
        scanFolderTree(api, folderId).collect { scanned ->
            val existing = trackDao.getByDriveFileId(scanned.driveFileId)
            trackDao.upsert(
                TrackEntity(
                    driveFileId = scanned.driveFileId,
                    sourceFolderId = folderId,
                    driveParentId = scanned.driveParentId,
                    driveFolderPath = scanned.driveFolderPath,
                    fileName = scanned.fileName,
                    mimeType = scanned.mimeType,
                    driveMd5 = scanned.driveMd5,
                    driveModifiedTime = scanned.driveModifiedTime,
                    localPath = existing?.localPath,
                    cacheStatus = existing?.cacheStatus ?: "pending",
                    title = existing?.title,
                    artist = existing?.artist,
                    album = existing?.album,
                    trackNumber = existing?.trackNumber,
                    discNumber = existing?.discNumber,
                    durationSeconds = existing?.durationSeconds,
                    artPath = existing?.artPath,
                    updatedAt = Instant.now().toString(),
                )
            )
            count++
            onProgress(count)
        }
        sourceDao.touchScanned(folderId, Instant.now().toString())
    }
}

package io.github.christianlealreyes.purrr.cache

import android.content.Context
import io.github.christianlealreyes.purrr.drive.DriveApi
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val AUDIO_DIR_NAME = "audio"

/** Caché local de audio — equivalente Android de `cache/manager.py` del escritorio
 * (mismo esquema de nombre: `"<drive_file_id><ext>"`, un archivo por track). Usa
 * `filesDir`, no `cacheDir`: una canción que el usuario ya bajó para escucharla
 * offline no debería poder desaparecer sola si el sistema necesita espacio, a
 * diferencia de contenido realmente descartable. */
class AudioCache(context: Context) {
    private val dir = File(context.filesDir, AUDIO_DIR_NAME).apply { mkdirs() }

    fun pathFor(driveFileId: String, fileName: String): File {
        val ext = fileName.substringAfterLast('.', "").ifEmpty { "bin" }
        return File(dir, "$driveFileId.$ext")
    }

    /** Descarga bajo demanda (al reproducir), mismo patrón que
     * `sync/controller.py:download_track` — si ya está cacheado no vuelve a pedirlo. */
    suspend fun ensureDownloaded(api: DriveApi, driveFileId: String, fileName: String): File {
        val dest = pathFor(driveFileId, fileName)
        if (dest.exists()) return dest
        val bytes = api.downloadFile(driveFileId)
        withContext(Dispatchers.IO) { dest.writeBytes(bytes) }
        return dest
    }
}

package io.github.christianlealreyes.purrr.drive

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow

private const val FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

data class ScannedTrack(
    val driveFileId: String,
    val driveParentId: String?,
    val driveFolderPath: String,
    val fileName: String,
    val mimeType: String,
    val driveMd5: String?,
    val driveModifiedTime: String?,
)

/** Recorrido recursivo (BFS) de una carpeta de Drive — mismo diseño que
 * `drive/scanner.py:scan_folder_tree` del escritorio (misma cola BFS, mismo set de
 * visitados para no repetir carpetas), recortado a solo `.mp3`/`.flac` — sin
 * carátulas de carpeta, fuera de alcance en v1 de Android (ver el plan Fase 6.2).
 * Un `Flow` en vez de devolver una lista completa: emite cada track a medida que lo
 * encuentra, para que quien llama pueda ir guardando en Room y mostrando progreso
 * sin esperar a que termine todo el escaneo — mismo espíritu que el generador
 * Python, pensado para bibliotecas grandes. */
fun scanFolderTree(api: DriveApi, rootFolderId: String): Flow<ScannedTrack> = flow {
    val queue = ArrayDeque<Pair<String, String>>()
    queue.add(rootFolderId to "")
    val visited = mutableSetOf(rootFolderId)

    while (queue.isNotEmpty()) {
        val (folderId, folderPath) = queue.removeFirst()
        for (item in api.listChildren(folderId)) {
            if (item.mimeType == FOLDER_MIME_TYPE) {
                if (!visited.add(item.id)) continue
                queue.add(item.id to "$folderPath/${item.name}")
                continue
            }
            val extension = item.name.substringAfterLast('.', "").lowercase()
            if (extension != "mp3" && extension != "flac") continue
            emit(
                ScannedTrack(
                    driveFileId = item.id,
                    driveParentId = item.parents?.firstOrNull(),
                    driveFolderPath = folderPath.ifEmpty { "/" },
                    fileName = item.name,
                    mimeType = item.mimeType,
                    driveMd5 = item.md5Checksum,
                    driveModifiedTime = item.modifiedTime,
                )
            )
        }
    }
}

package io.github.christianlealreyes.purrr.drive

import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request

private const val FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
private const val LIST_FIELDS = "nextPageToken, files(id, name, mimeType, parents, md5Checksum, modifiedTime, size)"
private const val PAGE_SIZE = 1000

@Serializable
data class DriveFile(
    val id: String,
    val name: String,
    val mimeType: String,
    val parents: List<String>? = null,
    val md5Checksum: String? = null,
    val modifiedTime: String? = null,
    val size: String? = null,
)

@Serializable
private data class DriveFileListResponse(
    val files: List<DriveFile> = emptyList(),
    val nextPageToken: String? = null,
)

class DriveApiException(message: String, val statusCode: Int? = null) : IOException(message)

/** Cliente REST delgado sobre Drive v3 — equivalente Android de `drive/client.py` del
 * escritorio, pero a mano con OkHttp (sin el SDK Java de Google, que trae mucho más
 * de lo que hace falta acá: solo `files.list` y bajar bytes, ver el plan Fase 6.3).
 *
 * `accessTokenProvider` se invoca en cada request en vez de cachear el token acá —
 * es `DriveAuth.refreshAccessToken`, que ya cachea/renueva en el lado de Play
 * Services (silencioso salvo revocación real), así que no hace falta reimplementar
 * ese cacheo ni un manejo de reintento por 401 acá. */
class DriveApi(private val accessTokenProvider: suspend () -> String) {
    private val client = OkHttpClient()
    private val json = Json { ignoreUnknownKeys = true }

    /** Mismo filtro que `_ENTRY_QUERY` del escritorio, recortado a solo audio — las
     * carátulas de carpeta quedan fuera de alcance en v1 de Android (ver el plan). */
    suspend fun listChildren(folderId: String): List<DriveFile> {
        val query = "'$folderId' in parents and trashed = false and " +
            "(mimeType = '$FOLDER_MIME_TYPE' or fileExtension = 'mp3' or fileExtension = 'flac')"
        val result = mutableListOf<DriveFile>()
        var pageToken: String? = null
        do {
            val page = listFilesPage(query, pageToken)
            result += page.files
            pageToken = page.nextPageToken
        } while (pageToken != null)
        return result
    }

    private suspend fun listFilesPage(query: String, pageToken: String?): DriveFileListResponse =
        withContext(Dispatchers.IO) {
            val urlBuilder = "https://www.googleapis.com/drive/v3/files".toHttpUrl().newBuilder()
                .addQueryParameter("q", query)
                .addQueryParameter("fields", LIST_FIELDS)
                .addQueryParameter("pageSize", PAGE_SIZE.toString())
                .addQueryParameter("spaces", "drive")
            if (pageToken != null) urlBuilder.addQueryParameter("pageToken", pageToken)
            val request = Request.Builder()
                .url(urlBuilder.build())
                .header("Authorization", "Bearer ${accessTokenProvider()}")
                .build()
            json.decodeFromString(execute(request))
        }

    suspend fun downloadFile(fileId: String): ByteArray = withContext(Dispatchers.IO) {
        val url = "https://www.googleapis.com/drive/v3/files/$fileId".toHttpUrl().newBuilder()
            .addQueryParameter("alt", "media")
            .build()
        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${accessTokenProvider()}")
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw DriveApiException("Drive devolvió ${response.code} al bajar $fileId", response.code)
            }
            response.body?.bytes() ?: throw DriveApiException("Drive no devolvió contenido para $fileId")
        }
    }

    private fun execute(request: Request): String =
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw DriveApiException("Drive devolvió ${response.code}", response.code)
            response.body?.string() ?: throw DriveApiException("Drive no devolvió cuerpo en la respuesta")
        }
}

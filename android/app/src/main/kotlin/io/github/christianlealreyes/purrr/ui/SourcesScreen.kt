package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ListItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.auth.DriveAuth
import io.github.christianlealreyes.purrr.auth.GoogleAuthConfig
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.drive.DriveApi
import io.github.christianlealreyes.purrr.drive.DriveRepository
import kotlinx.coroutines.launch

/** Pantalla "Fuentes" (Fase 6.3 del plan): configurar el Web client ID de Google,
 * conectar la cuenta y agregar carpetas de Drive a escanear. */
@Composable
fun SourcesScreen(
    db: AppDatabase,
    driveAuth: DriveAuth,
    driveApi: DriveApi,
    driveRepository: DriveRepository,
) {
    val context = LocalContext.current
    val googleAuthConfig = remember { GoogleAuthConfig(context) }
    var webClientId by remember { mutableStateOf(googleAuthConfig.load() ?: "") }
    var connectedEmail by remember { mutableStateOf<String?>(null) }
    var folderInput by remember { mutableStateOf("") }
    var folderNameInput by remember { mutableStateOf("") }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    val sources by db.sourceDao().observeAll().collectAsState(initial = emptyList())
    val scope = rememberCoroutineScope()

    Column(modifier = Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Google")
        OutlinedTextField(
            value = webClientId,
            onValueChange = { webClientId = it },
            label = { Text("Web client ID (Google Cloud)") },
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { googleAuthConfig.save(webClientId.trim()) }) { Text("Guardar") }
            Button(onClick = {
                scope.launch {
                    runCatching { driveAuth.connect() }
                        .onSuccess { result ->
                            if (result == null) {
                                statusMessage = "Falta guardar el Web client ID."
                            } else {
                                connectedEmail = result.email
                                statusMessage = "Conectado."
                            }
                        }
                        .onFailure { statusMessage = "Error: ${it.message}" }
                }
            }) { Text("Conectar con Google") }
        }
        Text(connectedEmail?.let { "Conectado como $it" } ?: "Sin conectar")

        Text("Agregar carpeta de Drive")
        OutlinedTextField(
            value = folderInput,
            onValueChange = { folderInput = it },
            label = { Text("ID o link de la carpeta") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = folderNameInput,
            onValueChange = { folderNameInput = it },
            label = { Text("Nombre para mostrar") },
            modifier = Modifier.fillMaxWidth(),
        )
        Button(onClick = {
            val folderId = parseFolderIdOrLink(folderInput.trim())
            val displayName = folderNameInput.trim().ifEmpty { folderId }
            scope.launch {
                driveRepository.addSource(folderId, displayName)
                folderInput = ""
                folderNameInput = ""
            }
        }) { Text("Agregar fuente") }

        statusMessage?.let { Text(it) }

        Text("Fuentes")
        LazyColumn {
            items(sources, key = { it.driveFolderId }) { source ->
                ListItem(
                    headlineContent = { Text(source.displayName) },
                    supportingContent = { Text(source.lastScannedAt?.let { "Último escaneo: $it" } ?: "Sin escanear todavía") },
                    trailingContent = {
                        Button(onClick = {
                            scope.launch {
                                statusMessage = "Escaneando ${source.displayName}…"
                                runCatching {
                                    driveRepository.scan(driveApi, source.driveFolderId) { count ->
                                        statusMessage = "Escaneando ${source.displayName}… ($count encontrados)"
                                    }
                                }
                                    .onSuccess { statusMessage = "Escaneo de ${source.displayName} terminado." }
                                    .onFailure { statusMessage = "Error al escanear: ${it.message}" }
                            }
                        }) { Text("Escanear") }
                    },
                )
            }
        }
    }
}

private val folderIdPatterns = listOf(
    Regex("/folders/([a-zA-Z0-9_-]+)"),
    Regex("[?&]id=([a-zA-Z0-9_-]+)"),
)

/** Mismo parseo que `drive/client.py:parse_folder_id_or_link` del escritorio —
 * acepta un folder ID crudo o un link de Google Drive. */
private fun parseFolderIdOrLink(text: String): String {
    for (pattern in folderIdPatterns) {
        pattern.find(text)?.groupValues?.get(1)?.let { return it }
    }
    return text
}

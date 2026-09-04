package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.mood.buildMoodQueue
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import kotlinx.coroutines.launch

/** Pantalla "Ánimo" (Fase 7.3 del plan): elegir canciones semilla ya escaneadas y
 * armar una cola por cercanía de ánimo — mismo esquema que `ui/mood_view.py` del
 * escritorio, salvo que acá los vectores solo llegan por sync (Android no analiza
 * audio, ver el plan). Una semilla sin vector sincronizado todavía se muestra
 * atenuada. */
@Composable
fun MoodScreen(db: AppDatabase, coordinator: PlaybackCoordinator) {
    val tracks by db.trackDao().observeAll().collectAsState(initial = emptyList())
    val moods by db.trackMoodDao().observeAll().collectAsState(initial = emptyList())
    var query by remember { mutableStateOf("") }
    var seedRefs by remember { mutableStateOf(listOf<String>()) }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    val moodRefSet = remember(moods) { moods.map { it.trackRef }.toSet() }
    val filtered = if (query.isBlank()) {
        emptyList()
    } else {
        tracks.filter { it.displayTitle.contains(query, ignoreCase = true) || it.artist?.contains(query, ignoreCase = true) == true }
    }
    val seedTracks = seedRefs.mapNotNull { ref -> tracks.firstOrNull { it.trackRef == ref } }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("Buscar canción semilla") },
            modifier = Modifier.fillMaxWidth(),
        )
        LazyColumn(modifier = Modifier.weight(1f, fill = false)) {
            items(filtered, key = { it.driveFileId }) { track ->
                val hasMood = track.trackRef in moodRefSet
                ListItem(
                    headlineContent = { Text(track.displayTitle) },
                    supportingContent = {
                        Text(if (hasMood) "Tocar para agregar como semilla" else "Todavía sin ánimo calculado — reproducila una vez en el escritorio")
                    },
                    modifier = Modifier.clickable(enabled = hasMood) {
                        if (track.trackRef !in seedRefs) seedRefs = seedRefs + track.trackRef
                        query = ""
                    },
                )
            }
        }

        Text("Semillas elegidas")
        LazyColumn {
            items(seedTracks, key = { it.driveFileId }) { track ->
                ListItem(
                    headlineContent = { Text(track.displayTitle) },
                    modifier = Modifier.clickable { seedRefs = seedRefs - track.trackRef },
                )
            }
        }

        statusMessage?.let { Text(it) }

        Button(
            enabled = seedRefs.isNotEmpty(),
            onClick = {
                scope.launch {
                    val queue = buildMoodQueue(seedRefs, moods, tracks)
                    if (queue.isEmpty()) {
                        statusMessage = "Ninguna semilla elegida tiene todavía un vector de ánimo sincronizado."
                        return@launch
                    }
                    coordinator.playQueue(queue, 0)
                    statusMessage = null
                }
            },
        ) { Text("Reproducir por este ánimo") }
    }
}

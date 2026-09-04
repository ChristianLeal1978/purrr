package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.foundation.clickable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import io.github.christianlealreyes.purrr.player.Station
import io.github.christianlealreyes.purrr.player.sources.RadioTunes
import io.github.christianlealreyes.purrr.player.sources.RadioTunesConfig
import io.github.christianlealreyes.purrr.player.sources.Stations
import kotlinx.coroutines.launch

/** Pantalla "Radios" (Fase 7.1 del plan): Rainwave/Radio Bío-Bío/SmoothJazz.com
 * están siempre listos (catálogo estático); RadioTunes necesita una Listen Key y
 * pega a la red para traer sus ~99 canales — mismo esquema que
 * `ui/stations_view.py` del escritorio. */
@Composable
fun StationsScreen(coordinator: PlaybackCoordinator) {
    val context = LocalContext.current
    val radioTunesConfig = remember { RadioTunesConfig(context) }
    var listenKeyInput by remember { mutableStateOf("") }
    var radioTunesStations by remember { mutableStateOf<List<Station>?>(null) }
    var radioTunesError by remember { mutableStateOf<String?>(null) }
    var radioTunesQuery by remember { mutableStateOf("") }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var radioTunesConfigured by remember { mutableStateOf(radioTunesConfig.isConfigured()) }
    val scope = rememberCoroutineScope()
    val staticStations = remember { Stations.listStaticStations() }

    suspend fun loadRadioTunes() {
        radioTunesError = null
        radioTunesStations = null
        runCatching { RadioTunes.listStations(radioTunesConfig.loadListenKey()) }
            .onSuccess { radioTunesStations = it }
            .onFailure { radioTunesError = it.message }
    }

    LaunchedEffect(Unit) {
        if (radioTunesConfigured) loadRadioTunes()
    }

    fun play(station: Station) {
        scope.launch {
            statusMessage = "Conectando con ${station.displayName}…"
            runCatching { coordinator.playStation(station) }
                .onSuccess { statusMessage = null }
                .onFailure { statusMessage = "Error: ${it.message}" }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        statusMessage?.let { Text(it) }
        LazyColumn(modifier = Modifier.weight(1f, fill = false)) {
            groupedByProvider(staticStations).forEach { (header, group) ->
                item { Text(header, modifier = Modifier.padding(top = 8.dp)) }
                items(group, key = { it.provider + ":" + it.slug }) { station ->
                    ListItem(
                        headlineContent = { Text(station.displayName) },
                        supportingContent = station.subtitle?.let { { Text(it) } },
                        modifier = Modifier.clickable { play(station) },
                    )
                }
            }

            item { Text("RadioTunes", modifier = Modifier.padding(top = 8.dp)) }
            if (!radioTunesConfigured) {
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = listenKeyInput,
                            onValueChange = { listenKeyInput = it },
                            label = { Text("Listen Key") },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Button(onClick = {
                            radioTunesConfig.saveListenKey(listenKeyInput.trim())
                            radioTunesConfigured = true
                            scope.launch { loadRadioTunes() }
                        }) { Text("Guardar") }
                    }
                }
            } else {
                val stationsSnapshot = radioTunesStations
                when {
                    radioTunesError != null -> item { Text("Error: $radioTunesError") }
                    stationsSnapshot == null -> item { CircularProgressIndicator() }
                    else -> {
                        item {
                            OutlinedTextField(
                                value = radioTunesQuery,
                                onValueChange = { radioTunesQuery = it },
                                label = { Text("Buscar canal") },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        val filtered = if (radioTunesQuery.isBlank()) {
                            stationsSnapshot
                        } else {
                            stationsSnapshot.filter { it.displayName.contains(radioTunesQuery, ignoreCase = true) }
                        }
                        items(filtered, key = { "radiotunes:" + it.slug }) { station ->
                            ListItem(
                                headlineContent = { Text(station.displayName) },
                                modifier = Modifier.clickable { play(station) },
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun groupedByProvider(stations: List<Station>): List<Pair<String, List<Station>>> {
    val labels = mapOf("rainwave" to "Rainwave", "biobio" to "Radio Bío-Bío", "smoothjazz" to "SmoothJazz.com")
    return stations.groupBy { it.provider }.map { (provider, group) -> (labels[provider] ?: provider) to group }
}

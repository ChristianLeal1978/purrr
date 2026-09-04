package io.github.christianlealreyes.purrr.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.CloudSync
import androidx.compose.material.icons.filled.Headset
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.Mood
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material.icons.filled.Source
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import io.github.christianlealreyes.purrr.auth.DriveAuth
import io.github.christianlealreyes.purrr.auth.SpotifyAuth
import io.github.christianlealreyes.purrr.cache.AudioCache
import io.github.christianlealreyes.purrr.cloud.CloudSyncEngine
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.drive.DriveApi
import io.github.christianlealreyes.purrr.drive.DriveRepository
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import io.github.christianlealreyes.purrr.spotify.SpotifyApi
import io.github.christianlealreyes.purrr.spotify.SpotifyConnectController

private const val ROUTE_SETUP = "setup"
private const val ROUTE_SOURCES = "sources"
private const val ROUTE_LIBRARY = "library"
private const val ROUTE_PLAYLISTS = "playlists"
private const val ROUTE_STATIONS = "stations"
private const val ROUTE_SPOTIFY = "spotify"
private const val ROUTE_MOOD = "mood"

private data class TopLevelDestination(val route: String, val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

private val destinations = listOf(
    TopLevelDestination(ROUTE_SETUP, "Cuenta", Icons.Filled.CloudSync),
    TopLevelDestination(ROUTE_SOURCES, "Fuentes", Icons.Filled.Source),
    TopLevelDestination(ROUTE_LIBRARY, "Biblioteca", Icons.Filled.LibraryMusic),
    TopLevelDestination(ROUTE_PLAYLISTS, "Playlists", Icons.AutoMirrored.Filled.QueueMusic),
    TopLevelDestination(ROUTE_STATIONS, "Radios", Icons.Filled.Radio),
    TopLevelDestination(ROUTE_SPOTIFY, "Spotify", Icons.Filled.Headset),
    TopLevelDestination(ROUTE_MOOD, "Ánimo", Icons.Filled.Mood),
)

/** Raíz de la UI Compose — navegación entre las 7 pantallas (Fases 6.4 y 7 del
 * plan) más la barra de reproducción persistente abajo. */
@Composable
fun PurrrApp(
    db: AppDatabase,
    driveAuth: DriveAuth,
    driveApi: DriveApi,
    driveRepository: DriveRepository,
    audioCache: AudioCache,
    syncEngine: CloudSyncEngine,
    coordinator: PlaybackCoordinator,
    spotifyAuth: SpotifyAuth,
    spotifyApi: SpotifyApi,
    spotifyController: SpotifyConnectController,
) {
    val navController = rememberNavController()

    Scaffold(
        bottomBar = {
            Column {
                PlayerBar(coordinator = coordinator)
                val backStackEntry by navController.currentBackStackEntryAsState()
                val currentDestination = backStackEntry?.destination
                NavigationBar {
                    destinations.forEach { destination ->
                        NavigationBarItem(
                            selected = currentDestination?.hierarchy?.any { it.route == destination.route } == true,
                            onClick = {
                                navController.navigate(destination.route) {
                                    popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(destination.icon, contentDescription = destination.label) },
                            label = { Text(destination.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = ROUTE_SETUP,
            modifier = Modifier.padding(padding),
        ) {
            composable(ROUTE_SETUP) { SetupScreen(syncEngine = syncEngine) }
            composable(ROUTE_SOURCES) {
                SourcesScreen(
                    db = db,
                    driveAuth = driveAuth,
                    driveApi = driveApi,
                    driveRepository = driveRepository,
                )
            }
            composable(ROUTE_LIBRARY) {
                LibraryScreen(db = db, driveApi = driveApi, audioCache = audioCache, coordinator = coordinator)
            }
            composable(ROUTE_PLAYLISTS) { PlaylistsScreen(db = db, coordinator = coordinator) }
            composable(ROUTE_STATIONS) { StationsScreen(coordinator = coordinator) }
            composable(ROUTE_SPOTIFY) {
                SpotifyScreen(
                    db = db,
                    spotifyAuth = spotifyAuth,
                    spotifyApi = spotifyApi,
                    spotifyController = spotifyController,
                    coordinator = coordinator,
                )
            }
            composable(ROUTE_MOOD) { MoodScreen(db = db, coordinator = coordinator) }
        }
    }
}

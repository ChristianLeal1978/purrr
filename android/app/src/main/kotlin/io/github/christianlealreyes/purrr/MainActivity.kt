package io.github.christianlealreyes.purrr

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.lifecycle.lifecycleScope
import io.github.christianlealreyes.purrr.auth.DriveAuth
import io.github.christianlealreyes.purrr.auth.SpotifyAuth
import io.github.christianlealreyes.purrr.cache.AudioCache
import io.github.christianlealreyes.purrr.data.AppDatabase
import io.github.christianlealreyes.purrr.drive.DriveApi
import io.github.christianlealreyes.purrr.drive.DriveRepository
import io.github.christianlealreyes.purrr.player.PlaybackCoordinator
import io.github.christianlealreyes.purrr.player.PurrrPlayer
import io.github.christianlealreyes.purrr.spotify.SpotifyApi
import io.github.christianlealreyes.purrr.spotify.SpotifyConnectController
import io.github.christianlealreyes.purrr.ui.PurrrApp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    // DriveAuth/SpotifyAuth registran callbacks de Activity — tienen que crearse
    // acá, antes de que la Activity llegue a STARTED, no dentro de un composable.
    private lateinit var driveAuth: DriveAuth
    private lateinit var spotifyAuth: SpotifyAuth
    private lateinit var player: PurrrPlayer

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        driveAuth = DriveAuth(this)
        spotifyAuth = SpotifyAuth(this)
        player = PurrrPlayer(this)

        val db = AppDatabase.get(this)
        val driveApi = DriveApi { driveAuth.refreshAccessToken() }
        val driveRepository = DriveRepository(db.sourceDao(), db.trackDao())
        val audioCache = AudioCache(this)
        val syncEngine = (application as PurrrApplication).syncEngine
        val spotifyApi = SpotifyApi { spotifyAuth.getAccessToken() }
        val spotifyController = SpotifyConnectController(spotifyAuth, spotifyApi)
        val coordinator = PlaybackCoordinator(player, spotifyController)

        handleIntent(intent)

        setContent {
            MaterialTheme {
                Surface {
                    PurrrApp(
                        db = db,
                        driveAuth = driveAuth,
                        driveApi = driveApi,
                        driveRepository = driveRepository,
                        audioCache = audioCache,
                        syncEngine = syncEngine,
                        coordinator = coordinator,
                        spotifyAuth = spotifyAuth,
                        spotifyApi = spotifyApi,
                        spotifyController = spotifyController,
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    /** El redirect de Spotify vuelve acá (intent-filter en AndroidManifest.xml, ver
     * el plan Fase 7.2) — `SpotifyAuth.handleRedirect` resuelve la corrutina que
     * `SpotifyAuth.connect()` dejó esperando. */
    private fun handleIntent(intent: Intent?) {
        val uri = intent?.data ?: return
        lifecycleScope.launch { spotifyAuth.handleRedirect(uri) }
    }

    override fun onDestroy() {
        player.disconnect()
        super.onDestroy()
    }
}

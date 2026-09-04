package io.github.christianlealreyes.purrr.player

import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

/** Servicio de reproducción — equivalente Android del servicio MPRIS de escritorio
 * (`mpris/service.py`): expone la sesión de reproducción al sistema (notificación,
 * controles de auriculares/Bluetooth, Android Auto) sin que la UI tenga que
 * manejar nada de eso directo. Ya registrado en AndroidManifest.xml. */
class PlaybackService : MediaSessionService() {
    private lateinit var player: ExoPlayer
    private lateinit var session: MediaSession

    override fun onCreate() {
        super.onCreate()
        player = ExoPlayer.Builder(this).build()
        session = MediaSession.Builder(this, player).build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession = session

    override fun onDestroy() {
        session.run {
            player.release()
            release()
        }
        super.onDestroy()
    }
}

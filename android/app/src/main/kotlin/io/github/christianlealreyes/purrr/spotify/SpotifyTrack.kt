package io.github.christianlealreyes.purrr.spotify

/** Espejo del dataclass `SpotifyTrack` del escritorio (`spotify/track.py`). */
data class SpotifyTrack(
    val id: String,
    val title: String,
    val artist: String?,
    val album: String?,
    val durationSeconds: Double?,
    val artUrl: String?,
    val uri: String, // 'spotify:track:<id>' — lo que se manda a la Connect API
)

data class SpotifyDevice(
    val id: String,
    val name: String,
    val isActive: Boolean,
)

data class SpotifyPlaybackState(
    val isPlaying: Boolean,
    val positionSeconds: Double,
    val durationSeconds: Double,
    val trackUri: String?,
)

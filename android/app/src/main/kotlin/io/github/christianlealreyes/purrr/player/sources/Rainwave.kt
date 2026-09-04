package io.github.christianlealreyes.purrr.player.sources

import io.github.christianlealreyes.purrr.player.Station

/** Catálogo de estaciones de Rainwave (rainwave.cc) — radio de música de
 * videojuegos. El relay público de audio no pide autenticación para reproducir
 * (verificado desde el escritorio con `curl` contra las 6 estaciones: `200`,
 * `Content-Type: audio/mpeg`, cabeceras `icy-*`). Espejo de
 * `player/sources/rainwave.py`. */
object Rainwave {
    private const val STREAM_URL = "https://relay.rainwave.cc/%s.mp3"

    private val stations = listOf(
        Triple("game", "Rainwave — Game", "Música de videojuegos"),
        Triple("ocremix", "Rainwave — OC ReMix", "Remixes de OverClocked ReMix"),
        Triple("covers", "Rainwave — Covers", "Covers de música de videojuegos"),
        Triple("chiptune", "Rainwave — Chiptune", "Chiptune / 8-bit"),
        Triple("all", "Rainwave — All", "Mezcla de las demás señales"),
        Triple("chill", "Rainwave — Chill", "Videojuegos, ritmo relajado"),
    )

    fun listStations(): List<Station> = stations.map { (slug, name, subtitle) ->
        Station(provider = "rainwave", slug = slug, displayName = name, streamUrl = STREAM_URL.format(slug), subtitle = subtitle)
    }
}

package io.github.christianlealreyes.purrr.player.sources

import io.github.christianlealreyes.purrr.player.Station

/** SmoothJazz.com y su señal hermana SmoothLounge.com — a diferencia de
 * RadioTunes, no es AudioAddict: sin cuenta ni Listen Key. Espejo de
 * `player/sources/smoothjazz.py`. */
object Smoothjazz {
    private const val STREAM_URL = "http://smoothjazz.cdnstream1.com/%s_320.mp3"

    private val stations = listOf(
        Triple("2585", "SmoothJazz.com", "Smooth Jazz"),
        Triple("2586", "SmoothLounge.com", "Chillout / Lounge"),
    )

    fun listStations(): List<Station> = stations.map { (stationId, name, subtitle) ->
        Station(provider = "smoothjazz", slug = stationId, displayName = name, streamUrl = STREAM_URL.format(stationId), subtitle = subtitle)
    }
}

package io.github.christianlealreyes.purrr.player.sources

import io.github.christianlealreyes.purrr.player.Station

/** Catálogo de las 8 señales de Radio Bío-Bío (biobiochile.cl). No hay API
 * pública — la URL de stream de cada señal se obtuvo inspeccionando en vivo el
 * reproductor de `vivo.biobiochile.cl` (no adivinada), un redirect 302 público a
 * un servidor Nimble que sirve AAC real. Espejo de `player/sources/biobio.py`. */
object Biobio {
    private const val STREAM_URL = "https://redirector.dps.live/biobio%s/aac/icecast.audio"

    private val stations = listOf(
        Triple("santiago", "Radio Bío-Bío Santiago", "99.7 FM"),
        Triple("valparaiso", "Radio Bío-Bío Valparaíso", "94.5 FM"),
        Triple("concepcion", "Radio Bío-Bío Concepción", "98.1 FM"),
        Triple("losangeles", "Radio Bío-Bío Los Ángeles", "96.7 FM"),
        Triple("temuco", "Radio Bío-Bío Temuco", "88.1 FM"),
        Triple("osorno", "Radio Bío-Bío Osorno", "106.5 FM"),
        Triple("valdivia", "Radio Bío-Bío Valdivia", "88.9 FM"),
        Triple("puertomontt", "Radio Bío-Bío Puerto Montt", "94.9 FM"),
    )

    fun listStations(): List<Station> = stations.map { (slug, name, subtitle) ->
        Station(provider = "biobio", slug = slug, displayName = name, streamUrl = STREAM_URL.format(slug), subtitle = subtitle)
    }
}

package io.github.christianlealreyes.purrr.player.sources

import io.github.christianlealreyes.purrr.player.Station

/** Catálogos estáticos (sin red) — RadioTunes es dinámico, se maneja aparte
 * (ver [RadioTunes]) porque necesita una Listen Key y pega a la red. */
object Stations {
    fun listStaticStations(): List<Station> = Rainwave.listStations() + Biobio.listStations() + Smoothjazz.listStations()
}

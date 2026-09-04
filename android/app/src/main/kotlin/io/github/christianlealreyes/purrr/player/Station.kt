package io.github.christianlealreyes.purrr.player

/** Una señal de radio en vivo — a diferencia de un track, no tiene archivo que
 * descargar, ni duración, ni orden dentro de una cola. Espejo de
 * `player/station.py` del escritorio. */
data class Station(
    val provider: String,
    val slug: String,
    val displayName: String,
    val streamUrl: String,
    val subtitle: String? = null,
)

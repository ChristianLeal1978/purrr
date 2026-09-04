"""Catálogo de estaciones de Rainwave (rainwave.cc) — radio de música de videojuegos.

El relay público de audio no pide autenticación para reproducir (verificado con
`curl` contra las 6 estaciones: devuelven `200`, `Content-Type: audio/mpeg`,
cabeceras `icy-*`). La API JSON de "now playing"/votos sí pedirá una key de usuario
(rainwave.cc/keys/), pero eso queda para más adelante — no hace falta para el audio.
"""

from purrr.player.station import Station

_STREAM_URL = "https://relay.rainwave.cc/{slug}.mp3"

# (slug, nombre, subtítulo) — slugs confirmados contra el relay real, no adivinados.
_STATIONS = [
    ("game", "Rainwave — Game", "Música de videojuegos"),
    ("ocremix", "Rainwave — OC ReMix", "Remixes de OverClocked ReMix"),
    ("covers", "Rainwave — Covers", "Covers de música de videojuegos"),
    ("chiptune", "Rainwave — Chiptune", "Chiptune / 8-bit"),
    ("all", "Rainwave — All", "Mezcla de las demás señales"),
    ("chill", "Rainwave — Chill", "Videojuegos, ritmo relajado"),
]


def list_stations() -> list[Station]:
    return [
        Station(
            provider="rainwave",
            slug=slug,
            display_name=name,
            stream_url=_STREAM_URL.format(slug=slug),
            subtitle=subtitle,
        )
        for slug, name, subtitle in _STATIONS
    ]

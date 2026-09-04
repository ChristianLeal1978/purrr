"""Catálogo de SmoothJazz.com y su señal hermana SmoothLounge.com.

A diferencia de RadioTunes, esto **no es AudioAddict** — es un servicio propio, sin
cuenta ni Listen Key. Confirmé las dos URLs leyendo el HTML real de
`smoothjazz.com/help` y probándolas con `curl`: streams públicos en
`smoothjazz.cdnstream1.com`, `Content-Type: audio/mpeg`, con `icy-name` correcto
para cada una (`SmoothJazz.com` / `SmoothLounge.com`).
"""

from purrr.player.station import Station

_STATIONS = [
    ("2585", "SmoothJazz.com", "Smooth Jazz"),
    ("2586", "SmoothLounge.com", "Chillout / Lounge"),
]

_STREAM_URL = "http://smoothjazz.cdnstream1.com/{station_id}_320.mp3"


def list_stations() -> list[Station]:
    return [
        Station(
            provider="smoothjazz",
            slug=station_id,
            display_name=name,
            stream_url=_STREAM_URL.format(station_id=station_id),
            subtitle=subtitle,
        )
        for station_id, name, subtitle in _STATIONS
    ]

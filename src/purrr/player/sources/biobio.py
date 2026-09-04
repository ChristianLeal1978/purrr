"""Catálogo de las 8 señales de Radio Bío-Bío (biobiochile.cl).

No hay API pública — la URL de stream de cada señal se obtuvo inspeccionando en vivo
el estado del reproductor jPlayer de `vivo.biobiochile.cl` (no adivinada). Es un
redirect 302 público (sin depender de Referer, confirmado con `curl`) a un servidor
Nimble que sirve AAC real (`Content-Type: audio/aacp`).
"""

from purrr.player.station import Station

_STREAM_URL = "https://redirector.dps.live/biobio{slug}/aac/icecast.audio"

# (slug, nombre, frecuencia) — slugs y frecuencias sacados del selector real del sitio.
_STATIONS = [
    ("santiago", "Radio Bío-Bío Santiago", "99.7 FM"),
    ("valparaiso", "Radio Bío-Bío Valparaíso", "94.5 FM"),
    ("concepcion", "Radio Bío-Bío Concepción", "98.1 FM"),
    ("losangeles", "Radio Bío-Bío Los Ángeles", "96.7 FM"),
    ("temuco", "Radio Bío-Bío Temuco", "88.1 FM"),
    ("osorno", "Radio Bío-Bío Osorno", "106.5 FM"),
    ("valdivia", "Radio Bío-Bío Valdivia", "88.9 FM"),
    ("puertomontt", "Radio Bío-Bío Puerto Montt", "94.9 FM"),
]


def list_stations() -> list[Station]:
    return [
        Station(
            provider="biobio",
            slug=slug,
            display_name=name,
            stream_url=_STREAM_URL.format(slug=slug),
            subtitle=subtitle,
        )
        for slug, name, subtitle in _STATIONS
    ]

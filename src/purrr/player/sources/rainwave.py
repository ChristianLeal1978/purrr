"""Catálogo de estaciones de Rainwave (rainwave.cc) — radio de música de videojuegos.

El relay público de audio no pide autenticación para reproducir (verificado con
`curl` contra las 6 estaciones: devuelven `200`, `Content-Type: audio/mpeg`,
cabeceras `icy-*`, pero SIN `icy-metadata` de canción — por eso no hay "tags"
que leer del stream en sí, a diferencia de Bío-Bío/SmoothJazz/RadioTunes).

Lo que sí hay, y tampoco pide key (verificado con `curl` contra
`rainwave.cc/api4/info?sid=1`: responde sin autenticación — la key de usuario
de rainwave.cc/keys/ solo hace falta para votar/pedir canciones, no para leer),
es la canción actual de las 6 señales en un solo pedido, vía `all_stations_info`
— eso es lo que expone `get_now_playing()`, usado por `ui/playback_bar.py` para
mostrar título/artista/carátula reales mientras suena una señal de Rainwave."""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from purrr.player.station import Station

_STREAM_URL = "https://relay.rainwave.cc/{slug}.mp3"
_INFO_URL = "https://rainwave.cc/api4/info"
_ART_BASE_URL = "https://rainwave.cc"
_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"

# (slug, sid, nombre, subtítulo) — slugs confirmados contra el relay real; sid
# (station id numérico de la API) confirmado contra `all_stations_info`
# comparando álbum/artista actual de cada uno con lo que suena en cada relay.
_STATIONS = [
    ("game", 1, "Rainwave — Game", "Música de videojuegos"),
    ("ocremix", 2, "Rainwave — OC ReMix", "Remixes de OverClocked ReMix"),
    ("covers", 3, "Rainwave — Covers", "Covers de música de videojuegos"),
    ("chiptune", 4, "Rainwave — Chiptune", "Chiptune / 8-bit"),
    ("all", 5, "Rainwave — All", "Mezcla de las demás señales"),
    ("chill", 6, "Rainwave — Chill", "Videojuegos, ritmo relajado"),
]

_SID_BY_SLUG = {slug: sid for slug, sid, _name, _subtitle in _STATIONS}


@dataclass
class NowPlaying:
    title: str
    artist: str
    album: str
    art_url: str | None


def list_stations() -> list[Station]:
    return [
        Station(
            provider="rainwave",
            slug=slug,
            display_name=name,
            stream_url=_STREAM_URL.format(slug=slug),
            subtitle=subtitle,
        )
        for slug, _sid, name, subtitle in _STATIONS
    ]


def get_now_playing(slug: str) -> NowPlaying | None:
    """Canción actual de una señal de Rainwave — corre red (llamar desde un hilo
    aparte). Un solo pedido trae la info de las 6 señales a la vez
    (`all_stations_info`), así que el `sid` en la URL no importa demasiado; se
    manda igual para que el pedido sea válido."""
    sid = _SID_BY_SLUG.get(slug)
    if sid is None:
        return None
    query = urllib.parse.urlencode({"sid": sid})
    request = urllib.request.Request(f"{_INFO_URL}?{query}", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    info = data.get("all_stations_info", {}).get(str(sid))
    if not info:
        return None
    art_path = info.get("art")
    return NowPlaying(
        title=info.get("title") or "",
        artist=info.get("artists") or "",
        album=info.get("album") or "",
        art_url=f"{_ART_BASE_URL}{art_path}_320.jpg" if art_path else None,
    )

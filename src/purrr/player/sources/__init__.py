"""Registro de proveedores ESTÁTICOS de estaciones de radio en vivo (catálogo fijo,
sin credenciales). RadioTunes queda aparte (`player/sources/radiotunes.py`) — su
catálogo es dinámico y depende de una Listen Key configurada por el usuario, así
que `ui/window.py` lo pide por separado en vez de sumarlo acá."""

from purrr.player.sources import biobio, rainwave, smoothjazz
from purrr.player.station import Station


def list_all_stations() -> list[Station]:
    return rainwave.list_stations() + biobio.list_stations() + smoothjazz.list_stations()

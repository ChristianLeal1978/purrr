"""Catálogo dinámico de RadioTunes (red AudioAddict) — a diferencia de
Rainwave/Bío-Bío/SmoothJazz, necesita una Listen Key de tu cuenta Premium: sin
ella no hay audio (probé la URL real de un servidor sin key y devolvió
`401 Authentication Required`).

Sin OAuth: la Listen Key se copia a mano desde tu cuenta (radiotunes.com → Player
Settings → Hardware Player) — mismo patrón que el Client ID de Spotify, para que
Purrr nunca tenga que manejar tu contraseña real de la cuenta.

El catálogo de canales (id/nombre) sí es público, sin auth — confirmado con `curl`
contra `http://listen.radiotunes.com/streamlist` (99 canales al momento de escribir
esto). Cada canal individual sí necesita la key: se arma como una URL `.pls` con la
key en la query — `player/pls_resolver.py` la resuelve a la URL de stream real
recién al momento de reproducir (ver `ui/playback_bar.py:play_station`).
"""

import json
import os
import urllib.request

from purrr.config import RADIOTUNES_CONFIG_PATH
from purrr.player.station import Station

_STREAMLIST_URL = "http://listen.radiotunes.com/streamlist"
_STREAM_URL_TEMPLATE = "http://listen.radiotunes.com/premium_high/{key}.pls?{listen_key}"
_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"


def save_listen_key(listen_key: str) -> None:
    RADIOTUNES_CONFIG_PATH.write_text(json.dumps({"listen_key": listen_key}))
    os.chmod(RADIOTUNES_CONFIG_PATH, 0o600)
    # Mismo hook que auth/token_store.py y auth/spotify_oauth.py: si hay una bóveda
    # Supabase desbloqueada, empuja la key para que tus otros dispositivos la
    # reciban solo con iniciar sesión, sin volver a pegarla (Fase 1.5).
    from purrr.cloud import vault

    try:
        vault.push_credential("radiotunes", {"listen_key": listen_key})
    except Exception:
        pass


def load_listen_key() -> str | None:
    if not RADIOTUNES_CONFIG_PATH.exists():
        return None
    try:
        return json.loads(RADIOTUNES_CONFIG_PATH.read_text()).get("listen_key")
    except json.JSONDecodeError:
        return None


def is_configured() -> bool:
    return bool(load_listen_key())


def list_stations() -> list[Station]:
    """Pega a la red (el catálogo, público) — llamar siempre desde un hilo de
    fondo, nunca desde el hilo de la UI. Devuelve `[]` si todavía no hay Listen
    Key guardada — la UI lo interpreta como "falta configurar"."""
    listen_key = load_listen_key()
    if not listen_key:
        return []
    request = urllib.request.Request(_STREAMLIST_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        channels = json.load(response)
    return [
        Station(
            provider="radiotunes",
            slug=channel["key"],
            display_name=channel["name"],
            stream_url=_STREAM_URL_TEMPLATE.format(key=channel["key"], listen_key=listen_key),
            subtitle=None,
        )
        for channel in channels
    ]

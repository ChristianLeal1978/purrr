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

La carátula de cada canal NO viene en `streamlist` — sale de la API pública de
AudioAddict (la red dueña de RadioTunes/DI.FM/etc., `api.audioaddict.com`,
confirmada sin key con `curl`), que además de imagen trae nombre/descripción por
canal. `images.square` llega como URI-template RFC 6570
(`//cdn-images.audioaddict.com/.../hash.png{?size,height,width,quality,pad}`);
`?width=&height=` sí funciona para pedir un tamaño chico (probado con `curl -I`).
"""

import json
import os
import urllib.request

from purrr.config import RADIOTUNES_CONFIG_PATH
from purrr.player.station import Station

_STREAMLIST_URL = "http://listen.radiotunes.com/streamlist"
_STREAM_URL_TEMPLATE = "http://listen.radiotunes.com/premium_high/{key}.pls?{listen_key}"
_CHANNELS_API_URL = "https://api.audioaddict.com/v1/radiotunes/channels"
_ART_SIZE = 300
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


def _fetch_channel_art() -> dict[str, str]:
    """channel key -> URL de carátula ya resuelta (300x300). Corre red aparte del
    streamlist porque es una API distinta (AudioAddict, no RadioTunes) — si falla
    (sin conexión, cambio de esquema) no debe tumbar el catálogo entero: quien
    llame se queda sin carátulas, no sin canales."""
    request = urllib.request.Request(_CHANNELS_API_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        channels = json.load(response)
    art_by_key = {}
    for channel in channels:
        template = channel.get("images", {}).get("square")
        if not template:
            continue
        base_url = template.split("{?")[0]
        if base_url.startswith("//"):
            base_url = f"https:{base_url}"
        art_by_key[channel["key"]] = f"{base_url}?width={_ART_SIZE}&height={_ART_SIZE}"
    return art_by_key


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
    try:
        art_by_key = _fetch_channel_art()
    except Exception:  # noqa: BLE001 — sin carátulas, no sin canales
        art_by_key = {}
    return [
        Station(
            provider="radiotunes",
            slug=channel["key"],
            display_name=channel["name"],
            stream_url=_STREAM_URL_TEMPLATE.format(key=channel["key"], listen_key=listen_key),
            subtitle=None,
            art_url=art_by_key.get(channel["key"]),
        )
        for channel in channels
    ]

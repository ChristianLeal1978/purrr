"""Wrapper delgado sobre `spotipy` — mismo rol que `drive/client.py` para Drive.

La búsqueda de tracks (`/v1/search`) y el cacheo de tracks nuevos se sacaron: ese
endpoint de catálogo no funciona con una app personal en modo Development desde el
cambio de política de Spotify de noviembre 2024 (solo apps con Extended Quota Mode
tienen acceso, y Spotify no lo otorga para apps de uso individual). Lo que queda es
solo control de Spotify Connect — la reproducción de tracks ya cacheados en una
playlist sigue funcionando vía `purrr.db.database.get_spotify_track`."""

from purrr.auth.spotify_oauth import get_client


def list_devices() -> list[dict]:
    """Dispositivos Spotify Connect disponibles (para la sección de solo-lectura de
    `ui/spotify_view.py`) — pega a la red, llamar desde un hilo."""
    return get_client().devices().get("devices", [])

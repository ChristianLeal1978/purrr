"""Wrapper delgado sobre `spotipy` — mismo rol que `drive/client.py` para Drive.
Búsqueda de tracks y cacheo local de su metadata (Purrr nunca descarga el audio de
Spotify, solo lo necesario para mostrar la fila y controlar Spotify Connect)."""

from purrr.auth.spotify_oauth import get_client
from purrr.cache.manager import save_spotify_art_bytes
from purrr.db import database
from purrr.metadata.cover_search import download_cover
from purrr.spotify.track import SpotifyTrack


def _track_from_item(item: dict) -> SpotifyTrack:
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    album = item.get("album") or {}
    images = album.get("images") or []
    # El array de Spotify viene de mayor a menor resolución; la más chica alcanza de
    # sobra para una miniatura de lista.
    art_url = images[-1]["url"] if images else None
    return SpotifyTrack(
        id=item["id"],
        title=item["name"],
        artist=artists or None,
        album=album.get("name"),
        duration_seconds=(item.get("duration_ms") or 0) / 1000 or None,
        art_url=art_url,
        uri=item["uri"],
    )


def search_tracks(query: str, limit: int = 15) -> list[SpotifyTrack]:
    """Pega a la red — llamar desde un hilo secundario (mismo patrón que
    `metadata/cover_search.py:search_covers`)."""
    response = get_client().search(q=query, type="track", limit=limit)
    items = response.get("tracks", {}).get("items", [])
    return [_track_from_item(item) for item in items]


def list_devices() -> list[dict]:
    """Dispositivos Spotify Connect disponibles (para la sección de solo-lectura de
    `ui/spotify_view.py`) — pega a la red, llamar desde un hilo."""
    return get_client().devices().get("devices", [])


def cache_spotify_track(track: SpotifyTrack) -> None:
    """Guarda la metadata en `spotify_tracks` para que la playlist pueda mostrarla sin
    volver a pegarle a la API — y de paso baja/cachea la miniatura, igual que ya se
    hace con las carátulas de álbum (`metadata/cover_search.py` + `cache/manager.py`)."""
    art_path = None
    if track.art_url:
        existing = database.get_spotify_track(track.id)
        if existing is not None and existing["art_path"]:
            art_path = existing["art_path"]
        else:
            try:
                data = download_cover(track.art_url)
                art_path = str(save_spotify_art_bytes(data, track.id))
            except Exception:
                art_path = None  # sin miniatura no es motivo para no poder agregar el track
    database.cache_spotify_track(
        track.id, track.title, track.artist, track.album,
        track.duration_seconds, track.art_url, art_path, track.uri,
    )

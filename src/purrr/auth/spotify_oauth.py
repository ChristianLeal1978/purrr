"""Login con Spotify (Authorization Code + PKCE) — mismo rol que `auth/oauth.py` para
Drive, pero usando `spotipy` en vez de una implementación a mano: maneja el intercambio
PKCE, el refresh de tokens, y hasta levanta el servidor HTTP local para capturar el
redirect (confirmado leyendo su código fuente — ver el plan). No hace falta client
secret: PKCE está pensado justo para apps que no pueden guardar uno de forma segura,
como esta.
"""

import json
import os

from spotipy import Spotify
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyPKCE

from purrr.config import SPOTIFY_CLIENT_CONFIG_PATH, SPOTIFY_REDIRECT_URI, SPOTIFY_TOKEN_PATH

SCOPE = "user-read-playback-state user-modify-playback-state"


class MissingClientIdError(RuntimeError):
    """El usuario todavía no pegó el Client ID de su app de Spotify (developer.spotify.com)."""


class _PurrrCacheHandler(CacheHandler):
    """Persiste el token donde el resto de Purrr ya sabe buscarlo, y lo empuja a la
    bóveda centralizada (Fase 1.5) en el mismo punto de guardado que usa Drive."""

    def get_cached_token(self) -> dict | None:
        if not SPOTIFY_TOKEN_PATH.exists():
            return None
        try:
            return json.loads(SPOTIFY_TOKEN_PATH.read_text())
        except json.JSONDecodeError:
            return None

    def save_token_to_cache(self, token_info: dict) -> None:
        SPOTIFY_TOKEN_PATH.write_text(json.dumps(token_info))
        os.chmod(SPOTIFY_TOKEN_PATH, 0o600)
        from purrr.cloud import vault

        try:
            vault.push_credential("spotify", token_info)
        except Exception:
            pass


def _load_client_id() -> str:
    if not SPOTIFY_CLIENT_CONFIG_PATH.exists():
        raise MissingClientIdError(
            f"No se encontró {SPOTIFY_CLIENT_CONFIG_PATH}. Crea una app en "
            "developer.spotify.com/dashboard, agrega el Redirect URI "
            f"'{SPOTIFY_REDIRECT_URI}' y pega el Client ID en la pantalla 'Spotify' de Purrr."
        )
    data = json.loads(SPOTIFY_CLIENT_CONFIG_PATH.read_text())
    client_id = data.get("client_id")
    if not client_id:
        raise MissingClientIdError(f"{SPOTIFY_CLIENT_CONFIG_PATH} no tiene 'client_id'.")
    return client_id


def save_client_id(client_id: str) -> None:
    SPOTIFY_CLIENT_CONFIG_PATH.write_text(json.dumps({"client_id": client_id}))
    os.chmod(SPOTIFY_CLIENT_CONFIG_PATH, 0o600)


def is_client_configured() -> bool:
    return SPOTIFY_CLIENT_CONFIG_PATH.exists()


def _auth_manager() -> SpotifyPKCE:
    return SpotifyPKCE(
        client_id=_load_client_id(),
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPE,
        cache_handler=_PurrrCacheHandler(),
        open_browser=True,
    )


def get_client() -> Spotify:
    """No dispara el flujo interactivo por sí solo: `spotipy` primero intenta el token
    cacheado (o su refresh) y solo abre el navegador si hace falta un login nuevo —
    llamar a esto desde un hilo de fondo, igual que `auth/oauth.py:get_credentials`."""
    return Spotify(auth_manager=_auth_manager())


def run_oauth_flow() -> None:
    """Fuerza el login interactivo (usado por el botón "Conectar con Spotify")."""
    _auth_manager().get_access_token(check_cache=False)


def is_authenticated() -> bool:
    """Chequeo local, sin red (igual que `auth/oauth.py:is_authenticated`) — solo mira
    si hay un token guardado con refresh_token; el refresh real (si expiró) lo hace
    `spotipy` solo, de forma perezosa, la próxima vez que `get_client()` haga un pedido
    de verdad — no hace falta forzarlo acá."""
    if not is_client_configured() or not SPOTIFY_TOKEN_PATH.exists():
        return False
    try:
        token_info = json.loads(SPOTIFY_TOKEN_PATH.read_text())
    except json.JSONDecodeError:
        return False
    return bool(token_info.get("refresh_token"))


def revoke() -> None:
    SPOTIFY_TOKEN_PATH.unlink(missing_ok=True)

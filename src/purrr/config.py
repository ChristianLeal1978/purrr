import os
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

APP_ID = "io.github.christianlealreyes.Purrr"

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

CONFIG_DIR = Path(GLib.get_user_config_dir()) / "purrr"
CACHE_DIR = Path(GLib.get_user_cache_dir()) / "purrr"
AUDIO_CACHE_DIR = CACHE_DIR / "audio"
ART_CACHE_DIR = CACHE_DIR / "art"
ALBUM_ART_CACHE_DIR = CACHE_DIR / "album_art"
WAVEFORM_CACHE_DIR = CACHE_DIR / "waveform"
MOOD_MODELS_DIR = CACHE_DIR / "models"
DATA_DIR = Path(GLib.get_user_data_dir()) / "purrr"

DB_PATH = DATA_DIR / "purrr.db"
TOKEN_PATH = CONFIG_DIR / "token.json"

# Client ID "Desktop app" compartido de Purrr en Google Cloud (ver src/purrr/auth/
# oauth.py). Un client secret de tipo "Desktop app"/"installed" no puede protegerse de
# verdad en una app nativa (cualquiera puede extraerlo del binario) — Google mismo lo
# documenta así para este flujo, por eso viaja incrustado igual que el anon key de
# Supabase de más abajo. Ningún usuario tiene que crear su propio proyecto de Google
# Cloud: solo acepta el consentimiento de acceso de solo lectura a su propio Drive.
GOOGLE_OAUTH_CLIENT_CONFIG = {
    "installed": {
        "client_id": "890264943964-mbs0a76e8j2f0vtfg7fqrgfv6i51fgrk.apps.googleusercontent.com",
        "project_id": "purrr-506719",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "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",
        "redirect_uris": ["http://localhost"],
    }
}

# Fase 1 — backend Supabase compartido de Purrr (ver src/purrr/cloud/). El anon key
# está diseñado por Supabase para viajar al cliente — no es secreto, todo el acceso a
# datos queda restringido por Row Level Security (`cloud/schema.sql`) con `auth.uid()`,
# así que el anon key por sí solo no alcanza para leer ni escribir nada de otro
# usuario. Cada persona que usa Purrr inicia sesión con su propia cuenta (email +
# contraseña) sobre este mismo proyecto — no crea ni configura ningún backend propio.
SUPABASE_URL = "https://nlvajcskcnnwnhcslbcj.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5sdmFqY3Nr"
    "Y25ud25oY3NsYmNqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg0ODMyNTksImV4cCI6MjEwNDA1OTI1"
    "OX0.PaHa_yz91J_M8Xh0Mhsr0zg1czHdpunRAmwFgKmkK-w"
)
SUPABASE_SESSION_PATH = CONFIG_DIR / "supabase_session.json"

# Fase 4 — Spotify Connect (ver src/purrr/auth/spotify_oauth.py, src/purrr/spotify/).
SPOTIFY_CLIENT_CONFIG_PATH = CONFIG_DIR / "spotify_client.json"
SPOTIFY_TOKEN_PATH = CONFIG_DIR / "spotify_token.json"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"

# Fase 3 (radios) — RadioTunes (ver src/purrr/player/sources/radiotunes.py).
RADIOTUNES_CONFIG_PATH = CONFIG_DIR / "radiotunes_key.json"


def ensure_dirs() -> None:
    for path in (
        DATA_DIR, AUDIO_CACHE_DIR, ART_CACHE_DIR, ALBUM_ART_CACHE_DIR, WAVEFORM_CACHE_DIR,
        MOOD_MODELS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)

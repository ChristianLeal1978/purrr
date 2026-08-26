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
DATA_DIR = Path(GLib.get_user_data_dir()) / "purrr"

DB_PATH = DATA_DIR / "purrr.db"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
TOKEN_PATH = CONFIG_DIR / "token.json"


def ensure_dirs() -> None:
    for path in (DATA_DIR, AUDIO_CACHE_DIR, ART_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)

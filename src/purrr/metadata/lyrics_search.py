import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from purrr.config import LYRICS_CACHE_DIR

_API_BASE = "https://lrclib.net/api"
_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"
_LRC_LINE_RE = re.compile(r"\[(\d{2}):(\d{2}(?:\.\d+)?)](.*)")


@dataclass
class LyricsResult:
    synced: list[tuple[float, str]] | None  # None si no hay versión sincronizada
    plain: str | None  # texto plano, para cuando solo hay eso (o nada)


def _parse_lrc(text: str) -> list[tuple[float, str]]:
    lines = []
    for raw_line in text.splitlines():
        match = _LRC_LINE_RE.match(raw_line)
        if not match:
            continue  # metadata del LRC ([ar:...], [ti:...], etc.) o línea vacía
        minutes, seconds, lyric = match.groups()
        lyric = lyric.strip()
        if lyric:
            lines.append((int(minutes) * 60 + float(seconds), lyric))
    lines.sort(key=lambda pair: pair[0])
    return lines


def _request_json(path: str, params: dict) -> object:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{_API_BASE}/{path}?{query}", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def fetch_lyrics(title: str, artist: str, album: str, duration_seconds: float) -> LyricsResult | None:
    """Busca la letra (sincronizada si existe) en lrclib.net — base pública y libre de letras,
    sin API key. Corre red, así que hay que llamarla desde un hilo secundario (ver
    `sync/controller.py:ensure_lyrics`)."""
    if not title:
        return None

    params = {"track_name": title, "artist_name": artist or ""}
    if album:
        params["album_name"] = album
    if duration_seconds:
        params["duration"] = round(duration_seconds)

    try:
        data = _request_json("get", params)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        # Sin coincidencia exacta de título/artista/álbum/duración: probamos una búsqueda
        # más laxa y nos quedamos con el primer resultado, mejor que dejar el panel vacío.
        results = _request_json("search", {"track_name": title, "artist_name": artist or ""})
        data = results[0] if results else None

    if not data:
        return None

    synced_raw = data.get("syncedLyrics")
    plain = data.get("plainLyrics") or None
    synced = _parse_lrc(synced_raw) if synced_raw else None
    if not synced and not plain:
        return None
    return LyricsResult(synced=synced or None, plain=plain)


def _cache_path(key: str) -> Path:
    return LYRICS_CACHE_DIR / f"{key}.json"


def load_cached(key: str) -> LyricsResult | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    synced = [(pair[0], pair[1]) for pair in data["synced"]] if data.get("synced") else None
    return LyricsResult(synced=synced, plain=data.get("plain"))


def _save_cache(key: str, result: LyricsResult | None) -> None:
    LYRICS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"synced": result.synced if result else None, "plain": result.plain if result else None}
    _cache_path(key).write_text(json.dumps(payload))


def fetch_and_cache(
    key: str, title: str, artist: str, album: str, duration_seconds: float
) -> LyricsResult | None:
    """Envoltorio de `fetch_lyrics` que además cachea el resultado localmente (incluso
    "no había letra", para no repetir el pedido de red en cada reproducción)."""
    try:
        result = fetch_lyrics(title, artist, album, duration_seconds)
    except Exception:  # noqa: BLE001 — sin conexión o API caída: mejor sin letra que romper la UI
        return None
    _save_cache(key, result)
    return result

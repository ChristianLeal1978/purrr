import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

_SEARCH_URL = "https://itunes.apple.com/search"
_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"


@dataclass
class CoverCandidate:
    thumb_url: str
    full_url: str
    label: str


def search_covers(album: str, artist: str | None, limit: int = 4) -> list[CoverCandidate]:
    """Busca posibles carátulas para un álbum en la API pública de iTunes (sin API key).
    Corre red, así que hay que llamarla desde un hilo secundario."""
    term = f"{artist} {album}" if artist else album
    query = urllib.parse.urlencode({"term": term, "entity": "album", "limit": limit})
    request = urllib.request.Request(
        f"{_SEARCH_URL}?{query}", headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)

    candidates = []
    for item in data.get("results", []):
        art_url = item.get("artworkUrl100")
        if not art_url:
            continue
        full_url = art_url.replace("100x100bb", "1200x1200bb")
        thumb_url = art_url.replace("100x100bb", "300x300bb")
        label = f"{item.get('collectionName', album)} — {item.get('artistName', artist or '')}"
        candidates.append(CoverCandidate(thumb_url, full_url, label))
    return candidates


def download_cover(url: str, timeout: int = 15) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()

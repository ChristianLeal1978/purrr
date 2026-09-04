"""Descarga y cache local de los modelos de Essentia usados para el análisis de
ánimo (Fase 5) — ver `mood/analyzer.py`. Se bajan una sola vez, la primera vez que
hace falta, a `purrr.config.MOOD_MODELS_DIR` (~20.5 MB en total):

- El embedding Discogs-EffNet (~18.4 MB) — elegido en vez de AudioSet-VGGish
  (~289 MB) porque cubre los mismos 4 modelos de ánimo con una fracción del peso
  (confirmado descargando ambos y comparando tamaños reales).
- Los 4 cabezales de clasificación de ánimo (happy/sad/relaxed/aggressive,
  ~500 KB cada uno) que corren sobre ese embedding.

Licencias: el paquete `essentia-tensorflow` es AGPL-3.0 (Purrr se distribuye bajo
esa misma licencia, ver `/LICENSE`); los modelos son CC BY-NC-SA 4.0 (MTG-UPF) — no
comercial, cumplido porque Purrr es gratis.
"""

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path

from purrr.config import MOOD_MODELS_DIR

_BASE_URL = "https://essentia.upf.edu/models"
_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"

MOODS = ("happy", "sad", "relaxed", "aggressive")

EMBEDDING_FILENAME = "discogs-effnet-bs64-1.pb"
_EMBEDDING_URL = f"{_BASE_URL}/feature-extractors/discogs-effnet/{EMBEDDING_FILENAME}"


def _head_urls(mood: str) -> tuple[str, str]:
    base = f"{_BASE_URL}/classification-heads/mood_{mood}/mood_{mood}-discogs-effnet-1"
    return f"{base}.pb", f"{base}.json"


def embedding_path() -> Path:
    return MOOD_MODELS_DIR / EMBEDDING_FILENAME


def head_pb_path(mood: str) -> Path:
    return MOOD_MODELS_DIR / f"mood_{mood}-discogs-effnet-1.pb"


def head_json_path(mood: str) -> Path:
    return MOOD_MODELS_DIR / f"mood_{mood}-discogs-effnet-1.json"


def _all_paths() -> list[Path]:
    paths = [embedding_path()]
    for mood in MOODS:
        paths.append(head_pb_path(mood))
        paths.append(head_json_path(mood))
    return paths


def is_downloaded() -> bool:
    return all(p.exists() for p in _all_paths())


def load_head_metadata(mood: str) -> dict:
    """El `.json` de cada cabezal trae el nombre del nodo de salida de TensorFlow y
    el orden de sus clases — ninguno de los dos es fijo entre modelos (ver
    `mood/analyzer.py`), así que siempre hay que leerlos de acá, nunca hardcodear."""
    return json.loads(head_json_path(mood).read_text())


def download_models(on_progress: Callable[[int, int], None]) -> None:
    """Descarga los 9 archivos (~20.5 MB) a `MOOD_MODELS_DIR`. `on_progress(hecho, total)`
    se llama después de cada archivo — pensado para correr en un hilo de fondo
    (`mood/controller.py`), no llamar desde el hilo de la UI."""
    MOOD_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    downloads = [(_EMBEDDING_URL, embedding_path())]
    for mood in MOODS:
        pb_url, json_url = _head_urls(mood)
        downloads.append((pb_url, head_pb_path(mood)))
        downloads.append((json_url, head_json_path(mood)))

    total = len(downloads)
    for done, (url, dest) in enumerate(downloads, start=1):
        if not dest.exists():
            _download_file(url, dest)
        on_progress(done, total)


def _download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    tmp_path = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=60) as response, tmp_path.open("wb") as fh:
        fh.write(response.read())
    tmp_path.replace(dest)

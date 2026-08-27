import json
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from purrr.config import WAVEFORM_CACHE_DIR

_BAR_COUNT = 48
_LEVEL_INTERVAL_NS = 50_000_000  # 50ms — suficientes muestras para 48 barras hasta en temas cortos
_FLOOR_DB = -60.0


def waveform_cache_path(key: str) -> Path:
    return WAVEFORM_CACHE_DIR / f"{key}.json"


def load_cached(key: str) -> list[float] | None:
    path = waveform_cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _db_to_linear(db: float) -> float:
    if db <= _FLOOR_DB:
        return 0.0
    return max(0.0, min(1.0, 10 ** (db / 20)))


def _bucketize(values: list[float], n_bars: int) -> list[float]:
    if not values:
        return [0.0] * n_bars
    bucket_size = max(1, len(values) // n_bars)
    bars = [
        sum(chunk) / len(chunk)
        for i in range(n_bars)
        if (chunk := values[i * bucket_size : (i + 1) * bucket_size] or values[-1:])
    ]
    peak = max(bars) or 1.0
    # Normaliza contra el pico del propio tema y deja un piso mínimo visible — sin esto, temas
    # grabados con poco volumen dibujarían barras casi invisibles.
    return [round(min(1.0, v / peak * 0.92 + 0.08), 4) for v in bars]


def extract_waveform(path: Path, n_bars: int = _BAR_COUNT) -> list[float]:
    """Decodifica el audio entero para sacar el nivel de pico cada `_LEVEL_INTERVAL_NS` (vía el
    elemento `level` de GStreamer) y lo reduce a `n_bars` valores 0..1. Corre más rápido que en
    tiempo real (fakesink sync=false) — del orden de un cuarto de segundo por canción."""
    if not Gst.is_initialized():
        Gst.init(None)

    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    pipeline = Gst.parse_launch(
        f'filesrc location="{escaped}" ! decodebin ! audioconvert ! '
        f"level interval={_LEVEL_INTERVAL_NS} post-messages=true ! fakesink sync=false"
    )
    bus = pipeline.get_bus()
    peaks_db: list[float] = []
    pipeline.set_state(Gst.State.PLAYING)
    try:
        while True:
            msg = bus.timed_pop_filtered(
                5 * Gst.SECOND, Gst.MessageType.ELEMENT | Gst.MessageType.EOS | Gst.MessageType.ERROR
            )
            if msg is None or msg.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR):
                break
            structure = msg.get_structure()
            if structure and structure.get_name() == "level":
                peaks_db.append(max(structure.get_value("peak")))
    finally:
        pipeline.set_state(Gst.State.NULL)

    return _bucketize([_db_to_linear(db) for db in peaks_db], n_bars)


def extract_and_cache(path: Path, key: str, n_bars: int = _BAR_COUNT) -> list[float]:
    bars = extract_waveform(path, n_bars)
    WAVEFORM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    waveform_cache_path(key).write_text(json.dumps(bars))
    return bars

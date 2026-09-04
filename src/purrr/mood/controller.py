"""Orquesta la descarga de modelos y el análisis de ánimo en segundo plano — mismo
estilo que `sync/controller.py:SyncController`: trabajo pesado en hilos, cruce a la
UI vía `GLib.idle_add`.
"""

import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from purrr.db import database
from purrr.mood import models
from purrr.mood.analyzer import MoodVector, analyze_track


def _vector_from_row(row) -> MoodVector:
    return MoodVector(
        happy=row["happy"], sad=row["sad"], relaxed=row["relaxed"], aggressive=row["aggressive"]
    )


class MoodAnalysisController(GObject.Object):
    __gsignals__ = {
        "models-download-progress": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "models-ready": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "analysis-progress": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),  # analizados, total
        "analysis-finished": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # total analizado
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._library_thread: threading.Thread | None = None
        self._stop_requested = False

    def ensure_mood(
        self, track_id: int, local_path: str, on_complete: Callable[[MoodVector | None], None]
    ) -> None:
        """Mismo patrón que `SyncController.ensure_waveform`: si ya hay un vector
        guardado, devuelve al toque; si no, analiza en un hilo aparte (descarga los
        modelos primero si hace falta — así el enganche perezoso de `ui/window.py`
        funciona sin que el usuario haya visitado antes la pantalla 'Ánimo')."""
        cached = database.get_track_mood(track_id)
        if cached is not None:
            on_complete(_vector_from_row(cached))
            return
        threading.Thread(
            target=self._analyze_one_thread, args=(track_id, local_path, on_complete), daemon=True
        ).start()

    def _analyze_one_thread(
        self, track_id: int, local_path: str, on_complete: Callable[[MoodVector | None], None]
    ) -> None:
        try:
            self._ensure_models_downloaded()
            vector = analyze_track(Path(local_path))
            database.save_track_mood(track_id, vector.happy, vector.sad, vector.relaxed, vector.aggressive)
            GLib.idle_add(on_complete, vector)
        except Exception as exc:  # noqa: BLE001 — se reporta a la UI, no debe romper la reproducción
            GLib.idle_add(self.emit, "error", str(exc))
            GLib.idle_add(on_complete, None)

    def analyze_library(self) -> None:
        """Backfill proactivo: analiza todos los tracks cacheados sin vector de ánimo
        todavía. Opcional — no hace falta correrlo para poder usar el modo Ánimo con
        pocas semillas (`ensure_mood` ya las analiza al toque una por una)."""
        if self._library_thread is not None and self._library_thread.is_alive():
            return
        self._stop_requested = False
        self._library_thread = threading.Thread(target=self._analyze_library_thread, daemon=True)
        self._library_thread.start()

    def stop(self) -> None:
        self._stop_requested = True

    def _analyze_library_thread(self) -> None:
        try:
            self._ensure_models_downloaded()
        except Exception as exc:  # noqa: BLE001 — se reporta a la UI
            GLib.idle_add(self.emit, "error", str(exc))
            return

        tracks = database.list_tracks_needing_mood_analysis()
        total = len(tracks)
        analyzed = 0
        for track_row in tracks:
            if self._stop_requested:
                break
            try:
                vector = analyze_track(Path(track_row["local_path"]))
                database.save_track_mood(
                    track_row["id"], vector.happy, vector.sad, vector.relaxed, vector.aggressive
                )
            except Exception:  # noqa: BLE001 — un track que falla no debe cortar todo el backfill
                pass
            analyzed += 1
            GLib.idle_add(self.emit, "analysis-progress", analyzed, total)
        GLib.idle_add(self.emit, "analysis-finished", analyzed)

    def _ensure_models_downloaded(self) -> None:
        if models.is_downloaded():
            return

        def on_progress(done: int, total: int) -> None:
            GLib.idle_add(self.emit, "models-download-progress", done, total)

        models.download_models(on_progress)
        GLib.idle_add(self.emit, "models-ready")

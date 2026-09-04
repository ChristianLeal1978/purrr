"""Arma una cola de reproducción a partir de canciones semilla, usando la cercanía
en el espacio de ánimo de 4 dimensiones (happy/sad/relaxed/aggressive) — Fase 5.

Simplificación aceptada sobre el diseño original: en vez de una cola "infinita" que
va evitando repetir lo reciente, arma una lista ordenada y acotada de una sola vez
(como una playlist autogenerada) — cada candidato aparece una sola vez en la lista,
así que no hay repetición que evitar. "Cambiar de ánimo" (agregar otra semilla)
recalcula el centroide con todas las semillas acumuladas y reconstruye la cola
entera, no hace merge incremental con lo que ya sonó.

Devuelve `QueueItem` normales de Drive — nada de esto toca `PlayQueue` ni
`ui/playback_bar.py`, son datos que `ui/window.py` le pasa tal cual a
`queue.set_queue(...)`.
"""

from purrr.db import database
from purrr.mood.analyzer import MoodVector
from purrr.player.queue import QueueItem

DEFAULT_LIMIT = 50


def _mood_vector_from_row(row) -> MoodVector:
    return MoodVector(
        happy=row["happy"], sad=row["sad"], relaxed=row["relaxed"], aggressive=row["aggressive"]
    )


def _queue_item_from_track_row(row) -> QueueItem:
    return QueueItem(
        track_id=row["id"],
        drive_file_id=row["drive_file_id"],
        title=row["title"] or row["file_name"],
        artist=row["artist"] or "",
        album=row["album"] or "",
        local_path=row["local_path"],
        duration_seconds=row["duration_seconds"] or 0.0,
        art_path=row["art_path"],
    )


def build_mood_queue(seed_track_ids: list[int], limit: int = DEFAULT_LIMIT) -> list[QueueItem]:
    """Vacío si ninguna semilla tiene todavía un vector de ánimo calculado (la UI
    debería analizarlas antes de llamar a esto — ver `ui/mood_view.py`)."""
    seed_mood_rows = [database.get_track_mood(tid) for tid in seed_track_ids]
    seed_mood_rows = [row for row in seed_mood_rows if row is not None]
    if not seed_mood_rows:
        return []
    centroid = MoodVector.average([_mood_vector_from_row(row) for row in seed_mood_rows])

    seed_tracks = [database.get_track(tid) for tid in seed_track_ids]
    seed_items = [_queue_item_from_track_row(row) for row in seed_tracks if row is not None]

    seed_id_set = set(seed_track_ids)
    candidates = [row for row in database.list_track_moods() if row["id"] not in seed_id_set]
    candidates.sort(key=lambda row: centroid.distance_to(_mood_vector_from_row(row)))
    ranked_items = [_queue_item_from_track_row(row) for row in candidates[:limit]]

    return seed_items + ranked_items

import random
from dataclasses import dataclass


@dataclass
class QueueItem:
    track_id: int
    drive_file_id: str
    title: str
    artist: str
    local_path: str | None
    duration_seconds: float


class PlayQueue:
    def __init__(self):
        self._items: list[QueueItem] = []
        self._order: list[int] = []  # índices en self._items, reordenados si hay shuffle
        self._position = -1
        self.shuffle = False
        self.repeat = False  # repetir toda la cola al llegar al final

    def set_queue(self, items: list[QueueItem], start_index: int = 0) -> None:
        self._items = items
        self._order = list(range(len(items)))
        if self.shuffle:
            self._shuffle_order(keep_first=start_index)
            self._position = 0
        else:
            self._position = start_index

    def toggle_shuffle(self, enabled: bool) -> None:
        self.shuffle = enabled
        if not self._items:
            return
        current = self.current()
        if enabled:
            self._shuffle_order(keep_first=self._order[self._position] if self._position >= 0 else 0)
            self._position = 0
        else:
            self._order = list(range(len(self._items)))
            if current is not None:
                self._position = self._items.index(current)

    def _shuffle_order(self, keep_first: int) -> None:
        rest = [i for i in range(len(self._items)) if i != keep_first]
        random.shuffle(rest)
        self._order = [keep_first, *rest]

    def current(self) -> QueueItem | None:
        if 0 <= self._position < len(self._order):
            return self._items[self._order[self._position]]
        return None

    def peek_next(self) -> QueueItem | None:
        """Mira la siguiente canción sin avanzar la posición (para precargar su descarga)."""
        if self._position + 1 < len(self._order):
            return self._items[self._order[self._position + 1]]
        if self.repeat and self._order:
            return self._items[self._order[0]]
        return None

    def has_next(self) -> bool:
        return self._position + 1 < len(self._order) or self.repeat

    def has_previous(self) -> bool:
        return self._position > 0

    def next(self) -> QueueItem | None:
        if self._position + 1 < len(self._order):
            self._position += 1
        elif self.repeat and self._order:
            self._position = 0
        else:
            return None
        return self.current()

    def previous(self) -> QueueItem | None:
        if self._position > 0:
            self._position -= 1
            return self.current()
        return None

    def is_empty(self) -> bool:
        return not self._items

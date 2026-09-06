import bisect

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from purrr.metadata.lyrics_search import LyricsResult

# Deben coincidir con los valores usados al armar `self._box` más abajo: el auto-scroll
# calcula la posición de la línea activa a mano (sumando alturas ya renderizadas), en vez
# de depender de `translate_coordinates` (frágil entre versiones de GTK4).
_LINE_SPACING = 10
_BOX_MARGIN_TOP = 12


class LyricsView(Gtk.ScrolledWindow):
    """Letra sincronizada con la reproducción, debajo de los controles del panel derecho
    (ver ui/playback_bar.py). Sin letra sincronizada disponible mostramos el texto plano
    (si lo hay) sin resaltado, ya que no hay con qué alinearlo al tiempo de reproducción."""

    def __init__(self):
        super().__init__(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.add_css_class("purrr-lyrics-view")

        self._box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=_LINE_SPACING,
            margin_top=_BOX_MARGIN_TOP, margin_bottom=200, margin_start=16, margin_end=16,
        )
        # El margen inferior grande deja lugar para que la última línea también pueda
        # llegar a centrarse en el viewport, en vez de quedar pegada abajo del scroll.
        self.set_child(self._box)

        self._timestamps: list[float] = []
        self._labels: list[Gtk.Label] = []
        self._active_index: int = -1

        self._set_message("Sin letra disponible.")

    def _clear(self) -> None:
        while (child := self._box.get_first_child()) is not None:
            self._box.remove(child)
        self._timestamps = []
        self._labels = []
        self._active_index = -1

    def _set_message(self, text: str) -> None:
        self._clear()
        self._box.append(
            Gtk.Label(
                label=text, css_classes=["dim-label"], wrap=True,
                justify=Gtk.Justification.CENTER, margin_top=24,
            )
        )

    def set_loading(self) -> None:
        self._set_message("Buscando letra…")

    def set_lyrics(self, result: LyricsResult | None) -> None:
        self._clear()
        if result is None or (not result.synced and not result.plain):
            self._set_message("Sin letra disponible.")
            return

        if result.synced:
            for timestamp, text in result.synced:
                label = Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER)
                label.add_css_class("purrr-lyrics-line")
                label.add_css_class("dim-label")  # se saca al volverse la línea activa
                self._box.append(label)
                self._timestamps.append(timestamp)
                self._labels.append(label)
        else:
            # Letra sin marcas de tiempo: la mostramos entera, sin resaltado posible.
            self._box.append(Gtk.Label(label=result.plain, wrap=True, justify=Gtk.Justification.CENTER))

    def set_position(self, seconds: float) -> None:
        if not self._timestamps:
            return
        index = bisect.bisect_right(self._timestamps, seconds) - 1
        if index == self._active_index:
            return
        if 0 <= self._active_index < len(self._labels):
            previous = self._labels[self._active_index]
            previous.remove_css_class("purrr-lyrics-line-active")
            previous.add_css_class("dim-label")
        self._active_index = index
        if 0 <= index < len(self._labels):
            active = self._labels[index]
            active.remove_css_class("dim-label")
            active.add_css_class("purrr-lyrics-line-active")
            GLib.idle_add(self._scroll_to, index)

    def _scroll_to(self, index: int) -> bool:
        if not (0 <= index < len(self._labels)):
            return GLib.SOURCE_REMOVE
        viewport_height = self.get_height()
        if not viewport_height:
            return GLib.SOURCE_REMOVE  # todavía no se asignó tamaño (recién arrancó la app)

        y = _BOX_MARGIN_TOP + index * _LINE_SPACING + sum(
            label.get_height() for label in self._labels[:index]
        )
        target = y + self._labels[index].get_height() / 2 - viewport_height / 2

        adjustment = self.get_vadjustment()
        lower = adjustment.get_lower()
        upper = max(lower, adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(lower, min(target, upper)))
        return GLib.SOURCE_REMOVE

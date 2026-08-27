import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

_BAR_GAP_FRACTION = 0.4  # fracción del ancho de cada franja que queda como espacio entre barras
_MIN_BAR_HEIGHT_FRACTION = 0.08
_MAX_BAR_RADIUS = 1.5

_PLAYED_COLOR = (0.96, 0.75, 0.16, 1.0)
_UNPLAYED_COLOR = (1.0, 1.0, 1.0, 0.28)
_PLACEHOLDER_BARS = [0.15] * 96


class WaveformScrubber(Gtk.DrawingArea):
    """Barra de progreso que dibuja la forma de onda del track (barras verticales, coloreadas
    según cuánto ya se reprodujo) y permite hacer seek con clic o arrastre."""

    __gsignals__ = {
        "seek-requested": (GObject.SignalFlags.RUN_FIRST, None, (float,)),  # fracción 0..1
    }

    def __init__(self):
        super().__init__(hexpand=True)
        self.set_size_request(-1, 24)
        self._waveform: list[float] = []
        self._progress = 0.0
        self._drag_active = False
        self._drag_start_x = 0.0
        self.set_draw_func(self._on_draw)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

    def set_waveform(self, waveform: list[float]) -> None:
        self._waveform = waveform or []
        self.queue_draw()

    def set_progress(self, fraction: float) -> None:
        if self._drag_active:
            return
        self._progress = max(0.0, min(1.0, fraction))
        self.queue_draw()

    def _fraction_at_x(self, x: float) -> float:
        width = self.get_width()
        return max(0.0, min(1.0, x / width)) if width else 0.0

    def _on_drag_begin(self, _gesture, x: float, _y: float) -> None:
        self._drag_active = True
        self._drag_start_x = x
        self._progress = self._fraction_at_x(x)
        self.queue_draw()

    def _on_drag_update(self, _gesture, offset_x: float, _offset_y: float) -> None:
        self._progress = self._fraction_at_x(self._drag_start_x + offset_x)
        self.queue_draw()

    def _on_drag_end(self, _gesture, offset_x: float, _offset_y: float) -> None:
        self._drag_active = False
        fraction = self._fraction_at_x(self._drag_start_x + offset_x)
        self._progress = fraction
        self.queue_draw()
        self.emit("seek-requested", fraction)

    def _on_draw(self, _area, cr, width: int, height: int) -> None:
        bars = self._waveform or _PLACEHOLDER_BARS
        n = len(bars)
        if n == 0 or width <= 0:
            return
        slot_w = width / n
        bar_w = max(1.0, slot_w * (1 - _BAR_GAP_FRACTION))
        radius = min(bar_w / 2, _MAX_BAR_RADIUS)
        played_bars = round(self._progress * n)

        for i, level in enumerate(bars):
            bar_h = max(height * _MIN_BAR_HEIGHT_FRACTION, level * height)
            x = i * slot_w + (slot_w - bar_w) / 2
            y = (height - bar_h) / 2
            cr.set_source_rgba(*(_PLAYED_COLOR if i < played_bars else _UNPLAYED_COLOR))
            _rounded_rect(cr, x, y, bar_w, bar_h, radius)
            cr.fill()


def _rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.14159)
    cr.arc(x + r, y + r, r, 3.14159, 4.71239)
    cr.close_path()

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem


def _format_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class PlaybackBar(Gtk.Box):
    __gsignals__ = {
        "playback-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, engine: PlayerEngine, queue: PlayQueue):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.engine = engine
        self.queue = queue
        self._dragging = False

        self.engine.connect("position-updated", self._on_position_updated)
        self.engine.connect("eos", self._on_eos)
        self.engine.connect("error", self._on_error)

        self.add_css_class("toolbar")
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # --- Fila de metadatos + barra de progreso -------------------------
        self._title_label = Gtk.Label(label="Sin reproducción", halign=Gtk.Align.START, xalign=0)
        self._title_label.add_css_class("heading")
        self._artist_label = Gtk.Label(label="", halign=Gtk.Align.START, xalign=0)
        self._artist_label.add_css_class("dim-label")

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        info_box.append(self._title_label)
        info_box.append(self._artist_label)

        self._position_label = Gtk.Label(label="0:00")
        self._duration_label = Gtk.Label(label="0:00")

        self._scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        self._scale.set_range(0, 1)
        self._scale.set_draw_value(False)
        self._scale.connect("change-value", self._on_scale_change_value)

        press_gesture = Gtk.GestureClick()
        press_gesture.connect("pressed", lambda *_: setattr(self, "_dragging", True))
        press_gesture.connect("released", lambda *_: setattr(self, "_dragging", False))
        self._scale.add_controller(press_gesture)

        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        seek_row.append(self._position_label)
        seek_row.append(self._scale)
        seek_row.append(self._duration_label)

        # --- Fila de controles ------------------------------------------
        self._prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        self._prev_button.connect("clicked", self._on_previous_clicked)

        self._play_pause_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self._play_pause_button.connect("clicked", self._on_play_pause_clicked)

        self._next_button = Gtk.Button(icon_name="media-skip-forward-symbolic")
        self._next_button.connect("clicked", self._on_next_clicked)

        self._shuffle_button = Gtk.ToggleButton(icon_name="media-playlist-shuffle-symbolic")
        self._shuffle_button.connect("toggled", self._on_shuffle_toggled)

        self._repeat_button = Gtk.ToggleButton(icon_name="media-playlist-repeat-symbolic")
        self._repeat_button.connect("toggled", self._on_repeat_toggled)

        volume_adjustment = Gtk.Adjustment(value=1.0, lower=0.0, upper=1.0, step_increment=0.05)
        self._volume_button = Gtk.ScaleButton(adjustment=volume_adjustment)
        self._volume_button.set_icons(
            [
                "audio-volume-muted-symbolic",
                "audio-volume-high-symbolic",
                "audio-volume-low-symbolic",
                "audio-volume-medium-symbolic",
            ]
        )
        self._volume_button.connect("value-changed", self._on_volume_changed)

        controls_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        controls_row.append(self._shuffle_button)
        controls_row.append(self._prev_button)
        controls_row.append(self._play_pause_button)
        controls_row.append(self._next_button)
        controls_row.append(self._repeat_button)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_row.append(info_box)
        top_row.append(controls_row)
        top_row.append(self._volume_button)

        self.append(top_row)
        self.append(seek_row)

        self._set_controls_sensitive(False)

    def play_queue_item(self, item: QueueItem) -> None:
        self.engine.load(Path(item.local_path))
        self.engine.play()
        self._title_label.set_text(item.title)
        self._artist_label.set_text(item.artist or "Artista desconocido")
        self._scale.set_range(0, max(item.duration_seconds, 1))
        self._duration_label.set_text(_format_time(item.duration_seconds))
        self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
        self._set_controls_sensitive(True)

    def _set_controls_sensitive(self, sensitive: bool) -> None:
        for widget in (self._prev_button, self._play_pause_button, self._next_button, self._scale):
            widget.set_sensitive(sensitive)

    def _on_play_pause_clicked(self, _button) -> None:
        if self.queue.is_empty():
            return
        if self._play_pause_button.get_icon_name() == "media-playback-start-symbolic":
            self.engine.play()
            self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
        else:
            self.engine.pause()
            self._play_pause_button.set_icon_name("media-playback-start-symbolic")

    def _on_previous_clicked(self, _button) -> None:
        item = self.queue.previous()
        if item:
            self.play_queue_item(item)

    def _on_next_clicked(self, _button) -> None:
        item = self.queue.next()
        if item:
            self.play_queue_item(item)

    def _on_shuffle_toggled(self, button: Gtk.ToggleButton) -> None:
        self.queue.toggle_shuffle(button.get_active())

    def _on_repeat_toggled(self, button: Gtk.ToggleButton) -> None:
        self.queue.repeat = button.get_active()

    def _on_volume_changed(self, _button, value: float) -> None:
        self.engine.set_volume(value)

    def _on_scale_change_value(self, _range, _scroll_type, value: float) -> bool:
        self.engine.seek(value)
        return False

    def _on_position_updated(self, _engine, position: float, duration: float) -> None:
        if self._dragging:
            return
        self._scale.set_range(0, max(duration, 1))
        self._scale.set_value(position)
        self._position_label.set_text(_format_time(position))
        self._duration_label.set_text(_format_time(duration))

    def _on_eos(self, _engine) -> None:
        item = self.queue.next()
        if item:
            self.play_queue_item(item)
        else:
            self._play_pause_button.set_icon_name("media-playback-start-symbolic")
            self._scale.set_value(0)

    def _on_error(self, _engine, message: str) -> None:
        self.emit("playback-error", message)

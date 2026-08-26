from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem
from purrr.sync.controller import SyncController


def _format_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class PlaybackBar(Gtk.Box):
    __gsignals__ = {
        "playback-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "now-playing-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # QueueItem
    }

    def __init__(self, engine: PlayerEngine, queue: PlayQueue, sync_controller: SyncController):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.engine = engine
        self.queue = queue
        self._sync_controller = sync_controller
        self._dragging = False
        self._pending_track_id: int | None = None

        self.engine.connect("position-updated", self._on_position_updated)
        self.engine.connect("eos", self._on_eos)
        self.engine.connect("error", self._on_error)

        self.add_css_class("toolbar")
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # --- Fila de metadatos + barra de progreso -------------------------
        self._art_picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self._art_picture.set_size_request(48, 48)
        self._art_picture.add_css_class("card")
        self._art_picture.set_visible(False)

        self._title_label = Gtk.Label(label="Sin reproducción", halign=Gtk.Align.START, xalign=0)
        self._title_label.add_css_class("heading")
        self._artist_label = Gtk.Label(label="", halign=Gtk.Align.START, xalign=0)
        self._artist_label.add_css_class("dim-label")

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        text_box.append(self._title_label)
        text_box.append(self._artist_label)

        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, hexpand=True)
        info_box.append(self._art_picture)
        info_box.append(text_box)

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
        self._pending_track_id = item.track_id
        if item.local_path and Path(item.local_path).exists():
            self._start_playback(item)
            self._prefetch_next()
        else:
            self._show_downloading(item)
            self._sync_controller.download_track(
                item.track_id,
                on_complete=lambda local_path, art_path: self._on_download_complete(
                    item, local_path, art_path
                ),
                on_error=lambda message: self._on_download_error(item, message),
            )

    def _start_playback(self, item: QueueItem) -> None:
        self.engine.load(Path(item.local_path))
        self.engine.play()
        self._title_label.set_text(item.title)
        self._artist_label.set_text(item.artist or "Artista desconocido")
        self._scale.set_range(0, max(item.duration_seconds, 1))
        self._duration_label.set_text(_format_time(item.duration_seconds))
        self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
        self._set_controls_sensitive(True)
        self._update_art(item.art_path)
        self.emit("now-playing-changed", item)

    def _update_art(self, art_path: str | None) -> None:
        if art_path and Path(art_path).exists():
            self._art_picture.set_filename(art_path)
            self._art_picture.set_visible(True)
        else:
            self._art_picture.set_visible(False)

    def _show_downloading(self, item: QueueItem) -> None:
        self._title_label.set_text(f"Descargando: {item.title}…")
        self._artist_label.set_text(item.artist or "")
        self._update_art(item.art_path)
        self._set_controls_sensitive(False)

    def _on_download_complete(self, item: QueueItem, local_path: str, art_path: str | None) -> None:
        if self._pending_track_id != item.track_id:
            return  # el usuario ya cambió de canción mientras se descargaba esta
        item.local_path = local_path
        if art_path:
            item.art_path = art_path
        self._start_playback(item)
        self._prefetch_next()

    def _on_download_error(self, item: QueueItem, message: str) -> None:
        if self._pending_track_id == item.track_id:
            self._title_label.set_text("Sin reproducción")
            self._artist_label.set_text("")
        self.emit("playback-error", f"No se pudo descargar «{item.title}»: {message}")

    def _prefetch_next(self) -> None:
        next_item = self.queue.peek_next()
        if next_item and not (next_item.local_path and Path(next_item.local_path).exists()):
            self._sync_controller.download_track(
                next_item.track_id,
                on_complete=lambda local_path, art_path, i=next_item: (
                    setattr(i, "local_path", local_path),
                    setattr(i, "art_path", art_path) if art_path else None,
                ),
            )

    # --- API pública (también usada por el servicio MPRIS) ------------------

    def play_pause(self) -> None:
        self._on_play_pause_clicked(None)

    def next(self) -> None:
        self._on_next_clicked(None)

    def previous(self) -> None:
        self._on_previous_clicked(None)

    def is_playing(self) -> bool:
        return self._play_pause_button.get_icon_name() == "media-playback-pause-symbolic"

    def current_position(self) -> float:
        return self.engine.get_position() or 0.0

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

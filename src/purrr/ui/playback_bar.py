from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GObject, Gtk, Pango

from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem
from purrr.sync.controller import SyncController
from purrr.ui.textures import load_texture_at_size
from purrr.ui.waveform_scrubber import WaveformScrubber

_ART_THUMB_SIZE = 72  # ~alto combinado de la columna de texto + controles + onda, a la derecha
_ART_EXPANDED_SIZE = 360


def _format_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class PlaybackBar(Gtk.Box):
    __gsignals__ = {
        "playback-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "now-playing-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # QueueItem
    }

    def __init__(self, engine: PlayerEngine, queue: PlayQueue, sync_controller: SyncController):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.engine = engine
        self.queue = queue
        self._sync_controller = sync_controller
        self._pending_track_id: int | None = None
        self._current_duration = 1.0
        self._waveform_token: int | None = None
        self._art_token: int | None = None

        self.engine.connect("position-updated", self._on_position_updated)
        self.engine.connect("eos", self._on_eos)
        self.engine.connect("error", self._on_error)

        self.add_css_class("toolbar")
        self.add_css_class("purrr-playback-card")
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # --- Carátula: a la izquierda, ocupa toda la altura de la barra --------
        self._current_art_path: str | None = None

        self._art_picture = Gtk.Picture(
            content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, hexpand=False, vexpand=False
        )
        self._art_picture.set_size_request(_ART_THUMB_SIZE, _ART_THUMB_SIZE)

        self._art_button = Gtk.Button(has_frame=False, valign=Gtk.Align.CENTER, tooltip_text="Ver carátula")
        self._art_button.add_css_class("flat")
        self._art_button.add_css_class("purrr-art-rounded")
        self._art_button.set_overflow(Gtk.Overflow.HIDDEN)
        self._art_button.set_child(self._art_picture)
        self._art_button.connect("clicked", self._on_art_clicked)
        # Siempre visible (aunque el track no tenga carátula) para que la columna de la derecha
        # arranque siempre en el mismo lugar — sin imagen, queda como un espacio vacío.
        self._art_button.set_sensitive(False)
        self.append(self._art_button)

        # Una sola fila horizontal (texto | onda | controles | volumen) en vez de dos apiladas —
        # la barra queda más baja y la onda puede ser más alta dentro de esa única fila.
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, hexpand=True, valign=Gtk.Align.CENTER)

        self._title_label = Gtk.Label(label="Sin reproducción", halign=Gtk.Align.START, xalign=0)
        self._title_label.add_css_class("heading")
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._artist_label = Gtk.Label(label="", halign=Gtk.Align.START, xalign=0)
        self._artist_label.add_css_class("dim-label")
        self._artist_label.set_ellipsize(Pango.EllipsizeMode.END)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=False)
        text_box.set_size_request(150, -1)
        text_box.append(self._title_label)
        text_box.append(self._artist_label)

        self._position_label = Gtk.Label(label="0:00")
        self._duration_label = Gtk.Label(label="0:00")

        self._waveform_scrubber = WaveformScrubber()
        self._waveform_scrubber.connect("seek-requested", self._on_scrubber_seek)

        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, hexpand=True)
        seek_row.append(self._position_label)
        seek_row.append(self._waveform_scrubber)
        seek_row.append(self._duration_label)

        # --- Controles ------------------------------------------
        self._prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        self._prev_button.connect("clicked", self._on_previous_clicked)

        self._play_pause_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self._play_pause_button.add_css_class("circular")
        self._play_pause_button.add_css_class("purrr-accent-button")
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

        right_box.append(text_box)
        right_box.append(seek_row)
        right_box.append(controls_row)
        right_box.append(self._volume_button)
        self.append(right_box)

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
        self._current_duration = max(item.duration_seconds, 1)
        self._duration_label.set_text(_format_time(item.duration_seconds))
        self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
        self._set_controls_sensitive(True)
        if not item.art_path:
            # Este track ya estaba cacheado de una sesión anterior (por eso nunca pasó por
            # download_track/_run_download), así que nadie intentó todavía sacarle la carátula
            # embebida — la rescatamos ahora, sin red, antes de mostrarlo.
            item.art_path = self._sync_controller.resolve_local_art(item.track_id, item.local_path)
        self._update_art(item.art_path)
        self._art_token = item.track_id
        if not item.art_path:
            # Tampoco tiene carátula embebida: buscamos un cover.jpg/folder.png en su carpeta de
            # Drive antes de resignarnos a dejar el espacio vacío. Esto sí pega a la red, así que
            # va en un hilo aparte y no bloquea el arranque de la reproducción.
            self._sync_controller.ensure_folder_cover_art(
                item.track_id,
                on_complete=lambda path, track_id=item.track_id: self._on_folder_cover_ready(track_id, path),
            )
        self._load_waveform(item)
        self.emit("now-playing-changed", item)

    def _on_folder_cover_ready(self, track_id: int, art_path: str | None) -> None:
        if track_id != self._art_token or not art_path:
            return  # el usuario ya cambió de canción, o no había nada que mostrar
        self._update_art(art_path)

    def _load_waveform(self, item: QueueItem) -> None:
        self._waveform_token = item.track_id
        self._waveform_scrubber.set_waveform([])
        self._waveform_scrubber.set_progress(0.0)
        self._sync_controller.ensure_waveform(
            item.drive_file_id, item.local_path,
            on_complete=lambda bars, track_id=item.track_id: self._on_waveform_ready(track_id, bars),
        )

    def _on_waveform_ready(self, track_id: int, bars: list[float]) -> None:
        if track_id != self._waveform_token:
            return  # el usuario ya cambió de canción mientras se calculaba esta
        self._waveform_scrubber.set_waveform(bars)

    def _update_art(self, art_path: str | None) -> None:
        self._current_art_path = art_path
        if art_path and Path(art_path).exists():
            texture = load_texture_at_size(art_path, _ART_THUMB_SIZE)
            if texture:
                self._art_picture.set_paintable(texture)
                self._art_button.set_sensitive(True)
                return
        self._art_picture.set_paintable(None)
        self._art_button.set_sensitive(False)

    def _on_art_clicked(self, button: Gtk.Button) -> None:
        if not self._current_art_path or not Path(self._current_art_path).exists():
            return
        texture = load_texture_at_size(self._current_art_path, _ART_EXPANDED_SIZE)
        if not texture:
            return
        picture = Gtk.Picture(
            paintable=texture,
            content_fit=Gtk.ContentFit.CONTAIN,
            width_request=_ART_EXPANDED_SIZE,
            height_request=_ART_EXPANDED_SIZE,
        )
        popover = Gtk.Popover()
        popover.set_parent(button)
        popover.set_child(picture)
        popover.popup()

    def _show_downloading(self, item: QueueItem) -> None:
        self._title_label.set_text(f"Descargando: {item.title}…")
        self._artist_label.set_text(item.artist or "")
        self._update_art(item.art_path)
        self._art_token = None
        self._waveform_token = None
        self._waveform_scrubber.set_waveform([])
        self._waveform_scrubber.set_progress(0.0)
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
        for widget in (
            self._prev_button, self._play_pause_button, self._next_button, self._waveform_scrubber,
        ):
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

    def _on_scrubber_seek(self, _widget, fraction: float) -> None:
        if self.queue.is_empty():
            return
        self.engine.seek(fraction * self._current_duration)

    def _on_position_updated(self, _engine, position: float, duration: float) -> None:
        self._current_duration = max(duration, 1)
        self._waveform_scrubber.set_progress(position / self._current_duration)
        self._position_label.set_text(_format_time(position))
        self._duration_label.set_text(_format_time(duration))

    def _on_eos(self, _engine) -> None:
        item = self.queue.next()
        if item:
            self.play_queue_item(item)
        else:
            self._play_pause_button.set_icon_name("media-playback-start-symbolic")
            self._waveform_scrubber.set_progress(0.0)

    def _on_error(self, _engine, message: str) -> None:
        self.emit("playback-error", message)

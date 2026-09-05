import hashlib
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, GObject, Gtk, Pango

from purrr.cache import manager as cache_manager
from purrr.metadata import cover_search
from purrr.player import pls_resolver
from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem
from purrr.player.sources import rainwave as rainwave_source
from purrr.player.spotify_connect import SpotifyConnectController
from purrr.player.station import Station
from purrr.spotify.track import SpotifyTrack
from purrr.sync.controller import SyncController
from purrr.ui.textures import load_texture_at_size
from purrr.ui.waveform_scrubber import WaveformScrubber

_ART_THUMB_SIZE = 240  # carátula grande, centrada arriba del panel de reproducción
_ART_EXPANDED_SIZE = 360
_RAINWAVE_POLL_SECONDS = 20  # canciones duran minutos; esto alcanza para no perderse un cambio


def _format_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class PlaybackBar(Gtk.Box):
    __gsignals__ = {
        "playback-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "now-playing-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # QueueItem
        "play-recorded": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # track_id, para Estadísticas
        # 'local' | 'station' | 'spotify' — sobre todo para que window.py sepa cuándo
        # apagar el resalte de la fila de una radio (ver ui/stations_view.py) al
        # dejar de sonar, sin importar por qué (otra fuente, fin de stream, error).
        "playback-mode-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, engine: PlayerEngine, queue: PlayQueue, sync_controller: SyncController):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.engine = engine
        self.queue = queue
        self._sync_controller = sync_controller
        self._pending_track_id: int | None = None
        self._current_duration = 1.0
        # Para Estadísticas: id del track ya contado como "reproducción" en esta pasada
        # (ver _maybe_record_play) — se resetea en cada _start_playback para que la
        # siguiente canción pueda volver a contar la suya.
        self._play_recorded_track_id: int | None = None
        self._waveform_token: int | None = None
        self._art_token: int | None = None
        self._playback_mode = "local"  # 'local' | 'station' | 'spotify'
        self._station_resolve_token: Station | None = None
        self._station_art_token: object | None = None
        # Rainwave no manda metadata ICY (ver player/sources/rainwave.py), así que en
        # vez de esperar tags del stream (como con Bío-Bío/SmoothJazz/RadioTunes) hay
        # que pedirle la canción actual a su API pública en un hilo — ver play_station.
        self._rainwave_poll_token: Station | None = None
        self._rainwave_last_title: str | None = None

        self.engine.connect("position-updated", self._on_position_updated)
        self.engine.connect("eos", self._on_eos)
        self.engine.connect("error", self._on_error)
        self.engine.connect("tags-changed", self._on_tags_changed)
        self._current_station: Station | None = None

        self._spotify_controller = SpotifyConnectController()
        self._spotify_controller.connect("position-updated", self._on_spotify_position_updated)
        self._spotify_controller.connect("ended", self._on_spotify_ended)
        self._spotify_controller.connect("no-device", self._on_spotify_no_device)
        self._spotify_controller.connect("error", self._on_spotify_error)

        self.add_css_class("purrr-player-panel")

        # --- Carátula: grande, centrada arriba del panel -----------------------
        self._current_art_path: str | None = None

        self._art_picture = Gtk.Picture(
            content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, hexpand=False, vexpand=False
        )
        self._art_picture.set_size_request(_ART_THUMB_SIZE, _ART_THUMB_SIZE)

        self._art_button = Gtk.Button(has_frame=False, halign=Gtk.Align.CENTER, tooltip_text="Ver carátula")
        self._art_button.add_css_class("flat")
        self._art_button.add_css_class("purrr-art-rounded")
        self._art_button.set_overflow(Gtk.Overflow.HIDDEN)
        self._art_button.set_child(self._art_picture)
        self._art_button.connect("clicked", self._on_art_clicked)
        # Siempre visible (aunque el track no tenga carátula) para que el resto del panel
        # arranque siempre en el mismo lugar — sin imagen, queda como un espacio vacío.
        self._art_button.set_sensitive(False)
        self.append(self._art_button)

        # --- Texto: título y artista, centrados debajo de la carátula ----------
        self._title_label = Gtk.Label(label="Sin reproducción", halign=Gtk.Align.CENTER, justify=Gtk.Justification.CENTER)
        self._title_label.add_css_class("title-3")
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._artist_label = Gtk.Label(label="", halign=Gtk.Align.CENTER, justify=Gtk.Justification.CENTER)
        self._artist_label.add_css_class("dim-label")
        self._artist_label.set_ellipsize(Pango.EllipsizeMode.END)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER)
        text_box.append(self._title_label)
        text_box.append(self._artist_label)
        self.append(text_box)

        # --- Barra de progreso (onda + posición/duración) -----------------------
        self._position_label = Gtk.Label(label="0:00")
        self._position_label.add_css_class("caption")
        self._duration_label = Gtk.Label(label="0:00")
        self._duration_label.add_css_class("caption")

        self._waveform_scrubber = WaveformScrubber()
        self._waveform_scrubber.connect("seek-requested", self._on_scrubber_seek)

        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, hexpand=True)
        seek_row.append(self._position_label)
        seek_row.append(self._waveform_scrubber)
        seek_row.append(self._duration_label)
        self.append(seek_row)

        # --- Controles, centrados ------------------------------------------
        self._prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        self._prev_button.connect("clicked", self._on_previous_clicked)

        self._play_pause_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self._play_pause_button.add_css_class("circular")
        self._play_pause_button.add_css_class("purrr-accent-button")
        self._play_pause_button.add_css_class("purrr-play-button")
        self._play_pause_button.connect("clicked", self._on_play_pause_clicked)

        self._next_button = Gtk.Button(icon_name="media-skip-forward-symbolic")
        self._next_button.connect("clicked", self._on_next_clicked)

        self._shuffle_button = Gtk.ToggleButton(icon_name="media-playlist-shuffle-symbolic")
        self._shuffle_button.connect("toggled", self._on_shuffle_toggled)

        self._repeat_button = Gtk.ToggleButton(icon_name="media-playlist-repeat-symbolic")
        self._repeat_button.connect("toggled", self._on_repeat_toggled)

        controls_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.CENTER)
        controls_row.append(self._shuffle_button)
        controls_row.append(self._prev_button)
        controls_row.append(self._play_pause_button)
        controls_row.append(self._next_button)
        controls_row.append(self._repeat_button)
        self.append(controls_row)

        # --- Volumen, al final: deslizador + ícono que hace mute/unmute --------
        self._pre_mute_volume = 1.0
        self._volume_adjustment = Gtk.Adjustment(value=1.0, lower=0.0, upper=1.0, step_increment=0.05)
        self._volume_adjustment.connect("value-changed", self._on_volume_changed)

        self._volume_icon_button = Gtk.Button(
            icon_name="audio-volume-high-symbolic", has_frame=False, tooltip_text="Silenciar"
        )
        self._volume_icon_button.connect("clicked", self._on_volume_icon_clicked)

        self._volume_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=self._volume_adjustment, hexpand=True
        )
        self._volume_scale.set_draw_value(False)
        self._volume_scale.set_size_request(120, -1)

        volume_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        volume_row.append(self._volume_icon_button)
        volume_row.append(self._volume_scale)
        self.append(volume_row)

        self._set_controls_sensitive(False)

    def play_queue_item(self, item: QueueItem) -> None:
        if item.source == "spotify":
            self._play_spotify_queue_item(item)
            return
        self._set_playback_mode("local")
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
        self._play_recorded_track_id = None
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

    def play_station(self, station: Station) -> None:
        """Sintoniza una radio en vivo (Rainwave, Bío-Bío, SmoothJazz, RadioTunes)
        — a diferencia de `play_queue_item`, va directo al stream por URI: no hay
        archivo que descargar, ni duración, ni waveform que precalcular.

        RadioTunes es la única fuente cuya URI no es directamente reproducible: es
        un `.pls` que hay que bajar y resolver primero (confirmé con
        `gst-launch-1.0` que `playbin` no lo hace solo — ver
        `player/pls_resolver.py`). Las demás (Rainwave/Bío-Bío/SmoothJazz) siguen
        yendo directo al reproductor, sin este paso."""
        self._set_playback_mode("station")
        self._current_station = station
        self._title_label.set_text(station.display_name)
        self._station_art_token = None
        self._update_art(None)
        self._station_resolve_token = station
        self._rainwave_last_title = None
        if station.provider == "rainwave":
            self._rainwave_poll_token = station
            self._start_rainwave_polling(station)
        else:
            self._rainwave_poll_token = None
        if pls_resolver.is_pls_url(station.stream_url):
            self._artist_label.set_text("Conectando…")
            self._set_controls_sensitive(False)
            threading.Thread(
                target=self._resolve_and_play_station, args=(station,), daemon=True
            ).start()
        else:
            self._artist_label.set_text(station.subtitle or "En vivo")
            self._start_station_stream(station, station.stream_url)

    def _resolve_and_play_station(self, station: Station) -> None:
        try:
            resolved_url = pls_resolver.resolve_pls_url(station.stream_url)
        except Exception as exc:  # noqa: BLE001 — se reporta a la UI
            GLib.idle_add(self._on_station_resolve_error, station, str(exc))
            return
        GLib.idle_add(self._start_station_stream, station, resolved_url)

    def _on_station_resolve_error(self, station: Station, message: str) -> bool:
        if self._station_resolve_token is not station:
            return GLib.SOURCE_REMOVE  # el usuario ya cambió de estación mientras tanto
        self.emit("playback-error", f"No se pudo conectar a «{station.display_name}»: {message}")
        self._reset_to_idle()
        return GLib.SOURCE_REMOVE

    def _start_station_stream(self, station: Station, resolved_url: str) -> bool:
        if self._station_resolve_token is not station:
            return GLib.SOURCE_REMOVE  # ya se pidió otra estación, esta resolución quedó vieja
        self.engine.load(resolved_url)
        self.engine.play()
        self._artist_label.set_text(station.subtitle or "En vivo")
        self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
        self._set_controls_sensitive(True)
        return GLib.SOURCE_REMOVE

    def play_spotify_track(self, track: SpotifyTrack, art_path: str | None = None) -> None:
        """Reproduce un track de Spotify por Spotify Connect (control remoto — Purrr
        nunca decodifica ese audio). A diferencia de una estación, sí hay duración
        conocida y posición (por polling de `SpotifyConnectController`, no de
        GStreamer) — el seek manual queda fuera de esta etapa."""
        self._set_playback_mode("spotify")
        self._title_label.set_text(track.title)
        self._artist_label.set_text(track.artist or "Artista desconocido")
        self._current_duration = max(track.duration_seconds or 1, 1)
        self._position_label.set_text("0:00")
        self._duration_label.set_text(_format_time(track.duration_seconds or 0))
        self._waveform_scrubber.set_waveform([])
        self._waveform_scrubber.set_progress(0.0)
        self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
        self._set_controls_sensitive(True)
        self._update_art(art_path)
        self._spotify_controller.play(track)

    def _play_spotify_queue_item(self, item: QueueItem) -> None:
        spotify_id = item.track_id.rsplit(":", 1)[-1] if isinstance(item.track_id, str) else str(item.track_id)
        track = SpotifyTrack(
            id=spotify_id, title=item.title, artist=item.artist, album=item.album,
            duration_seconds=item.duration_seconds, art_url=None, uri=item.spotify_uri,
        )
        self.play_spotify_track(track, art_path=item.art_path)

    def _set_playback_mode(self, mode: str) -> None:
        if self._playback_mode == mode:
            return
        previous = self._playback_mode
        self._playback_mode = mode
        self.emit("playback-mode-changed", mode)
        if previous == "spotify" and mode != "spotify":
            self._spotify_controller.stop()
        if previous == "station" and mode != "station":
            # Se dejó de escuchar una radio para pasar a otra fuente — sin esto, el
            # polling de Rainwave (si era la que sonaba) seguiría pisando el título y
            # la carátula del track/track de Spotify recién elegido.
            self._rainwave_poll_token = None
            self._station_art_token = None
        # "Siguiente/anterior" y shuffle/repeat no aplican a una radio en vivo (no hay
        # cola detrás); para Spotify sí aplican — es un item más de la cola normal,
        # mezclado con tracks de Drive (playlists mixtas).
        for widget in (self._prev_button, self._next_button, self._shuffle_button, self._repeat_button):
            widget.set_sensitive(mode != "station")
        if mode == "station":
            self._waveform_scrubber.set_waveform([])
            self._waveform_scrubber.set_progress(0.0)
            self._position_label.set_text("EN VIVO")
            self._duration_label.set_text("")
        elif mode == "local":
            self._position_label.set_text("0:00")
            self._duration_label.set_text("0:00")
        # modo "spotify": las labels de tiempo las actualiza _on_spotify_position_updated;
        # play_spotify_track ya deja un placeholder razonable mientras llega el primer poll.

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
        if self._playback_mode == "spotify":
            if self._play_pause_button.get_icon_name() == "media-playback-start-symbolic":
                self._spotify_controller.resume()
                self._play_pause_button.set_icon_name("media-playback-pause-symbolic")
            else:
                self._spotify_controller.pause()
                self._play_pause_button.set_icon_name("media-playback-start-symbolic")
            return
        if self.queue.is_empty() and self._playback_mode == "local":
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

    def _on_volume_changed(self, adjustment: Gtk.Adjustment) -> None:
        value = adjustment.get_value()
        self.engine.set_volume(value)
        if value > 0.0:
            # Recordamos el último volumen "con sonido" para restaurarlo al desactivar
            # el mute — así el ícono no vuelve siempre al 100% sin importar de dónde
            # venía el usuario.
            self._pre_mute_volume = value
        self._update_volume_icon(value)

    def _on_volume_icon_clicked(self, _button) -> None:
        if self._volume_adjustment.get_value() > 0.0:
            self._pre_mute_volume = self._volume_adjustment.get_value()
            self._volume_adjustment.set_value(0.0)
        else:
            self._volume_adjustment.set_value(self._pre_mute_volume or 1.0)

    def _update_volume_icon(self, value: float) -> None:
        if value <= 0.0:
            icon, tooltip = "audio-volume-muted-symbolic", "Reactivar sonido"
        elif value < 0.34:
            icon, tooltip = "audio-volume-low-symbolic", "Silenciar"
        elif value < 0.67:
            icon, tooltip = "audio-volume-medium-symbolic", "Silenciar"
        else:
            icon, tooltip = "audio-volume-high-symbolic", "Silenciar"
        self._volume_icon_button.set_icon_name(icon)
        self._volume_icon_button.set_tooltip_text(tooltip)

    def _on_scrubber_seek(self, _widget, fraction: float) -> None:
        # Ni una radio en vivo ni (por ahora) Spotify Connect aceptan seek manual —
        # ver el plan de la Fase 4 (limitación aceptada).
        if self.queue.is_empty() or self._playback_mode != "local":
            return
        self.engine.seek(fraction * self._current_duration)

    def _on_position_updated(self, _engine, position: float, duration: float) -> None:
        self._current_duration = max(duration, 1)
        self._waveform_scrubber.set_progress(position / self._current_duration)
        self._position_label.set_text(_format_time(position))
        self._duration_label.set_text(_format_time(duration))
        self._maybe_record_play(position)

    def _maybe_record_play(self, position: float) -> None:
        """Cuenta una reproducción para Estadísticas recién al llegar a la mitad de la
        canción (o 30s, lo que sea menor) — no en cuanto arranca. Sin este umbral,
        saltar rápido entre canciones mientras buscás algo para escuchar inflaría el
        contador de "más escuchadas" igual que si las hubieras escuchado enteras."""
        if self._playback_mode != "local" or self._pending_track_id is None:
            return
        if self._play_recorded_track_id == self._pending_track_id:
            return
        threshold = min(30.0, self._current_duration / 2)
        if position >= threshold:
            self._play_recorded_track_id = self._pending_track_id
            self.emit("play-recorded", self._pending_track_id)

    def _on_eos(self, _engine) -> None:
        if self._playback_mode == "station":
            # No aplica "siguiente track" a una radio en vivo — se corta sin más.
            # Reconexión automática ante un corte queda fuera de esta etapa.
            self._reset_to_idle()
            return
        item = self.queue.next()
        if item:
            self.play_queue_item(item)
        else:
            self._play_pause_button.set_icon_name("media-playback-start-symbolic")
            self._waveform_scrubber.set_progress(0.0)

    def _on_error(self, _engine, message: str) -> None:
        if self._playback_mode == "station":
            self._reset_to_idle()
        self.emit("playback-error", message)

    def _on_tags_changed(self, _engine, title: str) -> None:
        """Nombre de la canción que anuncia el stream de radio (metadata ICY) — solo
        aplica en modo 'station': un archivo local también dispara tags al cargar
        (sus propios título/artista embebidos), pero esos ya se muestran desde
        `item.title`/`item.artist` en `_start_playback`, no hace falta pisarlos acá."""
        if self._playback_mode != "station" or self._current_station is None:
            return
        title = title.strip()
        if not title:
            return
        station_name = self._current_station.display_name
        if " - " in title:
            artist, _, song = title.partition(" - ")
            artist, song = artist.strip(), song.strip()
            self._title_label.set_text(song or title)
            self._artist_label.set_text(f"{artist} · {station_name}" if artist else station_name)
            self._fetch_station_track_art(artist, song)
        else:
            # No todos los streams mandan "Artista - Canción" (Rainwave, por ejemplo, no
            # manda nada útil acá) — sin ese dato no hay con qué buscar carátula, así
            # que solo mostramos el nombre de la estación, sin arte.
            self._title_label.set_text(title)
            self._artist_label.set_text(station_name)
            self._station_art_token = None
            self._update_art(None)

    def _fetch_station_track_art(self, artist: str, song: str) -> None:
        """Busca en la API pública de iTunes la carátula de la canción que el stream
        acaba de anunciar (mismo mecanismo que `metadata/cover_search.py` usa para
        álbumes, pero automático: sin diálogo de aprobación, se toma el primer
        resultado). Sin conexión o sin resultados, el espacio de arte queda vacío —
        nunca bloquea ni corta la reproducción. Ver `_apply_rainwave_now_playing`
        para el caso de Rainwave, que ya trae su propia URL de carátula (no hace
        falta adivinarla por búsqueda)."""
        token = (artist, song)
        self._station_art_token = token
        self._update_art(None)  # limpia la carátula de la canción anterior mientras busca
        if not artist and not song:
            return

        def worker() -> None:
            try:
                candidates = cover_search.search_covers(f"{artist} {song}".strip(), limit=1)
                if not candidates:
                    return
                url = candidates[0].thumb_url
                data = cover_search.download_cover(url)
            except Exception:  # noqa: BLE001 — sin arte para esta canción, no es un error visible
                return
            self._save_and_apply_art(url, data, f"station-{hashlib.sha1(f'{artist}|{song}'.encode()).hexdigest()}", token)

        threading.Thread(target=worker, daemon=True).start()

    def _save_and_apply_art(self, url: str, data: bytes, key: str, token: object) -> None:
        """Corre en el hilo de descarga: cachea los bytes y agenda aplicarlos en el
        hilo principal de GTK (ver `_apply_station_art`)."""
        ext = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        path = cache_manager.art_cache_path(key, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        GLib.idle_add(self._apply_station_art, token, str(path))

    def _apply_station_art(self, token: object, path: str) -> bool:
        if self._station_art_token != token:
            return GLib.SOURCE_REMOVE  # la canción ya cambió mientras se buscaba/bajaba
        self._update_art(path)
        return GLib.SOURCE_REMOVE

    # --- Rainwave: sin metadata ICY, así que se pide por su API pública ------

    def _start_rainwave_polling(self, station: Station) -> None:
        """Rainwave no manda "Artista - Canción" en el stream (ver
        player/sources/rainwave.py), así que en vez de esperar tags acá se pregunta
        a su API cada `_RAINWAVE_POLL_SECONDS` mientras esta siga siendo la estación
        activa — el propio `while` corta el hilo solo en cuanto cambias de estación
        (se nota, como mucho, un poll de atraso)."""

        def worker() -> None:
            while self._rainwave_poll_token is station:
                try:
                    info = rainwave_source.get_now_playing(station.slug)
                except Exception:  # noqa: BLE001 — sin conexión, se reintenta en el próximo poll
                    info = None
                if self._rainwave_poll_token is not station:
                    return
                if info:
                    GLib.idle_add(self._apply_rainwave_now_playing, station, info)
                time.sleep(_RAINWAVE_POLL_SECONDS)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_rainwave_now_playing(self, station: Station, info: rainwave_source.NowPlaying) -> bool:
        if self._rainwave_poll_token is not station:
            return GLib.SOURCE_REMOVE  # ya cambiaste de estación mientras se pedía esto
        station_name = station.display_name
        self._title_label.set_text(info.title or station_name)
        self._artist_label.set_text(f"{info.artist} · {station_name}" if info.artist else station_name)
        if info.title and info.title != self._rainwave_last_title:
            self._rainwave_last_title = info.title
            token = (station.slug, info.title)
            self._station_art_token = token
            self._fetch_url_art(info.art_url, token)
        return GLib.SOURCE_REMOVE

    def _fetch_url_art(self, url: str | None, token: object) -> None:
        """A diferencia de `_fetch_station_track_art` (que busca a ciegas en iTunes),
        acá ya sabemos exactamente qué imagen bajar — la trae la propia API de
        Rainwave junto con el título/artista."""
        if not url:
            return

        def worker() -> None:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Purrr/0.1"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = response.read()
            except Exception:  # noqa: BLE001 — sin arte para esta canción, no es un error visible
                return
            self._save_and_apply_art(url, data, f"url-{hashlib.sha1(url.encode()).hexdigest()}", token)

        threading.Thread(target=worker, daemon=True).start()

    def _reset_to_idle(self) -> None:
        self._set_playback_mode("local")
        self._title_label.set_text("Sin reproducción")
        self._artist_label.set_text("")
        self._play_pause_button.set_icon_name("media-playback-start-symbolic")
        self._waveform_scrubber.set_progress(0.0)
        self._set_controls_sensitive(not self.queue.is_empty())
        self._station_art_token = None
        self._rainwave_poll_token = None
        self._update_art(None)

    # --- Spotify Connect (control remoto — ver player/spotify_connect.py) --------

    def _on_spotify_position_updated(
        self, _controller, position: float, duration: float, is_playing: bool
    ) -> None:
        if self._playback_mode != "spotify":
            return  # eco tardío de una sesión que ya terminó
        self._current_duration = max(duration, 1)
        self._waveform_scrubber.set_progress(position / self._current_duration)
        self._position_label.set_text(_format_time(position))
        self._duration_label.set_text(_format_time(duration))
        self._play_pause_button.set_icon_name(
            "media-playback-pause-symbolic" if is_playing else "media-playback-start-symbolic"
        )

    def _on_spotify_ended(self, _controller) -> None:
        if self._playback_mode != "spotify":
            return
        item = self.queue.next()
        if item:
            self.play_queue_item(item)
        else:
            self._reset_to_idle()

    def _on_spotify_no_device(self, _controller) -> None:
        self.emit(
            "playback-error",
            "No hay ningún dispositivo Spotify Connect activo — abre Spotify en tu "
            "celular u otra computadora e intenta de nuevo.",
        )
        item = self.queue.next()
        if item:
            self.play_queue_item(item)
        else:
            self._reset_to_idle()

    def _on_spotify_error(self, _controller, message: str) -> None:
        self.emit("playback-error", message)

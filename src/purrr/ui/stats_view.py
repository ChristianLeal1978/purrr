import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.ui.markup import escape


def _play_label(count: int) -> str:
    return "1 reproducción" if count == 1 else f"{count} reproducciones"


class StatsView(Gtk.Box):
    """Pantalla 'Estadísticas': ranking de canciones y artistas más escuchados, según
    el historial de reproducciones que sincroniza `cloud/sync_engine.py` (misma
    cuenta, entre dispositivos). Vista "tonta" como `ui/mood_view.py`: no toca
    `database` directamente, solo pide refrescos vía `refresh()`."""

    __gsignals__ = {
        "track-play-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # track_id
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        scrolled.set_child(content)
        self.append(scrolled)

        content.append(Gtk.Label(
            label="Canciones más escuchadas", halign=Gtk.Align.START, css_classes=["title-4"],
        ))
        self._tracks_list = Gtk.ListBox(css_classes=["boxed-list"])
        content.append(self._tracks_list)
        self._tracks_empty_label = Gtk.Label(
            label="Todavía no has escuchado ninguna canción lo suficiente como para que "
            "aparezca aquí — continúa escuchando y esto se irá llenando solo.",
            halign=Gtk.Align.START, wrap=True, css_classes=["dim-label"], visible=False,
        )
        content.append(self._tracks_empty_label)

        content.append(Gtk.Label(
            label="Artistas más escuchados", halign=Gtk.Align.START, css_classes=["title-4"],
        ))
        self._artists_list = Gtk.ListBox(css_classes=["boxed-list"])
        content.append(self._artists_list)
        self._artists_empty_label = Gtk.Label(
            label="Todavía no hay artistas para mostrar aquí.",
            halign=Gtk.Align.START, css_classes=["dim-label"], visible=False,
        )
        content.append(self._artists_empty_label)

    def refresh(self, top_tracks: list[sqlite3.Row], top_artists: list[sqlite3.Row]) -> None:
        while row := self._tracks_list.get_row_at_index(0):
            self._tracks_list.remove(row)
        self._tracks_empty_label.set_visible(not top_tracks)
        for rank, track in enumerate(top_tracks, start=1):
            title = track["title"] or track["file_name"]
            subtitle = track["artist"] or "Artista desconocido"
            row = Adw.ActionRow(title=escape(f"{rank}. {title}"), subtitle=escape(subtitle))
            row.add_suffix(Gtk.Label(label=_play_label(track["play_count"]), css_classes=["dim-label"]))
            play_button = Gtk.Button(
                icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                tooltip_text="Reproducir",
            )
            play_button.connect(
                "clicked", lambda _b, tid=track["id"]: self.emit("track-play-requested", tid)
            )
            row.add_suffix(play_button)
            row.set_activatable_widget(play_button)
            self._tracks_list.append(row)

        while row := self._artists_list.get_row_at_index(0):
            self._artists_list.remove(row)
        self._artists_empty_label.set_visible(not top_artists)
        for rank, artist in enumerate(top_artists, start=1):
            row = Adw.ActionRow(title=escape(f"{rank}. {artist['artist']}"))
            row.add_suffix(Gtk.Label(label=_play_label(artist["play_count"]), css_classes=["dim-label"]))
            self._artists_list.append(row)

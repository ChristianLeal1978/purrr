import sqlite3

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GObject, Gtk

from purrr.ui.library_view import TrackObject, apply_now_playing, text_column


class PlaylistView(Gtk.Box):
    __gsignals__ = {
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "remove-tracks-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "rename-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "delete-playlist-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._playlist_id: int | None = None
        self._tracks: list[TrackObject] = []
        self._now_playing_track_id: int | None = None

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._title_label = Gtk.Label(halign=Gtk.Align.START, hexpand=True)
        self._title_label.add_css_class("title-2")
        header.append(self._title_label)

        rename_button = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Renombrar")
        rename_button.connect("clicked", self._on_rename_clicked)
        header.append(rename_button)

        delete_button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Eliminar playlist")
        delete_button.connect("clicked", lambda _b: self.emit("delete-playlist-requested"))
        header.append(delete_button)
        self.append(header)

        remove_row_button = Gtk.Button(label="Quitar de la playlist")
        remove_row_button.connect("clicked", self._on_remove_clicked)
        self.append(remove_row_button)

        self._store = Gio.ListStore(item_type=TrackObject)
        self._selection = Gtk.MultiSelection(model=self._store)

        self._column_view = Gtk.ColumnView(model=self._selection)
        self._column_view.append_column(text_column("Título", "title", expand=True))
        self._column_view.append_column(text_column("Artista", "artist", expand=True))
        self._column_view.append_column(text_column("Álbum", "album", expand=True))
        self._column_view.append_column(text_column("Duración", "duration_str"))
        self._column_view.connect("activate", self._on_row_activated)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._column_view)
        self.append(scrolled)

    def show_playlist(self, playlist_row: sqlite3.Row, track_rows: list[sqlite3.Row]) -> None:
        self._playlist_id = playlist_row["id"]
        self._title_label.set_text(playlist_row["name"])
        self._tracks = [TrackObject(row) for row in track_rows]
        for track, row in zip(self._tracks, track_rows):
            track.playlist_track_id = row["playlist_track_id"]
        # splice() en una sola operación en vez de append() en loop — ver el comentario en
        # LibraryView.refresh() sobre por qué el loop puede colgar la ventana.
        self._store.splice(0, self._store.get_n_items(), self._tracks)
        apply_now_playing(self._store, self._now_playing_track_id)

    def get_visible_tracks(self) -> list[TrackObject]:
        return self._tracks

    def set_now_playing(self, track_id: int | None) -> None:
        self._now_playing_track_id = track_id
        apply_now_playing(self._store, track_id)

    def _on_row_activated(self, _view, position: int) -> None:
        track: TrackObject = self._store.get_item(position)
        self.emit("track-activated", track.track_id)

    def _on_remove_clicked(self, _button) -> None:
        bitset = self._selection.get_selection()
        playlist_track_ids = [
            self._tracks[i].playlist_track_id
            for i in range(self._store.get_n_items())
            if bitset.contains(i)
        ]
        if playlist_track_ids:
            self.emit("remove-tracks-requested", playlist_track_ids)

    def _on_rename_clicked(self, _button) -> None:
        dialog = Gtk.Dialog(title="Renombrar playlist", modal=True)
        dialog.set_transient_for(self.get_root())
        entry = Gtk.Entry(text=self._title_label.get_text())
        entry.set_margin_top(12)
        entry.set_margin_bottom(12)
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        dialog.get_content_area().append(entry)
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("Renombrar", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        def on_response(dlg, response):
            if response == Gtk.ResponseType.OK and entry.get_text().strip():
                self.emit("rename-requested", entry.get_text().strip())
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.present()

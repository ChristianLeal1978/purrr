import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from purrr.auth.oauth import get_credentials
from purrr.db import database
from purrr.drive.client import get_service
from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem
from purrr.sync.controller import SyncController
from purrr.ui.drive_folder_picker import DriveFolderPickerDialog
from purrr.ui.first_run import SourcesView
from purrr.ui.library_view import LibraryView
from purrr.ui.playback_bar import PlaybackBar
from purrr.ui.playlist_view import PlaylistView
from purrr.ui.sidebar import Sidebar


def _prompt_text(parent: Gtk.Window, title: str, on_confirm) -> None:
    dialog = Gtk.Dialog(title=title, modal=True, transient_for=parent)
    entry = Gtk.Entry(margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
    dialog.get_content_area().append(entry)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button("Aceptar", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    def on_response(dlg, response):
        text = entry.get_text().strip()
        if response == Gtk.ResponseType.OK and text:
            on_confirm(text)
        dlg.destroy()

    dialog.connect("response", on_response)
    dialog.present()


class PurrrWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(1100, 750)
        self.set_title("Purrr")

        self._engine = PlayerEngine()
        self._queue = PlayQueue()
        self._sync_controller = SyncController()
        self._current_playlist_id: int | None = None
        self._current_search_text: str | None = None
        self._track_updated_source_id: int | None = None

        self._sidebar = Sidebar()
        self._library_view = LibraryView()
        self._playlist_view = PlaylistView()
        self._sources_view = SourcesView()
        self._playback_bar = PlaybackBar(self._engine, self._queue, self._sync_controller)

        self._connect_signals()
        self._build_layout()
        self._reload_all()

    # --- Construcción de la UI --------------------------------------------

    def _build_layout(self) -> None:
        self._content_stack = Gtk.Stack()
        self._content_stack.add_named(self._library_view, "library")
        self._content_stack.add_named(self._playlist_view, "playlist")
        self._content_stack.add_named(self._sources_view, "sources")

        sidebar_page = Adw.NavigationPage(child=self._sidebar, title="Purrr")
        content_page = Adw.NavigationPage(child=self._content_stack, title="Biblioteca")
        self._content_page = content_page

        split_view = Adw.NavigationSplitView(sidebar=sidebar_page, content=content_page)

        header_bar = Adw.HeaderBar()

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header_bar)
        toolbar_view.set_content(split_view)
        toolbar_view.add_bottom_bar(self._playback_bar)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _connect_signals(self) -> None:
        self._sidebar.connect("library-selected", self._on_library_selected)
        self._sidebar.connect("sources-selected", self._on_sources_selected)
        self._sidebar.connect("playlist-selected", self._on_playlist_selected)
        self._sidebar.connect("new-playlist-requested", self._on_new_playlist_requested)

        self._library_view.connect("track-activated", self._on_library_track_activated)
        self._library_view.connect("search-changed", self._on_library_search_changed)

        self._playlist_view.connect("track-activated", self._on_playlist_track_activated)
        self._playlist_view.connect("remove-tracks-requested", self._on_remove_tracks_requested)
        self._playlist_view.connect("rename-requested", self._on_playlist_rename_requested)
        self._playlist_view.connect("delete-playlist-requested", self._on_playlist_delete_requested)

        self._sources_view.connect("connect-requested", self._on_connect_requested)
        self._sources_view.connect("add-folder-requested", self._on_add_folder_requested)
        self._sources_view.connect("rescan-requested", self._on_rescan_requested)
        self._sources_view.connect("metadata-scan-requested", self._on_metadata_scan_requested)
        self._sources_view.connect("delete-source-requested", self._on_delete_source_requested)

        self._sync_controller.connect("progress", self._on_sync_progress)
        self._sync_controller.connect("finished", self._on_sync_finished)
        self._sync_controller.connect("error", self._on_sync_error)
        self._sync_controller.connect("track-updated", self._on_track_updated)
        self._sync_controller.connect("metadata-scan-finished", self._on_metadata_scan_finished)

        self._playback_bar.connect("playback-error", self._on_playback_error)

    def _reload_all(self) -> None:
        self._library_view.refresh(database.list_tracks())
        self._sidebar.refresh_playlists(database.list_playlists())
        self._sources_view.refresh_sources(database.list_sources())

    def _toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    # --- Navegación ----------------------------------------------------

    def _on_library_selected(self, _sidebar) -> None:
        self._content_page.set_title("Biblioteca")
        self._content_stack.set_visible_child_name("library")

    def _on_sources_selected(self, _sidebar) -> None:
        self._content_page.set_title("Fuentes de Google Drive")
        self._content_stack.set_visible_child_name("sources")
        self._sources_view.refresh_sources(database.list_sources())

    def _on_playlist_selected(self, _sidebar, playlist_id: int) -> None:
        playlist_row = next(
            (p for p in database.list_playlists() if p["id"] == playlist_id), None
        )
        if playlist_row is None:
            return
        self._current_playlist_id = playlist_id
        self._content_page.set_title(playlist_row["name"])
        self._playlist_view.show_playlist(playlist_row, database.list_playlist_tracks(playlist_id))
        self._content_stack.set_visible_child_name("playlist")

    def _on_new_playlist_requested(self, _sidebar) -> None:
        def on_confirm(name: str) -> None:
            database.create_playlist(name)
            self._sidebar.refresh_playlists(database.list_playlists())

        _prompt_text(self, "Nombre de la nueva playlist", on_confirm)

    # --- Biblioteca / reproducción ---------------------------------------

    def _on_library_search_changed(self, _view, text: str) -> None:
        self._current_search_text = text or None
        self._library_view.refresh(database.list_tracks(filter_text=self._current_search_text))

    def _on_library_track_activated(self, _view, track_id: int) -> None:
        tracks = self._library_view.get_visible_tracks()
        self._play_from_track_list(tracks, track_id)

    def _on_playlist_track_activated(self, _view, track_id: int) -> None:
        tracks = self._playlist_view.get_visible_tracks()
        self._play_from_track_list(tracks, track_id)

    def _play_from_track_list(self, tracks, track_id: int) -> None:
        index = next((i for i, t in enumerate(tracks) if t.track_id == track_id), None)
        if index is None:
            return
        items = [
            QueueItem(
                t.track_id, t.drive_file_id, t.title, t.artist, t.album,
                t.local_path, t.duration_seconds, t.art_path,
            )
            for t in tracks
        ]
        self._queue.set_queue(items, index)
        self._playback_bar.play_queue_item(self._queue.current())

    # --- Playlists -------------------------------------------------------

    def _on_remove_tracks_requested(self, _view, playlist_track_ids) -> None:
        for playlist_track_id in playlist_track_ids:
            database.remove_playlist_track(playlist_track_id)
        self._on_playlist_selected(self._sidebar, self._current_playlist_id)

    def _on_playlist_rename_requested(self, _view, name: str) -> None:
        database.rename_playlist(self._current_playlist_id, name)
        self._sidebar.refresh_playlists(database.list_playlists())
        self._content_page.set_title(name)

    def _on_playlist_delete_requested(self, _view) -> None:
        database.delete_playlist(self._current_playlist_id)
        self._current_playlist_id = None
        self._sidebar.refresh_playlists(database.list_playlists())
        self._on_library_selected(self._sidebar)

    # --- Fuentes / Google Drive --------------------------------------------

    def _on_connect_requested(self, _view) -> None:
        def worker() -> None:
            try:
                get_credentials()
                GLib.idle_add(self._on_connected_success)
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                GLib.idle_add(self._on_connected_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_connected_success(self) -> bool:
        self._sources_view.set_authenticated(True)
        self._toast("Cuenta de Google conectada.")
        return False

    def _on_connected_error(self, message: str) -> bool:
        self._toast(f"No se pudo conectar la cuenta: {message}")
        return False

    def _on_add_folder_requested(self, _view) -> None:
        def worker() -> None:
            try:
                creds = get_credentials()
                service = get_service(creds)
                GLib.idle_add(self._open_folder_picker, service)
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                GLib.idle_add(self._toast, f"No se pudo conectar con Drive: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _open_folder_picker(self, service) -> bool:
        def on_confirm(folder_id: str, display_name: str) -> None:
            self._sync_controller.start_scan(folder_id, display_name)

        DriveFolderPickerDialog(self, service, on_confirm).present()
        return False

    def _on_rescan_requested(self, _view, _source_id: int, folder_id: str, display_name: str) -> None:
        self._sync_controller.start_scan(folder_id, display_name)

    def _on_metadata_scan_requested(self, _view, source_id: int) -> None:
        self._sync_controller.start_metadata_scan(source_id)

    def _on_metadata_scan_finished(self, _controller, updated: int, total: int) -> None:
        self._sources_view.hide_progress()
        self._reload_all()
        self._toast(f"Etiquetas leídas: {updated} de {total} canciones actualizadas.")

    def _on_delete_source_requested(self, _view, source_id: int) -> None:
        database.delete_source(source_id)
        self._sources_view.refresh_sources(database.list_sources())
        self._library_view.refresh(database.list_tracks())

    def _on_sync_progress(self, _controller, stage: str, actual: int, total: int) -> None:
        self._sources_view.show_progress(stage, actual, total)

    def _on_sync_finished(self, _controller, total: int) -> None:
        self._sources_view.hide_progress()
        self._reload_all()
        self._toast(f"Sincronización completa: {total} canciones encontradas.")

    def _on_sync_error(self, _controller, message: str) -> None:
        self._sources_view.hide_progress()
        self._toast(f"Error al sincronizar: {message}")

    def _on_track_updated(self, _controller, _track_id: int) -> None:
        # Una o más canciones terminaron de actualizarse en segundo plano (reproducción, precarga,
        # o un escaneo de metadatos que puede disparar esta señal cientos de veces seguidas). Se
        # agrupan (debounce) para no reconstruir toda la tabla de la biblioteca por cada una —
        # eso congelaba la ventana durante un escaneo de metadatos grande.
        if self._track_updated_source_id is not None:
            GLib.source_remove(self._track_updated_source_id)
        self._track_updated_source_id = GLib.timeout_add(400, self._refresh_after_track_updates)

    def _refresh_after_track_updates(self) -> bool:
        self._track_updated_source_id = None
        self._library_view.refresh(database.list_tracks(filter_text=self._current_search_text))
        if self._current_playlist_id is not None:
            self._on_playlist_selected(self._sidebar, self._current_playlist_id)
        return False

    def _on_playback_error(self, _bar, message: str) -> None:
        self._toast(f"Error de reproducción: {message}")

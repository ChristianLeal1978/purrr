import threading
import urllib.parse
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from purrr.auth import spotify_oauth
from purrr.auth.oauth import get_credentials, is_authenticated
from purrr.cache.manager import save_album_art_bytes
from purrr.cloud import client as cloud_client
from purrr.cloud import vault as cloud_vault
from purrr.cloud.sync_engine import CloudSyncEngine
from purrr.db import database
from purrr.drive.client import get_service
from purrr.metadata import cover_search
from purrr.metadata.cover_search import CoverCandidate
from purrr.mood.controller import MoodAnalysisController
from purrr.mood.queue_builder import build_mood_queue
from purrr.mpris.service import MprisService
from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem
from purrr.player.sources import radiotunes as radiotunes_source
from purrr.player.station import Station
from purrr.spotify import client as spotify_client
from purrr.spotify.track import SpotifyTrack
from purrr.sync.controller import SyncController
from purrr.ui.album_dialogs import open_cover_approval_dialog
from purrr.ui.albums_view import AlbumsView
from purrr.ui.cloud_settings import CloudSettingsView
from purrr.ui.dialogs import prompt_text
from purrr.ui.drive_folder_picker import DriveFolderPickerDialog
from purrr.ui.first_run import SourcesView
from purrr.ui.folder_view import FolderBrowserView
from purrr.ui.library_view import LibraryView
from purrr.ui.library_view import TrackObject as LibraryTrackObject
from purrr.ui.mood_view import MoodView
from purrr.ui.playback_bar import PlaybackBar
from purrr.ui.playlist_picker import open_playlist_picker
from purrr.ui.playlist_view import PlaylistView
from purrr.ui.sidebar import Sidebar
from purrr.ui.spotify_view import SpotifyView
from purrr.ui.stations_view import StationsView


def _folder_name(folder_path: str | None) -> str | None:
    """Último segmento de una ruta de carpeta ('/Abbey Road/Disc 2' -> 'Disc 2'), para cuando
    una canción no trae etiqueta de álbum y hay que ponerle algún nombre igual."""
    if not folder_path or folder_path == "/":
        return None
    return folder_path.rstrip("/").rsplit("/", 1)[-1] or None


class PurrrWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(1280, 800)
        self.set_title("Purrr")

        self._engine = PlayerEngine()
        self._queue = PlayQueue()
        self._sync_controller = SyncController()
        self._cloud_sync_engine = CloudSyncEngine()
        self._mood_controller = MoodAnalysisController()
        self._current_playlist_id: int | None = None
        self._current_search_text: str | None = None
        self._track_updated_source_id: int | None = None

        self._sidebar = Sidebar()
        self._library_view = LibraryView()
        self._folder_view = FolderBrowserView()
        self._albums_view = AlbumsView()
        self._playlist_view = PlaylistView()
        self._sources_view = SourcesView()
        self._stations_view = StationsView()
        self._spotify_view = SpotifyView()
        self._mood_view = MoodView()
        self._cloud_settings_view = CloudSettingsView()
        self._playback_bar = PlaybackBar(self._engine, self._queue, self._sync_controller)
        self._mpris_service = MprisService(self._engine, self._queue, self._playback_bar)

        self._connect_signals()
        self._build_layout()
        self._reload_all()
        self._restore_last_view()
        self._refresh_cloud_settings_view()
        self._cloud_sync_engine.start()

    # --- Construcción de la UI --------------------------------------------

    def _build_layout(self) -> None:
        self._content_stack = Gtk.Stack()
        # Por defecto Gtk.Stack dimensiona su alto/ancho según la página MÁS GRANDE de
        # todas, no solo la visible — así que una sola pantalla con contenido sin acotar
        # (ver stations_view.py) forzaba a la ventana entera a ese tamaño sin importar
        # qué pantalla estuviera mirando el usuario, incluso más grande que su propia
        # pantalla física.
        self._content_stack.set_hhomogeneous(False)
        self._content_stack.set_vhomogeneous(False)
        self._content_stack.add_named(self._library_view, "library")
        self._content_stack.add_named(self._folder_view, "folders")
        self._content_stack.add_named(self._albums_view, "albums")
        self._content_stack.add_named(self._playlist_view, "playlist")
        self._content_stack.add_named(self._sources_view, "sources")
        self._content_stack.add_named(self._stations_view, "radios")
        self._content_stack.add_named(self._spotify_view, "spotify")
        self._content_stack.add_named(self._mood_view, "mood")
        self._content_stack.add_named(self._cloud_settings_view, "cloud")

        sidebar_page = Adw.NavigationPage(child=self._sidebar, title="Purrr")
        content_page = Adw.NavigationPage(child=self._content_stack, title="Biblioteca")
        self._content_page = content_page

        split_view = Adw.NavigationSplitView(sidebar=sidebar_page, content=content_page)
        split_view.set_hexpand(True)

        header_bar = Adw.HeaderBar()
        header_bar.add_css_class("flat")

        # El panel de reproducción vive como columna fija a la derecha (estilo "Player"
        # del mockup de referencia), no como barra angosta arriba del contenido.
        self._playback_bar.set_size_request(320, -1)
        self._playback_bar.set_hexpand(False)
        self._playback_bar.set_vexpand(True)

        body_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body_box.append(split_view)
        body_box.append(self._playback_bar)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header_bar)
        toolbar_view.set_content(body_box)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _connect_signals(self) -> None:
        self._sidebar.connect("library-selected", self._on_library_selected)
        self._sidebar.connect("folders-selected", self._on_folders_selected)
        self._sidebar.connect("albums-selected", self._on_albums_selected)
        self._sidebar.connect("sources-selected", self._on_sources_selected)
        self._sidebar.connect("radios-selected", self._on_radios_selected)
        self._sidebar.connect("spotify-selected", self._on_spotify_selected)
        self._sidebar.connect("mood-selected", self._on_mood_selected)
        self._sidebar.connect("cloud-selected", self._on_cloud_selected)
        self._sidebar.connect("playlist-selected", self._on_playlist_selected)
        self._sidebar.connect("new-playlist-requested", self._on_new_playlist_requested)

        self._library_view.connect("track-activated", self._on_library_track_activated)
        self._library_view.connect("search-changed", self._on_library_search_changed)
        self._library_view.connect("add-to-album-requested", self._on_add_to_album_requested)

        self._folder_view.connect("track-activated", self._on_folder_track_activated)
        self._folder_view.connect("scan-folder-requested", self._on_folder_scan_requested)
        self._folder_view.connect("add-to-album-requested", self._on_add_to_album_requested)
        self._folder_view.connect("add-folder-to-album-requested", self._on_add_folder_to_album_requested)

        self._albums_view.connect("album-activated", self._on_album_activated)
        self._albums_view.connect("album-art-search-requested", self._on_album_art_search_requested)
        self._albums_view.connect("album-rescan-requested", self._on_album_rescan_requested)
        self._albums_view.connect("album-art-upload-requested", self._on_album_art_upload_requested)

        self._playlist_view.connect("track-activated", self._on_playlist_track_activated)
        self._playlist_view.connect("remove-tracks-requested", self._on_remove_tracks_requested)
        self._playlist_view.connect("rename-requested", self._on_playlist_rename_requested)
        self._playlist_view.connect("delete-playlist-requested", self._on_playlist_delete_requested)

        self._sources_view.connect("connect-requested", self._on_connect_requested)
        self._sources_view.connect("add-folder-requested", self._on_add_folder_requested)
        self._sources_view.connect("rescan-requested", self._on_rescan_requested)
        self._sources_view.connect("metadata-scan-requested", self._on_metadata_scan_requested)
        self._sources_view.connect("delete-source-requested", self._on_delete_source_requested)

        self._stations_view.connect("station-activated", self._on_station_activated)
        self._stations_view.connect(
            "radiotunes-key-save-requested", self._on_radiotunes_key_save_requested
        )

        self._spotify_view.connect("client-id-save-requested", self._on_spotify_client_id_save_requested)
        self._spotify_view.connect("connect-requested", self._on_spotify_connect_requested)
        self._spotify_view.connect("search-requested", self._on_spotify_search_requested)
        self._spotify_view.connect("play-requested", self._on_spotify_play_requested)
        self._spotify_view.connect("add-to-playlist-requested", self._on_spotify_add_to_playlist_requested)

        self._mood_view.connect("analyze-library-requested", self._on_analyze_library_requested)
        self._mood_view.connect("search-requested", self._on_mood_search_requested)
        self._mood_view.connect("play-mood-requested", self._on_play_mood_requested)

        self._mood_controller.connect("models-download-progress", self._on_mood_models_download_progress)
        self._mood_controller.connect("analysis-progress", self._on_mood_analysis_progress)
        self._mood_controller.connect("analysis-finished", self._on_mood_analysis_finished)
        self._mood_controller.connect("error", self._on_mood_error)

        self._cloud_settings_view.connect("sign-in-requested", self._on_sign_in_requested)
        self._cloud_settings_view.connect("sign-up-requested", self._on_sign_up_requested)
        self._cloud_settings_view.connect("avatar-upload-requested", self._on_avatar_upload_requested)
        self._cloud_settings_view.connect("sign-out-requested", self._on_sign_out_requested)

        self._cloud_sync_engine.connect("playlists-changed", self._on_cloud_playlists_changed)
        self._cloud_sync_engine.connect("albums-changed", self._on_cloud_albums_changed)
        self._cloud_sync_engine.connect("sync-error", self._on_cloud_sync_error)

        self._sync_controller.connect("progress", self._on_sync_progress)
        self._sync_controller.connect("finished", self._on_sync_finished)
        self._sync_controller.connect("error", self._on_sync_error)
        self._sync_controller.connect("track-updated", self._on_track_updated)
        self._sync_controller.connect("metadata-scan-finished", self._on_metadata_scan_finished)

        self._playback_bar.connect("playback-error", self._on_playback_error)
        self._playback_bar.connect("now-playing-changed", self._on_now_playing_changed)

    def _reload_all(self) -> None:
        self._library_view.refresh(database.list_tracks())
        self._folder_view.refresh(database.list_sources())
        self._albums_view.refresh(database.list_albums())
        self._sidebar.refresh_playlists(database.list_playlists())
        self._sources_view.refresh_sources(database.list_sources())

    def _restore_last_view(self) -> None:
        """Vuelve a abrir la sección (y, si era Carpetas, la carpeta puntual) donde estaba el
        usuario la última vez que cerró la app."""
        last_view = database.get_state("last_view", "library")
        if last_view == "folders":
            self._on_folders_selected(self._sidebar)
            self._sidebar.select_folders_row()
            source_id = database.get_state("last_folder_source_id")
            path = database.get_state("last_folder_path")
            if source_id and path:
                self._folder_view.select_folder(int(source_id), path)
        elif last_view == "albums":
            self._on_albums_selected(self._sidebar)
            self._sidebar.select_albums_row()
        elif last_view == "sources":
            self._on_sources_selected(self._sidebar)
            self._sidebar.select_sources_row()
        elif last_view == "radios":
            self._on_radios_selected(self._sidebar)
            self._sidebar.select_radios_row()
        elif last_view == "spotify":
            self._on_spotify_selected(self._sidebar)
            self._sidebar.select_spotify_row()
        elif last_view == "mood":
            self._on_mood_selected(self._sidebar)
            self._sidebar.select_mood_row()
        elif last_view == "cloud":
            self._on_cloud_selected(self._sidebar)
            self._sidebar.select_cloud_row()
        elif last_view.startswith("playlist:"):
            playlist_id = int(last_view.split(":", 1)[1])
            if any(p["id"] == playlist_id for p in database.list_playlists()):
                self._on_playlist_selected(self._sidebar, playlist_id)
                self._sidebar.select_playlist_row(playlist_id)
        # "library" es el default con el que ya arranca todo, no hace falta nada más.

    def _toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    # --- Navegación ----------------------------------------------------

    def _on_library_selected(self, _sidebar) -> None:
        self._content_page.set_title("Biblioteca")
        self._content_stack.set_visible_child_name("library")
        database.set_state("last_view", "library")

    def _on_folders_selected(self, _sidebar) -> None:
        self._content_page.set_title("Carpetas")
        self._content_stack.set_visible_child_name("folders")
        database.set_state("last_view", "folders")

    def _on_albums_selected(self, _sidebar) -> None:
        self._content_page.set_title("Álbumes")
        self._content_stack.set_visible_child_name("albums")
        database.set_state("last_view", "albums")

    def _on_sources_selected(self, _sidebar) -> None:
        self._content_page.set_title("Fuentes de Google Drive")
        self._content_stack.set_visible_child_name("sources")
        self._sources_view.refresh_sources(database.list_sources())
        database.set_state("last_view", "sources")

    def _on_radios_selected(self, _sidebar) -> None:
        self._content_page.set_title("Radios")
        self._content_stack.set_visible_child_name("radios")
        database.set_state("last_view", "radios")
        self._refresh_radiotunes_view()

    def _on_spotify_selected(self, _sidebar) -> None:
        self._content_page.set_title("Spotify")
        self._content_stack.set_visible_child_name("spotify")
        database.set_state("last_view", "spotify")
        self._refresh_spotify_view()

    def _on_mood_selected(self, _sidebar) -> None:
        self._content_page.set_title("Ánimo")
        self._content_stack.set_visible_child_name("mood")
        database.set_state("last_view", "mood")

    def _on_cloud_selected(self, _sidebar) -> None:
        self._content_page.set_title("Cuenta / Sync")
        self._content_stack.set_visible_child_name("cloud")
        database.set_state("last_view", "cloud")

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
        database.set_state("last_view", f"playlist:{playlist_id}")

    def _on_new_playlist_requested(self, _sidebar) -> None:
        def on_confirm(name: str) -> None:
            database.create_playlist(name)
            self._sidebar.refresh_playlists(database.list_playlists())

        prompt_text(self, "Nombre de la nueva playlist", on_confirm)

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

    def _on_folder_track_activated(self, _view, track_id: int) -> None:
        tracks = self._folder_view.get_visible_tracks()
        self._play_from_track_list(tracks, track_id)

    def _on_folder_scan_requested(self, _view, source_id: int, folder_path: str) -> None:
        self._sync_controller.start_metadata_scan(source_id, folder_path)

    def _on_station_activated(self, _view, station: Station) -> None:
        self._playback_bar.play_station(station)

    def _on_radiotunes_key_save_requested(self, _view, key: str) -> None:
        radiotunes_source.save_listen_key(key)
        self._stations_view.set_radiotunes_configured(True)
        self._refresh_radiotunes_view()

    def _refresh_radiotunes_view(self) -> None:
        configured = radiotunes_source.is_configured()
        self._stations_view.set_radiotunes_configured(configured)
        if not configured:
            return
        self._stations_view.show_radiotunes_loading()

        def worker() -> None:
            try:
                stations = radiotunes_source.list_stations()
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                GLib.idle_add(self._toast, f"No se pudo cargar el catálogo de RadioTunes: {exc}")
                stations = []
            GLib.idle_add(self._stations_view.show_radiotunes_channels, stations)

        threading.Thread(target=worker, daemon=True).start()

    def _on_album_activated(self, _view, album_id: int) -> None:
        tracks = [LibraryTrackObject(row) for row in database.list_album_tracks(album_id)]
        if tracks:
            self._play_from_track_list(tracks, tracks[0].track_id)

    # --- Álbumes -----------------------------------------------------------

    def _on_add_to_album_requested(self, _view, track_ids) -> None:
        # Clic derecho en UNA canción suma también el resto de su álbum si está en la misma
        # carpeta (lo normal), no solo esa pista puntual.
        expanded: set[int] = set()
        for track_id in track_ids:
            expanded.update(t["id"] for t in database.list_folder_siblings_by_album(track_id))
        self._add_tracks_to_album_by_metadata(list(expanded))

    def _on_add_folder_to_album_requested(self, _view, source_id: int, path: str) -> None:
        tracks = database.list_tracks_in_folder_recursive(source_id, path)
        if not tracks:
            self._toast("Esa carpeta no tiene canciones para agregar.")
            return
        self._add_tracks_to_album_by_metadata([t["id"] for t in tracks])

    def _add_tracks_to_album_by_metadata(self, track_ids: list[int]) -> None:
        """El nombre (y artista) del álbum sale de la etiqueta `album` de cada canción — no se
        le pregunta nada al usuario. Si las canciones traen álbumes distintos (p. ej. una
        carpeta con varios discos de álbumes distintos), cada una va al álbum que le corresponde
        según su propia etiqueta."""
        if not track_ids:
            return

        groups: dict[tuple[str, str | None], list[int]] = {}
        for track_id in track_ids:
            track = database.get_track(track_id)
            if track is None:
                continue
            name = track["album"] or _folder_name(track["drive_folder_path"]) or "Álbum desconocido"
            artist = track["album_artist"] or track["artist"]
            groups.setdefault((name, artist), []).append(track_id)

        if not groups:
            return

        total_added = 0
        for (name, artist), ids in groups.items():
            album_id = database.get_or_create_album(name, artist)
            total_added += database.add_tracks_to_album(album_id, ids)

        self._albums_view.refresh(database.list_albums())
        cancion_palabra = "canción" if total_added == 1 else "canciones"
        if len(groups) == 1:
            album_name = next(iter(groups))[0]
            self._toast(f'{total_added} {cancion_palabra} agregadas a "{album_name}".')
        else:
            self._toast(f"{total_added} {cancion_palabra} agregadas a {len(groups)} álbumes.")

    def _on_album_rescan_requested(self, _view, album_id: int) -> None:
        """Vuelve a mirar la(s) carpeta(s) de donde salieron las canciones de este álbum, por si
        se agregaron canciones nuevas con la misma etiqueta de álbum desde la última vez."""
        album = database.get_album(album_id)
        if album is None:
            return
        existing_tracks = database.list_album_tracks(album_id)
        existing_ids = {t["id"] for t in existing_tracks}
        folders = {(t["source_id"], t["drive_folder_path"]) for t in existing_tracks}

        target_name = (album["name"] or "").strip().lower()
        new_ids = []
        for source_id, folder_path in folders:
            for track in database.list_tracks_in_folder(source_id, folder_path):
                if track["id"] in existing_ids:
                    continue
                if (track["album"] or "").strip().lower() == target_name:
                    new_ids.append(track["id"])

        if not new_ids:
            self._toast(f'No hay canciones nuevas para "{album["name"]}".')
            return

        added = database.add_tracks_to_album(album_id, new_ids)
        self._albums_view.refresh(database.list_albums())
        cancion_palabra = "canción" if added == 1 else "canciones"
        self._toast(f'Se agregaron {added} {cancion_palabra} nuevas a "{album["name"]}".')

    def _on_album_art_upload_requested(self, _view, album_id: int) -> None:
        image_filter = Gtk.FileFilter(name="Imágenes")
        image_filter.add_mime_type("image/jpeg")
        image_filter.add_mime_type("image/png")
        image_filter.add_mime_type("image/webp")
        image_filter.add_mime_type("image/gif")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(image_filter)

        dialog = Gtk.FileDialog(
            title="Elegir imagen de carátula", filters=filters, default_filter=image_filter
        )

        def on_open_finished(dlg, result) -> None:
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error:
                return  # el usuario canceló el diálogo, o no se pudo abrir
            path = gfile.get_path()
            if not path:
                return
            try:
                data = Path(path).read_bytes()
                ext = Path(path).suffix or ".jpg"
                art_path = save_album_art_bytes(data, album_id, ext)
            except OSError as exc:
                self._toast(f"No se pudo cargar la imagen: {exc}")
                return
            database.update_album_art(album_id, str(art_path))
            self._albums_view.refresh(database.list_albums())
            self._toast("Carátula guardada.")

        dialog.open(self, None, on_open_finished)

    def _on_album_art_search_requested(self, _view, album_id: int, name: str, artist: str) -> None:
        term = f"{artist} {name}" if artist else name
        self._search_album_art(album_id, name, term)

    def _search_album_art(self, album_id: int, album_label: str, term: str) -> None:
        def worker() -> None:
            try:
                candidates = cover_search.search_covers(term)
            except Exception as exc:  # noqa: BLE001 — sin conexión: se avisa y no se rompe la UI
                GLib.idle_add(self._toast, f"No se pudo buscar carátulas: {exc}")
                return
            results = []
            for candidate in candidates:
                try:
                    thumb_bytes = cover_search.download_cover(candidate.thumb_url)
                except Exception:  # noqa: BLE001 — mejor mostrar la tarjeta sin miniatura que romper el diálogo
                    thumb_bytes = None
                results.append((candidate, thumb_bytes))
            GLib.idle_add(self._show_cover_approval_dialog, album_id, album_label, term, results)

        threading.Thread(target=worker, daemon=True).start()

    def _show_cover_approval_dialog(
        self, album_id: int, album_label: str, term: str, results: list[tuple[CoverCandidate, bytes | None]]
    ) -> bool:
        open_cover_approval_dialog(
            self, album_label, term, results,
            on_approve=lambda candidate: self._save_album_art(album_id, candidate),
            on_search_again=lambda new_term: self._search_album_art(album_id, album_label, new_term),
        )
        return False

    def _save_album_art(self, album_id: int, candidate: CoverCandidate) -> None:
        def worker() -> None:
            try:
                data = cover_search.download_cover(candidate.full_url)
                ext = Path(urllib.parse.urlparse(candidate.full_url).path).suffix or ".jpg"
                path = save_album_art_bytes(data, album_id, ext)
                database.update_album_art(album_id, str(path))
            except Exception as exc:  # noqa: BLE001 — sin conexión: se avisa y no se rompe la UI
                GLib.idle_add(self._toast, f"No se pudo guardar la carátula: {exc}")
                return
            GLib.idle_add(self._on_album_art_saved)

        threading.Thread(target=worker, daemon=True).start()

    def _on_album_art_saved(self) -> bool:
        self._albums_view.refresh(database.list_albums())
        self._toast("Carátula guardada.")
        return False

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

    def _on_now_playing_changed(self, _bar, item: QueueItem) -> None:
        self._library_view.set_now_playing(item.track_id)
        self._folder_view.set_now_playing(item.track_id)
        self._playlist_view.set_now_playing(item.track_id)
        # Fase 5: cada canción de Drive que se reproduce (aunque sea sin pasar por la
        # pantalla "Ánimo" para nada) suma cobertura de análisis de a poco — así no
        # hace falta correr "Analizar biblioteca" para que el modo Ánimo empiece a
        # tener candidatos.
        if item.source == "drive" and item.local_path:
            self._mood_controller.ensure_mood(item.track_id, item.local_path, lambda _vector: None)

    # --- Playlists -------------------------------------------------------

    def _on_remove_tracks_requested(self, _view, playlist_track_ids) -> None:
        for playlist_track_id in playlist_track_ids:
            database.remove_playlist_item(playlist_track_id)
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
        self._folder_view.hide_scan_progress()
        # No usa _reload_all(): una lectura de etiquetas no cambia la estructura de carpetas,
        # así que alcanza con refrescar contenido — evita perder la carpeta que el usuario
        # tenía abierta en la vista de Carpetas.
        self._refresh_after_track_updates()
        self._toast(f"Etiquetas leídas: {updated} de {total} canciones actualizadas.")

    def _on_delete_source_requested(self, _view, source_id: int) -> None:
        database.delete_source(source_id)
        self._sources_view.refresh_sources(database.list_sources())
        self._library_view.refresh(database.list_tracks())
        self._folder_view.refresh(database.list_sources())
        self._albums_view.refresh(database.list_albums())

    def _on_sync_progress(self, _controller, stage: str, actual: int, total: int) -> None:
        self._sources_view.show_progress(stage, actual, total)
        self._folder_view.show_scan_progress(actual, total)

    def _on_sync_finished(self, _controller, total: int) -> None:
        self._sources_view.hide_progress()
        self._reload_all()
        self._toast(f"Sincronización completa: {total} canciones encontradas.")

    def _on_sync_error(self, _controller, message: str) -> None:
        self._sources_view.hide_progress()
        self._toast(f"Error al sincronizar: {message}")

    def _on_track_updated(self, _controller, _track_id: int) -> None:
        # Una o más canciones terminaron de actualizarse en segundo plano (reproducción, precarga,
        # o un escaneo de metadatos que puede disparar esta señal cientos de veces seguidas, una
        # por canción, cada una separada por el tiempo que tarda su pedido de red). Se agrupan
        # para no reconstruir toda la tabla de la biblioteca por cada una.
        #
        # Importante: esto es un throttle (como mucho un refresco cada 400ms), no un debounce que
        # reinicia el plazo en cada señal — si las canciones tardan más de 400ms en llegar (lo
        # normal en un escaneo real, por la red), un debounce clásico dispara un refresco COMPLETO
        # por cada una, y ahí es donde colgaba la ventana.
        if self._track_updated_source_id is not None:
            return  # ya hay un refresco encolado; va a recoger este cambio también
        self._track_updated_source_id = GLib.timeout_add(400, self._refresh_after_track_updates)

    def _refresh_after_track_updates(self) -> bool:
        self._track_updated_source_id = None
        self._library_view.refresh(database.list_tracks(filter_text=self._current_search_text))
        self._folder_view.refresh_current_folder()
        self._albums_view.refresh(database.list_albums())
        if self._current_playlist_id is not None:
            self._on_playlist_selected(self._sidebar, self._current_playlist_id)
        return False

    def _on_playback_error(self, _bar, message: str) -> None:
        self._toast(f"Error de reproducción: {message}")

    # --- Cuenta / Sync (Fase 1) --------------------------------------------

    def _refresh_cloud_settings_view(self) -> None:
        logged_in = cloud_client.is_logged_in_locally()
        email = None
        name = None
        avatar_storage_path = None
        if logged_in:
            try:
                session = cloud_client.get_client().auth.get_session()
                email = session.user.email if session else None
                metadata = session.user.user_metadata if session else {}
                name = metadata.get("full_name")
                avatar_storage_path = metadata.get("avatar_url")
            except Exception:  # noqa: BLE001 — sesión guardada corrupta/expirada
                logged_in = False
        self._cloud_settings_view.set_logged_in(logged_in, email, name)
        if logged_in and avatar_storage_path:
            self._load_connected_avatar(avatar_storage_path)

    def _load_connected_avatar(self, storage_path: str) -> None:
        def worker() -> None:
            data = cloud_client.download_avatar(storage_path)
            if data is not None:
                GLib.idle_add(self._cloud_settings_view.set_connected_avatar, data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_sign_in_requested(self, _view, email: str, password: str) -> None:
        self._do_cloud_auth(lambda: cloud_client.sign_in(email, password), email, password, signing_up=False)

    def _on_sign_up_requested(self, _view, name: str, email: str, password: str, avatar_path: str) -> None:
        self._do_cloud_auth(
            lambda: cloud_client.sign_up(email, password, name),
            email,
            password,
            signing_up=True,
            avatar_path=avatar_path or None,
        )

    def _on_avatar_upload_requested(self, _view) -> None:
        image_filter = Gtk.FileFilter(name="Imágenes")
        image_filter.add_mime_type("image/jpeg")
        image_filter.add_mime_type("image/png")
        image_filter.add_mime_type("image/webp")
        image_filter.add_mime_type("image/gif")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(image_filter)
        dialog = Gtk.FileDialog(title="Elegir foto de perfil", filters=filters, default_filter=image_filter)

        def on_open_finished(dlg, result) -> None:
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error:
                return  # el usuario canceló el diálogo
            path = gfile.get_path()
            if path:
                self._cloud_settings_view.set_avatar_photo(path)

        dialog.open(self, None, on_open_finished)

    def _do_cloud_auth(
        self, action, email: str, password: str, signing_up: bool, avatar_path: str | None = None
    ) -> None:
        def worker() -> None:
            try:
                response = action()
                if response.session is not None:
                    # La bóveda se desbloquea con la MISMA contraseña recién ingresada (nunca
                    # viaja a Supabase, ver cloud/vault.py) y trae Drive/etc. ya conectados.
                    cloud_vault.sync_after_login(password, email)
                    if avatar_path:
                        try:
                            cloud_client.upload_avatar(avatar_path)
                        except Exception as exc:  # noqa: BLE001 — la foto es opcional
                            GLib.idle_add(
                                self._toast, f"Cuenta creada, pero no se pudo subir la foto: {exc}"
                            )
                    GLib.idle_add(self._on_cloud_signed_in, signing_up)
                else:
                    # Proyecto Supabase con "Confirm email" activo: la cuenta se crea pero
                    # no hay sesión hasta que el usuario confirme desde su correo (la foto
                    # se sube recién en el próximo login, ya con sesión).
                    GLib.idle_add(self._on_cloud_signup_pending)
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                verb = "crear la cuenta" if signing_up else "iniciar sesión"
                GLib.idle_add(self._toast, f"No se pudo {verb}: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_cloud_signed_in(self, signing_up: bool = False) -> bool:
        self._refresh_cloud_settings_view()
        self._sources_view.set_authenticated(is_authenticated())
        self._cloud_sync_engine.start()
        self._toast("Cuenta creada — sincronizando." if signing_up else "Sesión iniciada — sincronizando.")
        return False

    def _on_cloud_signup_pending(self) -> bool:
        self._toast("Cuenta creada. Revisa tu correo para confirmarla antes de iniciar sesión.")
        return False

    def _on_sign_out_requested(self, _view) -> None:
        self._cloud_sync_engine.stop()
        cloud_client.sign_out()
        cloud_vault.lock()
        self._refresh_cloud_settings_view()

    def _on_cloud_playlists_changed(self, _engine) -> None:
        self._sidebar.refresh_playlists(database.list_playlists())
        if self._current_playlist_id is not None:
            self._on_playlist_selected(self._sidebar, self._current_playlist_id)

    def _on_cloud_albums_changed(self, _engine) -> None:
        self._albums_view.refresh(database.list_albums())

    def _on_cloud_sync_error(self, _engine, message: str) -> None:
        self._cloud_settings_view.log_event(message)

    # --- Spotify (Fase 4) --------------------------------------------------

    def _refresh_spotify_view(self) -> None:
        configured = spotify_oauth.is_client_configured()
        self._spotify_view.set_client_configured(configured)
        authenticated = configured and spotify_oauth.is_authenticated()
        self._spotify_view.set_authenticated(authenticated)
        if authenticated:
            self._refresh_spotify_devices()

    def _refresh_spotify_devices(self) -> None:
        def worker() -> None:
            try:
                devices = spotify_client.list_devices()
            except Exception:
                devices = []
            GLib.idle_add(self._spotify_view.show_devices, devices)

        threading.Thread(target=worker, daemon=True).start()

    def _on_spotify_client_id_save_requested(self, _view, client_id: str) -> None:
        spotify_oauth.save_client_id(client_id)
        self._refresh_spotify_view()

    def _on_spotify_connect_requested(self, _view) -> None:
        def worker() -> None:
            try:
                spotify_oauth.run_oauth_flow()
                GLib.idle_add(self._on_spotify_connected_success)
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                GLib.idle_add(self._toast, f"No se pudo conectar Spotify: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_spotify_connected_success(self) -> bool:
        self._refresh_spotify_view()
        self._toast("Cuenta de Spotify conectada.")
        return False

    def _on_spotify_search_requested(self, _view, query: str) -> None:
        if not query.strip():
            return

        def worker() -> None:
            try:
                results = spotify_client.search_tracks(query)
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                GLib.idle_add(self._toast, f"No se pudo buscar en Spotify: {exc}")
                return
            GLib.idle_add(self._spotify_view.show_results, results)

        threading.Thread(target=worker, daemon=True).start()

    def _on_spotify_play_requested(self, _view, track: SpotifyTrack) -> None:
        self._playback_bar.play_spotify_track(track)

    def _on_spotify_add_to_playlist_requested(self, _view, track: SpotifyTrack) -> None:
        def worker() -> None:
            try:
                spotify_client.cache_spotify_track(track)
            except Exception as exc:  # noqa: BLE001 — se reporta a la UI
                GLib.idle_add(self._toast, f"No se pudo agregar la canción: {exc}")
                return
            GLib.idle_add(self._open_spotify_playlist_picker, track)

        threading.Thread(target=worker, daemon=True).start()

    def _open_spotify_playlist_picker(self, track: SpotifyTrack) -> bool:
        def on_chosen(playlist_id: int) -> None:
            database.add_spotify_track_to_playlist(playlist_id, track.id)
            self._toast(f'"{track.title}" agregada a la playlist.')

        open_playlist_picker(self, on_chosen)
        return False

    # --- Ánimo (Fase 5) --------------------------------------------------

    def _on_analyze_library_requested(self, _view) -> None:
        self._mood_controller.analyze_library()

    def _on_mood_search_requested(self, _view, query: str) -> None:
        query = query.strip()
        self._mood_view.show_search_results(database.list_tracks(filter_text=query) if query else [])

    def _on_mood_models_download_progress(self, _controller, done: int, total: int) -> None:
        self._mood_view.show_models_download_progress(done, total)

    def _on_mood_analysis_progress(self, _controller, analyzed: int, total: int) -> None:
        self._mood_view.show_analysis_progress(analyzed, total)

    def _on_mood_analysis_finished(self, _controller, analyzed: int) -> None:
        self._mood_view.show_analysis_finished(analyzed)

    def _on_mood_error(self, _controller, message: str) -> None:
        self._toast(f"Error en el análisis de ánimo: {message}")

    def _on_play_mood_requested(self, _view, seed_ids) -> None:
        seed_ids = list(seed_ids)
        if seed_ids:
            self._ensure_mood_seeds_analyzed(seed_ids, seed_ids)

    def _ensure_mood_seeds_analyzed(self, to_check: list[int], all_seed_ids: list[int]) -> None:
        """Una semilla elegida que todavía no tiene vector de ánimo se analiza al
        toque acá — no hace falta correr "Analizar biblioteca" antes para poder
        probar el modo con un puñado de canciones."""
        for index, track_id in enumerate(to_check):
            if database.get_track_mood(track_id) is None:
                track = database.get_track(track_id)
                if track is not None and track["local_path"]:
                    self._toast("Analizando canción semilla…")
                    self._mood_controller.ensure_mood(
                        track_id,
                        track["local_path"],
                        lambda _vector, rest=to_check[index + 1 :]: self._ensure_mood_seeds_analyzed(
                            rest, all_seed_ids
                        ),
                    )
                    return
        self._play_mood_queue(all_seed_ids)

    def _play_mood_queue(self, seed_ids: list[int]) -> None:
        items = build_mood_queue(seed_ids)
        if not items:
            self._toast("No hay suficientes canciones analizadas para armar la cola.")
            return
        self._queue.set_queue(items, 0)
        self._playback_bar.play_queue_item(items[0])

import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from purrr.auth.oauth import get_credentials
from purrr.cache.manager import cache_path_for, download_file
from purrr.db import database
from purrr.drive.client import get_service
from purrr.drive.scanner import scan_folder_tree
from purrr.metadata.extractor import extract_metadata


class SyncController(GObject.Object):
    """Orquesta el listado de Drive y las descargas bajo demanda, señalizando la UI vía GLib.idle_add.

    El escaneo (`start_scan`) solo lista metadatos de Google Drive — no descarga nada, para no
    saturar el disco/ancho de banda con bibliotecas grandes. Las canciones se descargan una a la
    vez, bajo demanda, con `download_track()` (llamado al reproducir o al precargar la siguiente).
    """

    __gsignals__ = {
        "progress": (GObject.SignalFlags.RUN_FIRST, None, (str, int, int)),  # etapa, actual, total
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # total encontrado
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "track-updated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # track_id
    }

    def __init__(self):
        super().__init__()
        self._scan_thread: threading.Thread | None = None
        self._cancelled = False
        self._downloading: set[int] = set()
        self._downloading_lock = threading.Lock()

    # --- Escaneo (solo metadatos, sin descargar audio) ----------------------

    def start_scan(self, folder_id: str, display_name: str) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self._cancelled = False
        self._scan_thread = threading.Thread(
            target=self._run_scan, args=(folder_id, display_name), daemon=True
        )
        self._scan_thread.start()

    def cancel(self) -> None:
        self._cancelled = True

    def _emit_progress(self, stage: str, actual: int, total: int) -> None:
        GLib.idle_add(self.emit, "progress", stage, actual, total)

    def _run_scan(self, folder_id: str, display_name: str) -> None:
        try:
            creds = get_credentials()
            service = get_service(creds)
        except Exception as exc:  # noqa: BLE001 — se reporta a la UI, no se relanza en el hilo
            GLib.idle_add(self.emit, "error", f"No se pudo autenticar con Google: {exc}")
            return

        try:
            source_id = database.upsert_source(folder_id, display_name)

            self._emit_progress("Buscando archivos en Google Drive…", 0, 0)
            seen_ids: set[str] = set()
            total = 0
            for drive_file in scan_folder_tree(service, folder_id):
                if self._cancelled:
                    return
                total += 1
                seen_ids.add(drive_file.id)
                database.upsert_track_from_drive(source_id, drive_file)
                self._emit_progress(f"Encontrado: {drive_file.name}", total, 0)
            database.mark_missing_tracks(source_id, seen_ids)
            database.touch_source_scanned(source_id)
            GLib.idle_add(self.emit, "finished", total)
        except Exception as exc:  # noqa: BLE001 — cualquier fallo inesperado se reporta a la UI
            GLib.idle_add(self.emit, "error", str(exc))

    # --- Descarga bajo demanda (al reproducir / precargar) ------------------

    def download_track(
        self,
        track_id: int,
        on_complete: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Descarga una canción si hace falta. Evita descargas duplicadas concurrentes del mismo track."""
        with self._downloading_lock:
            if track_id in self._downloading:
                return
            self._downloading.add(track_id)

        threading.Thread(
            target=self._run_download, args=(track_id, on_complete, on_error), daemon=True
        ).start()

    def _run_download(
        self,
        track_id: int,
        on_complete: Callable[[str], None] | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        try:
            track_row = database.get_track(track_id)
            if track_row is None:
                return

            if (
                track_row["cache_status"] == "cached"
                and track_row["local_path"]
                and Path(track_row["local_path"]).exists()
            ):
                if on_complete:
                    GLib.idle_add(on_complete, track_row["local_path"])
                return

            creds = get_credentials()
            service = get_service(creds)
            dest = cache_path_for(track_row["drive_file_id"], track_row["file_name"])
            download_file(
                service,
                track_row["drive_file_id"],
                track_row["file_name"],
                track_row["drive_md5"],
                dest,
            )
            metadata = extract_metadata(dest)
            database.update_track_cache(
                track_row["drive_file_id"], local_path=str(dest), cache_status="cached"
            )
            database.update_track_metadata(track_row["drive_file_id"], metadata)
            GLib.idle_add(self.emit, "track-updated", track_id)
            if on_complete:
                GLib.idle_add(on_complete, str(dest))
        except Exception as exc:  # noqa: BLE001 — se reporta por callback, no se relanza en el hilo
            if "track_row" in locals() and track_row is not None:
                database.update_track_cache(
                    track_row["drive_file_id"], cache_status="error", cache_error=str(exc)
                )
            if on_error:
                GLib.idle_add(on_error, str(exc))
        finally:
            with self._downloading_lock:
                self._downloading.discard(track_id)

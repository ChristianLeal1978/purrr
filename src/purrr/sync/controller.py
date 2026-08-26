import threading

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
    """Orquesta escaneo+descarga+metadata en un hilo de fondo, señalizando la UI vía GLib.idle_add."""

    __gsignals__ = {
        "progress": (GObject.SignalFlags.RUN_FIRST, None, (str, int, int)),  # etapa, actual, total
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),  # total, errores
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._thread: threading.Thread | None = None
        self._cancelled = False

    def start_scan(self, folder_id: str, display_name: str) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run_scan, args=(folder_id, display_name), daemon=True
        )
        self._thread.start()

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

            pending = database.list_pending_tracks(source_id)
            errors = 0
            for i, track_row in enumerate(pending, start=1):
                if self._cancelled:
                    return
                self._emit_progress(f"Descargando {track_row['file_name']}…", i, len(pending))
                dest = cache_path_for(track_row["drive_file_id"], track_row["file_name"])
                try:
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
                except Exception as exc:  # noqa: BLE001 — se registra por track y se continúa
                    errors += 1
                    database.update_track_cache(
                        track_row["drive_file_id"], cache_status="error", cache_error=str(exc)
                    )

            database.touch_source_scanned(source_id)
            GLib.idle_add(self.emit, "finished", total, errors)
        except Exception as exc:  # noqa: BLE001 — cualquier fallo inesperado se reporta a la UI
            GLib.idle_add(self.emit, "error", str(exc))

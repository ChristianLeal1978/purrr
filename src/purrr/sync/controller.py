import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from purrr.audio import waveform as waveform_extractor
from purrr.auth.oauth import get_credentials
from purrr.cache.manager import (
    art_cache_path,
    cache_path_for,
    download_file,
    fetch_bytes,
    fetch_partial_bytes,
    save_art_bytes,
)
from purrr.db import database
from purrr.drive.client import get_service
from purrr.drive.scanner import DriveCoverFile, looks_like_cover, scan_folder_tree
from purrr.metadata.extractor import extract_embedded_art, extract_metadata, extract_partial_metadata

_PARTIAL_FETCH_SIZES = (262_144, 2_097_152, 8_388_608)  # 256 KB, 2 MB, 8 MB


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
        "metadata-scan-finished": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),  # leídos, total
    }

    def __init__(self):
        super().__init__()
        self._scan_thread: threading.Thread | None = None
        self._metadata_thread: threading.Thread | None = None
        self._cancelled = False
        self._downloading: set[int] = set()
        self._downloading_lock = threading.Lock()

    def _busy(self) -> bool:
        return (self._scan_thread is not None and self._scan_thread.is_alive()) or (
            self._metadata_thread is not None and self._metadata_thread.is_alive()
        )

    # --- Escaneo (solo metadatos, sin descargar audio) ----------------------

    def start_scan(self, folder_id: str, display_name: str) -> None:
        if self._busy():
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
            folder_covers: dict[str, tuple[str, str]] = {}
            total = 0
            for entry in scan_folder_tree(service, folder_id):
                if self._cancelled:
                    return
                if isinstance(entry, DriveCoverFile):
                    parent_id = entry.parents[0] if entry.parents else None
                    if parent_id:
                        folder_covers[parent_id] = (entry.id, Path(entry.name).suffix or ".jpg")
                    continue
                total += 1
                seen_ids.add(entry.id)
                database.upsert_track_from_drive(source_id, entry)
                self._emit_progress(f"Encontrado: {entry.name}", total, 0)
            database.mark_missing_tracks(source_id, seen_ids)
            if folder_covers:
                database.set_folder_covers(source_id, folder_covers)
            database.touch_source_scanned(source_id)
            GLib.idle_add(self.emit, "finished", total)
        except Exception as exc:  # noqa: BLE001 — cualquier fallo inesperado se reporta a la UI
            GLib.idle_add(self.emit, "error", str(exc))

    # --- Lectura de metadatos por fragmentos (sin descargar el audio completo) --

    def start_metadata_scan(self, source_id: int, folder_path: str | None = None) -> None:
        if self._busy():
            return
        self._cancelled = False
        self._metadata_thread = threading.Thread(
            target=self._run_metadata_scan, args=(source_id, folder_path), daemon=True
        )
        self._metadata_thread.start()

    def _run_metadata_scan(self, source_id: int, folder_path: str | None = None) -> None:
        try:
            creds = get_credentials()
            service = get_service(creds)
        except Exception as exc:  # noqa: BLE001 — se reporta a la UI
            GLib.idle_add(self.emit, "error", f"No se pudo autenticar con Google: {exc}")
            return

        tracks = database.list_tracks_needing_metadata(source_id, folder_path)
        total = len(tracks)
        updated = 0
        for i, track_row in enumerate(tracks, start=1):
            if self._cancelled:
                break
            self._emit_progress(f"Leyendo etiquetas: {track_row['file_name']}…", i, total)
            metadata = self._fetch_partial_metadata(service, track_row)
            got_art = self._ensure_folder_cover_art(service, track_row)
            if (metadata and metadata.has_useful_tags()) or got_art:
                if metadata and metadata.has_useful_tags():
                    database.update_track_partial_metadata(track_row["drive_file_id"], metadata)
                    updated += 1
                GLib.idle_add(self.emit, "track-updated", track_row["id"])

        GLib.idle_add(self.emit, "metadata-scan-finished", updated, total)

    def resolve_local_art(self, track_id: int, local_path: str) -> str | None:
        """Para tracks que ya estaban cacheados de antes (así que ni pasan por _run_download):
        intenta rescatar su carátula embebida al momento de reproducirlos. Solo lee el archivo
        local, sin red, así que es seguro llamarla desde el hilo de la UI."""
        track_row = database.get_track(track_id)
        if track_row is None:
            return None
        if track_row["art_path"]:
            return track_row["art_path"]
        return self._resolve_embedded_art(track_row, Path(local_path))

    def ensure_folder_cover_art(self, track_id: int, on_complete: Callable[[str | None], None]) -> None:
        """Si el track no tiene arte propio, busca (y cachea para toda la carpeta) un archivo
        tipo cover.jpg/folder.png en su misma carpeta de Drive. Hace red, así que corre en un
        hilo aparte — llamar solo cuando resolve_local_art ya no encontró nada local."""
        threading.Thread(
            target=self._ensure_folder_cover_art_thread, args=(track_id, on_complete), daemon=True
        ).start()

    def _ensure_folder_cover_art_thread(
        self, track_id: int, on_complete: Callable[[str | None], None]
    ) -> None:
        try:
            track_row = database.get_track(track_id)
            if track_row is None or track_row["art_path"]:
                GLib.idle_add(on_complete, track_row["art_path"] if track_row else None)
                return

            creds = get_credentials()
            service = get_service(creds)

            if track_row["folder_cover_file_id"] is None:
                # None = nunca se buscó todavía. "" = ya se buscó una vez y no había nada (no
                # repetir el pedido a Drive en cada reproducción de esta misma carpeta).
                cover = self._find_folder_cover_file(service, track_row["drive_parent_id"])
                if cover is None:
                    # Memorizamos que ya buscamos y no hay nada, para no repetir el pedido a
                    # Drive cada vez que se reproduzca otra canción de esta misma carpeta.
                    database.set_folder_covers(track_row["source_id"], {track_row["drive_parent_id"]: ("", "")})
                    GLib.idle_add(on_complete, None)
                    return
                cover_id, cover_ext = cover
                database.set_folder_covers(
                    track_row["source_id"], {track_row["drive_parent_id"]: (cover_id, cover_ext)}
                )
                track_row = database.get_track(track_id)

            self._ensure_folder_cover_art(service, track_row)
            refreshed = database.get_track(track_id)
            GLib.idle_add(on_complete, refreshed["art_path"] if refreshed else None)
        except Exception:  # noqa: BLE001 — sin conexión o sin permisos: mejor sin carátula que romper la UI
            GLib.idle_add(on_complete, None)

    def _find_folder_cover_file(self, service, parent_id: str | None) -> tuple[str, str] | None:
        if not parent_id:
            return None
        query = f"'{parent_id}' in parents and trashed = false and mimeType contains 'image/'"
        response = (
            service.files().list(q=query, fields="files(id, name)", pageSize=50, spaces="drive").execute(num_retries=3)
        )
        for entry in response.get("files", []):
            if looks_like_cover(entry["name"]):
                return entry["id"], Path(entry["name"]).suffix or ".jpg"
        return None

    def ensure_waveform(
        self, drive_file_id: str, local_path: str, on_complete: Callable[[list[float]], None]
    ) -> None:
        """Entrega la forma de onda de este track: al toque si ya está cacheada, o calculándola
        en un hilo aparte (decodifica el audio entero, así que no puede ir en la UI)."""
        cached = waveform_extractor.load_cached(drive_file_id)
        if cached is not None:
            on_complete(cached)
            return
        threading.Thread(
            target=self._extract_waveform_thread,
            args=(drive_file_id, local_path, on_complete),
            daemon=True,
        ).start()

    def _extract_waveform_thread(
        self, drive_file_id: str, local_path: str, on_complete: Callable[[list[float]], None]
    ) -> None:
        try:
            bars = waveform_extractor.extract_and_cache(Path(local_path), key=drive_file_id)
        except Exception:  # noqa: BLE001 — si falla el análisis, mejor una barra plana que romper la UI
            bars = []
        GLib.idle_add(on_complete, bars)

    def _resolve_embedded_art(self, track_row, local_audio_path: Path) -> str | None:
        """Solo arte embebido en el archivo de audio local — no requiere red."""
        embedded = extract_embedded_art(local_audio_path)
        if not embedded:
            return None
        data, mime = embedded
        art_path = save_art_bytes(data, mime, key=track_row["drive_file_id"])
        database.update_track_art(track_row["drive_file_id"], str(art_path))
        return str(art_path)

    def _resolve_art(self, service, track_row, local_audio_path: Path) -> str | None:
        """Tras descargar el audio completo: intenta arte embebido, si no hay usa el de la carpeta."""
        embedded_art_path = self._resolve_embedded_art(track_row, local_audio_path)
        if embedded_art_path:
            return embedded_art_path

        if track_row["art_path"]:
            return track_row["art_path"]

        if track_row["folder_cover_file_id"]:
            self._ensure_folder_cover_art(service, track_row)
            refreshed = database.get_track(track_row["id"])
            return refreshed["art_path"] if refreshed else None

        return None

    def _ensure_folder_cover_art(self, service, track_row) -> bool:
        """Si el track ya sabe que su carpeta tiene cover.jpg pero todavía no lo cacheamos, lo baja
        (es una imagen chica, no la canción). Devuelve True si dejó un art_path nuevo."""
        if track_row["art_path"] or not track_row["folder_cover_file_id"]:
            return False
        art_path = art_cache_path(track_row["folder_cover_file_id"], track_row["folder_cover_ext"])
        if not art_path.exists():
            try:
                data = fetch_bytes(service, track_row["folder_cover_file_id"])
                art_path.parent.mkdir(parents=True, exist_ok=True)
                art_path.write_bytes(data)
            except Exception:
                return False
        database.update_track_art(track_row["drive_file_id"], str(art_path))
        return True

    def _fetch_partial_metadata(self, service, track_row):
        last_result = None
        for size in _PARTIAL_FETCH_SIZES:
            try:
                data = fetch_partial_bytes(service, track_row["drive_file_id"], size)
            except Exception:
                return last_result
            metadata = extract_partial_metadata(data, track_row["file_name"])
            if metadata is not None:
                last_result = metadata
                if metadata.has_useful_tags():
                    return metadata
            if len(data) < size:
                break  # ya bajamos el archivo completo, no tiene caso pedir más
        return last_result

    # --- Descarga bajo demanda (al reproducir / precargar) ------------------

    def download_track(
        self,
        track_id: int,
        on_complete: Callable[[str, str | None], None] | None = None,
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
        on_complete: Callable[[str, str | None], None] | None,
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
                art_path = track_row["art_path"]
                if not art_path:
                    # Tracks cacheados antes de que existiera la extracción de carátula nunca
                    # la recibieron — la resolvemos ahora, sin red, para no dejarla en blanco.
                    art_path = self._resolve_embedded_art(track_row, Path(track_row["local_path"]))
                if on_complete:
                    GLib.idle_add(on_complete, track_row["local_path"], art_path)
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

            art_path = self._resolve_art(service, track_row, dest)

            GLib.idle_add(self.emit, "track-updated", track_id)
            if on_complete:
                GLib.idle_add(on_complete, str(dest), art_path)
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

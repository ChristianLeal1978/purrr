import hashlib
import os
from collections.abc import Callable
from pathlib import Path

from googleapiclient.discovery import Resource
from googleapiclient.http import MediaIoBaseDownload

from purrr.config import ALBUM_ART_CACHE_DIR, ART_CACHE_DIR, AUDIO_CACHE_DIR
from purrr.drive.scanner import DriveFile

_MIME_TO_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}


def cache_path_for(drive_file_id: str, file_name: str) -> Path:
    ext = Path(file_name).suffix or ".bin"
    return AUDIO_CACHE_DIR / f"{drive_file_id}{ext}"


def art_cache_path(key: str, ext: str) -> Path:
    return ART_CACHE_DIR / f"{key}{ext or '.jpg'}"


def save_art_bytes(data: bytes, mime: str, key: str) -> Path:
    path = art_cache_path(key, _MIME_TO_EXT.get(mime, ".jpg"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def save_album_art_bytes(data: bytes, album_id: int, ext: str = ".jpg") -> Path:
    """Guarda en una carpeta local la carátula que el usuario aprobó buscar en internet para
    un álbum armado a mano (ver purrr.metadata.cover_search)."""
    path = ALBUM_ART_CACHE_DIR / f"{album_id}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def fetch_bytes(service: Resource, file_id: str) -> bytes:
    """Descarga un archivo completo de una sola vez (para archivos chicos, como carátulas)."""
    return service.files().get_media(fileId=file_id).execute(num_retries=3)


def is_cached_and_current(drive_file: DriveFile, track_row) -> bool:
    if track_row is None or track_row["cache_status"] != "cached":
        return False
    if not track_row["local_path"] or not Path(track_row["local_path"]).exists():
        return False
    if track_row["drive_md5"] != drive_file.md5_checksum:
        return False
    if track_row["drive_modified_time"] != drive_file.modified_time:
        return False
    return True


def _local_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(
    service: Resource,
    file_id: str,
    file_name: str,
    expected_md5: str | None,
    dest: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Descarga a un archivo temporal .part y lo mueve atómicamente sobre dest al terminar."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".part")

    request = service.files().get_media(fileId=file_id)
    with tmp_path.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk(num_retries=5)
            if status and on_progress:
                on_progress(int(status.resumable_progress), int(status.total_size or 0))

    if expected_md5 and _local_md5(tmp_path) != expected_md5:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"MD5 no coincide tras descargar {file_name}")

    os.replace(tmp_path, dest)
    return dest


def fetch_partial_bytes(service: Resource, file_id: str, byte_count: int) -> bytes:
    """Baja solo los primeros `byte_count` bytes de un archivo (para leer etiquetas sin
    descargarlo completo). Usa un header Range crudo, no el downloader por chunks."""
    request = service.files().get_media(fileId=file_id)
    request.headers["Range"] = f"bytes=0-{byte_count - 1}"
    return request.execute(num_retries=3)

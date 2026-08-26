import sqlite3
import threading
from importlib import resources

from purrr.config import DB_PATH
from purrr.drive.scanner import DriveFile
from purrr.metadata.extractor import TrackMetadata

_local = threading.local()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_connection() -> sqlite3.Connection:
    """Devuelve una conexión propia del hilo actual (SQLite no es segura entre hilos)."""
    if not hasattr(_local, "conn"):
        _local.conn = _connect()
    return _local.conn


def init_db() -> None:
    schema = resources.files("purrr.db").joinpath("schema.sql").read_text()
    get_connection().executescript(schema)


# --- Sources -----------------------------------------------------------

def upsert_source(drive_folder_id: str, display_name: str) -> int:
    conn = get_connection()
    conn.execute(
        "INSERT INTO sources (drive_folder_id, display_name) VALUES (?, ?) "
        "ON CONFLICT(drive_folder_id) DO UPDATE SET display_name = excluded.display_name",
        (drive_folder_id, display_name),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM sources WHERE drive_folder_id = ?", (drive_folder_id,)
    ).fetchone()
    return row["id"]


def touch_source_scanned(source_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE sources SET last_scanned_at = datetime('now') WHERE id = ?", (source_id,)
    )
    conn.commit()


def list_sources() -> list[sqlite3.Row]:
    return get_connection().execute("SELECT * FROM sources ORDER BY display_name").fetchall()


def delete_source(source_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()


# --- Tracks --------------------------------------------------------------

def upsert_track_from_drive(source_id: int, drive_file: DriveFile) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO tracks (
            drive_file_id, source_id, drive_parent_id, drive_folder_path,
            file_name, mime_type, drive_md5, drive_modified_time, drive_size_bytes,
            cache_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
        ON CONFLICT(drive_file_id) DO UPDATE SET
            drive_parent_id = excluded.drive_parent_id,
            drive_folder_path = excluded.drive_folder_path,
            file_name = excluded.file_name,
            mime_type = excluded.mime_type,
            drive_md5 = excluded.drive_md5,
            drive_modified_time = excluded.drive_modified_time,
            drive_size_bytes = excluded.drive_size_bytes,
            cache_status = CASE
                WHEN tracks.drive_md5 IS NOT excluded.drive_md5 THEN 'pending'
                ELSE tracks.cache_status
            END,
            updated_at = datetime('now')
        """,
        (
            drive_file.id,
            source_id,
            drive_file.parents[0] if drive_file.parents else None,
            drive_file.folder_path,
            drive_file.name,
            drive_file.mime_type,
            drive_file.md5_checksum,
            drive_file.modified_time,
            drive_file.size,
        ),
    )
    conn.commit()


def get_track_by_drive_id(drive_file_id: str) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM tracks WHERE drive_file_id = ?", (drive_file_id,)
    ).fetchone()


def list_pending_tracks(source_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        "SELECT * FROM tracks WHERE source_id = ? AND cache_status IN ('pending', 'error') "
        "ORDER BY file_name",
        (source_id,),
    ).fetchall()


def update_track_cache(
    drive_file_id: str,
    *,
    local_path: str | None = None,
    cache_status: str,
    cache_error: str | None = None,
) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE tracks SET local_path = ?, cache_status = ?, cache_error = ?, "
        "updated_at = datetime('now') WHERE drive_file_id = ?",
        (local_path, cache_status, cache_error, drive_file_id),
    )
    conn.commit()


def update_track_metadata(drive_file_id: str, metadata: TrackMetadata) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE tracks SET
            title = ?, artist = ?, album = ?, album_artist = ?,
            track_number = ?, disc_number = ?, year = ?, genre = ?,
            duration_seconds = ?, updated_at = datetime('now')
        WHERE drive_file_id = ?
        """,
        (
            metadata.title,
            metadata.artist,
            metadata.album,
            metadata.album_artist,
            metadata.track_number,
            metadata.disc_number,
            metadata.year,
            metadata.genre,
            metadata.duration_seconds,
            drive_file_id,
        ),
    )
    conn.commit()


def mark_missing_tracks(source_id: int, seen_drive_file_ids: set[str]) -> None:
    conn = get_connection()
    placeholders = ",".join("?" * len(seen_drive_file_ids)) if seen_drive_file_ids else "''"
    conn.execute(
        f"UPDATE tracks SET cache_status = 'missing', updated_at = datetime('now') "
        f"WHERE source_id = ? AND drive_file_id NOT IN ({placeholders})",
        (source_id, *seen_drive_file_ids),
    )
    conn.commit()


def list_tracks(filter_text: str | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    if filter_text:
        like = f"%{filter_text}%"
        return conn.execute(
            "SELECT * FROM tracks WHERE cache_status != 'missing' AND "
            "(title LIKE ? OR artist LIKE ? OR album LIKE ?) "
            "ORDER BY artist, album, disc_number, track_number, title",
            (like, like, like),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM tracks WHERE cache_status != 'missing' "
        "ORDER BY artist, album, disc_number, track_number, title"
    ).fetchall()


def get_track(track_id: int) -> sqlite3.Row | None:
    return get_connection().execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()


# --- Playlists -------------------------------------------------------------

def create_playlist(name: str) -> int:
    conn = get_connection()
    cursor = conn.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
    conn.commit()
    return cursor.lastrowid


def rename_playlist(playlist_id: int, name: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE playlists SET name = ?, updated_at = datetime('now') WHERE id = ?",
        (name, playlist_id),
    )
    conn.commit()


def delete_playlist(playlist_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    conn.commit()


def list_playlists() -> list[sqlite3.Row]:
    return get_connection().execute("SELECT * FROM playlists ORDER BY name").fetchall()


def list_playlist_tracks(playlist_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        """
        SELECT tracks.*, playlist_tracks.position AS playlist_position,
               playlist_tracks.id AS playlist_track_id
        FROM playlist_tracks
        JOIN tracks ON tracks.id = playlist_tracks.track_id
        WHERE playlist_tracks.playlist_id = ?
        ORDER BY playlist_tracks.position
        """,
        (playlist_id,),
    ).fetchall()


def add_track_to_playlist(playlist_id: int, track_id: int) -> None:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM playlist_tracks "
        "WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
        (playlist_id, track_id, row["next_pos"]),
    )
    conn.commit()


def remove_playlist_track(playlist_track_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM playlist_tracks WHERE id = ?", (playlist_track_id,))
    conn.commit()


def reorder_playlist_tracks(playlist_id: int, playlist_track_ids_in_order: list[int]) -> None:
    conn = get_connection()
    # Desplazar a posiciones negativas temporales para esquivar el UNIQUE(playlist_id, position).
    for offset, playlist_track_id in enumerate(playlist_track_ids_in_order):
        conn.execute(
            "UPDATE playlist_tracks SET position = ? WHERE id = ? AND playlist_id = ?",
            (-(offset + 1), playlist_track_id, playlist_id),
        )
    for position, playlist_track_id in enumerate(playlist_track_ids_in_order):
        conn.execute(
            "UPDATE playlist_tracks SET position = ? WHERE id = ? AND playlist_id = ?",
            (position, playlist_track_id, playlist_id),
        )
    conn.commit()


# --- App state ---------------------------------------------------------

def get_state(key: str, default: str | None = None) -> str | None:
    row = get_connection().execute(
        "SELECT value FROM app_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()

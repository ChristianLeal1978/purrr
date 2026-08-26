#!/usr/bin/env python3
"""Prueba manual de extremo a extremo: autenticación, escaneo, descarga, metadata y SQLite.

Uso:
    .venv/bin/python scripts/console_scan.py <folder-id-o-link-de-drive>

Requiere que ~/.config/purrr/client_secret.json exista (ver README.md).
"""

import sys

from purrr.auth.oauth import get_credentials
from purrr.cache.manager import cache_path_for, download_file
from purrr.config import ensure_dirs
from purrr.db import database
from purrr.drive.client import get_service, parse_folder_id_or_link
from purrr.drive.scanner import scan_folder_tree
from purrr.metadata.extractor import extract_metadata


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <folder-id-o-link-de-drive>", file=sys.stderr)
        return 1

    ensure_dirs()
    database.init_db()

    folder_id = parse_folder_id_or_link(sys.argv[1])

    print("Autenticando con Google...")
    creds = get_credentials()
    service = get_service(creds)

    source_id = database.upsert_source(folder_id, folder_id)

    print(f"Pase 1/2 — listando árbol de la carpeta {folder_id}...")
    seen_ids: set[str] = set()
    total = 0
    for drive_file in scan_folder_tree(service, folder_id):
        total += 1
        seen_ids.add(drive_file.id)
        database.upsert_track_from_drive(source_id, drive_file)
        print(f"  [{total}] {drive_file.folder_path}/{drive_file.name}")
    database.mark_missing_tracks(source_id, seen_ids)
    print(f"Listado completo: {total} archivos de audio encontrados.\n")

    print("Pase 2/2 — descargando y extrayendo metadata de los pendientes...")
    pending = database.list_pending_tracks(source_id)
    for i, track_row in enumerate(pending, start=1):
        dest = cache_path_for(track_row["drive_file_id"], track_row["file_name"])
        print(f"  [{i}/{len(pending)}] {track_row['file_name']}...", end=" ", flush=True)
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
            print(f"OK ({metadata.artist or '?'} - {metadata.title})")
        except Exception as exc:  # noqa: BLE001 — script de prueba, se reporta y continúa
            database.update_track_cache(
                track_row["drive_file_id"], cache_status="error", cache_error=str(exc)
            )
            print(f"ERROR: {exc}")

    database.touch_source_scanned(source_id)
    print("\nListo. Verifica con:")
    print('  sqlite3 ~/.local/share/purrr/purrr.db "SELECT title, artist, album FROM tracks;"')
    return 0


if __name__ == "__main__":
    sys.exit(main())

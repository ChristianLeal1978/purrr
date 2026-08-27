import re
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from googleapiclient.discovery import Resource

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_ENTRY_QUERY = (
    "'{folder_id}' in parents and trashed = false and "
    "(mimeType = '{folder_mime}' or fileExtension = 'mp3' or fileExtension = 'flac' "
    "or mimeType contains 'image/')"
)
_FIELDS = "nextPageToken, files(id, name, mimeType, parents, md5Checksum, modifiedTime, size)"
_PAGE_SIZE = 1000
_COVER_NAME_PATTERN = re.compile(r"(?i)^(cover|folder|albumart|front)\.(jpe?g|png)$")


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    md5_checksum: str | None
    modified_time: str
    size: int | None
    folder_path: str


@dataclass
class DriveCoverFile:
    """Una imagen de carátula de carpeta (cover.jpg, folder.png, etc.), no una canción."""

    id: str
    name: str
    parents: list[str]


def looks_like_cover(name: str) -> bool:
    return bool(_COVER_NAME_PATTERN.match(name))


def _list_children(service: Resource, folder_id: str) -> Iterator[dict]:
    page_token = None
    query = _ENTRY_QUERY.format(folder_id=folder_id, folder_mime=FOLDER_MIME_TYPE)
    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields=_FIELDS,
                pageSize=_PAGE_SIZE,
                pageToken=page_token,
                spaces="drive",
            )
            .execute(num_retries=5)
        )
        yield from response.get("files", [])
        page_token = response.get("nextPageToken")
        if not page_token:
            return


def scan_folder_tree(
    service: Resource,
    root_folder_id: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> Iterator[DriveFile | DriveCoverFile]:
    """Recorre recursivamente (BFS) una carpeta de Drive.

    Produce los archivos .mp3/.flac encontrados (`DriveFile`) y, cuando detecta una imagen de
    carátula (cover.jpg, folder.png, etc.) en una carpeta, también un `DriveCoverFile` — el
    llamador decide qué hacer con cada tipo.
    """
    queue: deque[tuple[str, str]] = deque([(root_folder_id, "")])
    visited: set[str] = {root_folder_id}
    files_found = 0

    while queue:
        folder_id, folder_path = queue.popleft()
        for item in _list_children(service, folder_id):
            if item["mimeType"] == FOLDER_MIME_TYPE:
                if item["id"] in visited:
                    continue
                visited.add(item["id"])
                queue.append((item["id"], f"{folder_path}/{item['name']}"))
                continue

            if item["mimeType"].startswith("image/"):
                if looks_like_cover(item["name"]):
                    yield DriveCoverFile(
                        id=item["id"], name=item["name"], parents=item.get("parents", [])
                    )
                continue

            if Path(item["name"]).suffix.lower() not in (".mp3", ".flac"):
                continue

            files_found += 1
            drive_file = DriveFile(
                id=item["id"],
                name=item["name"],
                mime_type=item["mimeType"],
                parents=item.get("parents", []),
                md5_checksum=item.get("md5Checksum"),
                modified_time=item["modifiedTime"],
                size=int(item["size"]) if item.get("size") else None,
                folder_path=folder_path or "/",
            )
            if on_progress:
                on_progress(files_found, drive_file.name)
            yield drive_file

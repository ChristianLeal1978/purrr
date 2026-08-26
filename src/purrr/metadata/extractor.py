import re
from dataclasses import dataclass
from pathlib import Path

import mutagen


@dataclass
class TrackMetadata:
    title: str
    artist: str | None
    album: str | None
    album_artist: str | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None
    duration_seconds: float


def _first(tags, key: str) -> str | None:
    if tags is None:
        return None
    values = tags.get(key)
    return values[0] if values else None


def _leading_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"\d+", value)
    return int(match.group()) if match else None


def extract_metadata(path: Path) -> TrackMetadata:
    audio = mutagen.File(path, easy=True)
    duration = audio.info.length if audio is not None and audio.info else 0.0
    tags = audio if audio is not None else None

    title = _first(tags, "title") or path.stem
    track_number = _leading_int(_first(tags, "tracknumber"))
    disc_number = _leading_int(_first(tags, "discnumber"))
    year = _leading_int(_first(tags, "date"))

    return TrackMetadata(
        title=title,
        artist=_first(tags, "artist"),
        album=_first(tags, "album"),
        album_artist=_first(tags, "albumartist"),
        track_number=track_number,
        disc_number=disc_number,
        year=year,
        genre=_first(tags, "genre"),
        duration_seconds=duration,
    )

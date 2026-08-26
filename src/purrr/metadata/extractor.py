import io
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


@dataclass
class PartialMetadata:
    """Etiquetas leídas de solo los primeros bytes de un archivo (sin descargarlo completo).

    `duration_seconds` queda en None salvo para FLAC (su duración está en el bloque STREAMINFO,
    siempre al inicio del archivo, así que sale exacta sin necesitar el resto de los datos). Para
    MP3 no se intenta estimar duración a partir de un buffer truncado: saldría mal para variable
    bitrate sin cabecera Xing/LAME, así que se deja para cuando la canción se descargue completa.
    """

    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None
    duration_seconds: float | None

    def has_useful_tags(self) -> bool:
        return bool(self.title or self.artist or self.album)


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


def extract_embedded_art(path: Path) -> tuple[bytes, str] | None:
    """Devuelve (bytes_de_la_imagen, mime) si el archivo trae carátula embebida, o None."""
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3

            pics = ID3(path).getall("APIC")
            if pics:
                return pics[0].data, pics[0].mime
        elif ext == ".flac":
            from mutagen.flac import FLAC

            pictures = FLAC(path).pictures
            if pictures:
                return pictures[0].data, pictures[0].mime
    except Exception:
        pass
    return None


def extract_partial_metadata(data: bytes, file_name: str) -> PartialMetadata | None:
    """Intenta leer etiquetas de un fragmento inicial del archivo (p.ej. el primer MB).

    Devuelve None si el formato no está soportado para lectura parcial o si el fragmento
    no alcanzó a incluir el bloque de etiquetas (el llamador puede reintentar con más bytes).
    """
    ext = Path(file_name).suffix.lower()
    buf = io.BytesIO(data)
    tags = None
    duration = None

    try:
        if ext == ".mp3":
            from mutagen.easyid3 import EasyID3

            tags = EasyID3(buf)
        elif ext == ".flac":
            from mutagen.flac import FLAC

            audio = FLAC(buf)
            tags = audio
            duration = audio.info.length
        else:
            return None
    except Exception:
        return None

    return PartialMetadata(
        title=_first(tags, "title"),
        artist=_first(tags, "artist"),
        album=_first(tags, "album"),
        album_artist=_first(tags, "albumartist"),
        track_number=_leading_int(_first(tags, "tracknumber")),
        disc_number=_leading_int(_first(tags, "discnumber")),
        year=_leading_int(_first(tags, "date")),
        genre=_first(tags, "genre"),
        duration_seconds=duration,
    )

from dataclasses import dataclass


@dataclass(frozen=True)
class SpotifyTrack:
    id: str
    title: str
    artist: str | None
    album: str | None
    duration_seconds: float | None
    art_url: str | None
    uri: str  # 'spotify:track:<id>' — lo que se manda a la Connect API

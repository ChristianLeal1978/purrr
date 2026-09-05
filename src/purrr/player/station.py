from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    """Una señal de radio en vivo — a diferencia de un `QueueItem`, no tiene archivo
    que descargar, ni duración, ni orden dentro de una cola (ver `player/sources/`)."""

    provider: str  # 'rainwave' | 'biobio'
    slug: str
    display_name: str
    stream_url: str
    subtitle: str | None = None  # género o frecuencia, para mostrar en la fila de la UI
    art_url: str | None = None  # carátula del canal (por ahora solo RadioTunes la trae)

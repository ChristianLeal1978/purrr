"""Resuelve una URL `.pls` (formato playlist de Winamp/Shoutcast, usado por
RadioTunes) a la URL de stream real — confirmado con `gst-launch-1.0` que
`playbin` no lo hace solo ("decodebin cannot decode plain text files"), así que
`ui/playback_bar.py` tiene que bajarlo y parsearlo antes de reproducir.

Formato típico:
    [playlist]
    NumberOfEntries=2
    File1=http://prem1.radiotunes.com:80/00scountry_hi
    Title1=RadioTunes - 00s Country
    File2=http://prem4.radiotunes.com:80/00scountry_hi
    ...
"""

import urllib.parse
import urllib.request

_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"


def is_pls_url(url: str) -> bool:
    return urllib.parse.urlparse(url).path.endswith(".pls")


def resolve_pls_url(url: str, timeout: int = 10) -> str:
    """Devuelve la primera URL de stream (`File1=`) del `.pls`. Lanza `ValueError`
    si el archivo no tiene ninguna entrada — mejor un error visible en la UI que un
    intento de reproducir un texto vacío en silencio."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")

    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("file1="):
            return line.split("=", 1)[1].strip()

    raise ValueError(f"El archivo .pls no tiene ninguna entrada de stream: {url}")

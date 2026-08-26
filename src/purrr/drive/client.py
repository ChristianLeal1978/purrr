import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

_FOLDER_ID_PATTERNS = [
    re.compile(r"/folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
]


def get_service(creds: Credentials) -> Resource:
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def parse_folder_id_or_link(text: str) -> str:
    """Acepta un folder ID crudo o un link de Google Drive y devuelve el folder ID."""
    text = text.strip()
    for pattern in _FOLDER_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return text

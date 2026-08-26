import os

from google.oauth2.credentials import Credentials

from purrr.config import DRIVE_SCOPES, TOKEN_PATH


def save_token(creds: Credentials) -> None:
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)


def load_token() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None
    return Credentials.from_authorized_user_file(str(TOKEN_PATH), DRIVE_SCOPES)


def delete_token() -> None:
    TOKEN_PATH.unlink(missing_ok=True)

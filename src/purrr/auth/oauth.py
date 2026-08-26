from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from purrr.config import CLIENT_SECRET_PATH, DRIVE_SCOPES
from purrr.auth.token_store import delete_token, load_token, save_token


class MissingClientSecretError(RuntimeError):
    """El usuario todavía no colocó su client_secret.json de Google Cloud Console."""


def run_oauth_flow() -> Credentials:
    if not CLIENT_SECRET_PATH.exists():
        raise MissingClientSecretError(
            f"No se encontró {CLIENT_SECRET_PATH}. Crea un OAuth Client ID tipo "
            "'Desktop app' en Google Cloud Console y guarda el JSON descargado ahí."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), DRIVE_SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(creds)
    return creds


def get_credentials() -> Credentials:
    creds = load_token()
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(creds)
        return creds
    return run_oauth_flow()


def is_authenticated() -> bool:
    creds = load_token()
    return bool(creds and (creds.valid or (creds.expired and creds.refresh_token)))


def revoke() -> None:
    delete_token()

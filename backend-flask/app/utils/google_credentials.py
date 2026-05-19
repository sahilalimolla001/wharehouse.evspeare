import base64
import json
from binascii import Error as Base64Error
from pathlib import Path


MISSING_GOOGLE_CREDENTIALS_MESSAGE = (
    "Google credentials are not configured. Set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file path, "
    "or set GOOGLE_APPLICATION_CREDENTIALS_JSON / GOOGLE_SERVICE_ACCOUNT_JSON to the service-account JSON."
)


def load_google_credentials(config, scopes):
    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError, GoogleAuthError
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError("Google auth packages are not installed") from error

    credentials_json = (config.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
    if credentials_json:
        return service_account.Credentials.from_service_account_info(parse_service_account_json(credentials_json), scopes=scopes)

    credentials_path = (config.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if credentials_path:
        credentials_file = Path(credentials_path).expanduser()
        if not credentials_file.is_file():
            raise RuntimeError(f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {credentials_path}")
        try:
            return service_account.Credentials.from_service_account_file(str(credentials_file), scopes=scopes)
        except Exception as error:
            raise RuntimeError(f"Could not load GOOGLE_APPLICATION_CREDENTIALS service-account file: {error}") from error

    try:
        credentials, _ = google.auth.default(scopes=scopes)
        return credentials
    except DefaultCredentialsError as error:
        raise RuntimeError(MISSING_GOOGLE_CREDENTIALS_MESSAGE) from error
    except GoogleAuthError as error:
        raise RuntimeError(f"Google credentials could not be loaded: {error}") from error


def parse_service_account_json(credentials_json):
    raw_value = credentials_json.strip()
    if raw_value.startswith("{"):
        decoded_json = raw_value
    else:
        try:
            decoded_json = base64.b64decode(raw_value, validate=True).decode("utf-8")
        except (Base64Error, UnicodeDecodeError) as error:
            raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_JSON must be service-account JSON or base64-encoded JSON") from error

    try:
        service_account_info = json.loads(decoded_json)
    except json.JSONDecodeError as error:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_JSON is not valid JSON") from error

    if not service_account_info.get("client_email") or service_account_info.get("type") != "service_account":
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_JSON must contain a Google service-account key with client_email")
    return service_account_info

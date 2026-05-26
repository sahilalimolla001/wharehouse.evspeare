import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TOKEN_CACHE_SECONDS = 9 * 24 * 60 * 60
_cached_token = None
_cached_token_until = 0


class ShiprocketError(RuntimeError):
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def is_shiprocket_configured(config):
    return bool(config.get("SHIPROCKET_TOKEN") or (config.get("SHIPROCKET_EMAIL") and config.get("SHIPROCKET_PASSWORD")))


def test_shiprocket_connection(config):
    token = get_shiprocket_token(config)
    preview = token[:8] + "..." if len(token) > 8 else "set"
    return {"ok": True, "message": "Shiprocket authentication is working.", "token_preview": preview}


def create_shiprocket_order(payload, config):
    token = get_shiprocket_token(config)
    return shiprocket_request(config, "orders/create/adhoc", payload=payload, token=token)


def create_shiprocket_return_order(payload, config):
    token = get_shiprocket_token(config)
    return shiprocket_request(config, "orders/create/return", payload=payload, token=token)


def cancel_shiprocket_order(order_ids, config):
    ids = [int(value) for value in normalize_list(order_ids) if str(value).strip().isdigit()]
    if not ids:
        raise ShiprocketError("Shiprocket order id is required for cancellation.")
    token = get_shiprocket_token(config)
    return shiprocket_request(config, "orders/cancel", payload={"ids": ids}, token=token)


def generate_shiprocket_label(shipment_ids, config):
    ids = [int(value) for value in normalize_list(shipment_ids) if str(value).strip().isdigit()]
    if not ids:
        raise ShiprocketError("Shiprocket shipment id is required to generate label.")
    token = get_shiprocket_token(config)
    return shiprocket_request(config, "courier/generate/label", payload={"shipment_id": ids}, token=token)


def normalize_list(value):
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def get_shiprocket_token(config):
    static_token = str(config.get("SHIPROCKET_TOKEN") or "").strip()
    if static_token:
        return static_token

    email = str(config.get("SHIPROCKET_EMAIL") or "").strip()
    password = str(config.get("SHIPROCKET_PASSWORD") or "").strip()
    if not email or not password:
        raise ShiprocketError("Shiprocket email/password or token is not configured.")

    global _cached_token, _cached_token_until
    now = time.time()
    if _cached_token and now < _cached_token_until:
        return _cached_token

    response = shiprocket_request(config, "auth/login", payload={"email": email, "password": password})
    token = extract_token(response)
    if not token:
        raise ShiprocketError("Shiprocket did not return an authentication token.", response=response)

    _cached_token = token
    _cached_token_until = now + TOKEN_CACHE_SECONDS
    return token


def shiprocket_request(config, endpoint, payload=None, token=None):
    base_url = str(config.get("SHIPROCKET_API_BASE_URL") or "https://apiv2.shiprocket.in/v1/external").rstrip("/")
    url = f"{base_url}/{endpoint.lstrip('/')}"
    body = json.dumps(payload or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, data=body, headers=headers, method="POST")
    timeout = int(config.get("SHIPROCKET_TIMEOUT") or 20)
    try:
        with urlopen(request, timeout=timeout) as response:
            return parse_response(response.read().decode("utf-8"))
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        parsed = parse_response(response_body, strict=False)
        message = extract_error_message(parsed) or f"Shiprocket API error {error.code}"
        raise ShiprocketError(message, status_code=error.code, response=parsed) from error
    except URLError as error:
        raise ShiprocketError(f"Shiprocket connection failed: {error.reason}") from error


def parse_response(text, strict=True):
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        if strict:
            raise ShiprocketError("Shiprocket returned a non-JSON response.") from error
        return {"raw": text}


def extract_token(response):
    if not isinstance(response, dict):
        return ""
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    return str(response.get("token") or data.get("token") or "").strip()


def extract_error_message(response):
    if isinstance(response, dict):
        for key in ("message", "error", "errors"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return "; ".join(str(item) for item in value[:3])
            if isinstance(value, dict) and value:
                return "; ".join(f"{field}: {messages}" for field, messages in list(value.items())[:3])
    return ""

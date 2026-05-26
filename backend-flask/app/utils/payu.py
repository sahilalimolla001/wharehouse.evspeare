import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app, request, url_for


class PayURefundError(RuntimeError):
    pass


def payu_refund_enabled():
    return bool(current_app.config.get("PAYU_KEY") and current_app.config.get("PAYU_SALT"))


def payu_postservice_url():
    if current_app.config.get("PAYU_ENV") == "production":
        return "https://secure.payu.in/merchant/postservice.php?form=2"
    return "https://test.payu.in/merchant/postservice.php?form=2"


def payu_command_hash(command, var1):
    key = current_app.config.get("PAYU_KEY", "")
    salt = current_app.config.get("PAYU_SALT", "")
    if not key or not salt:
        raise PayURefundError("PAYU_KEY and PAYU_SALT are required for PayU refund approval")
    raw = "|".join([key, command, str(var1 or ""), salt])
    return hashlib.sha512(raw.encode("utf-8")).hexdigest().lower()


def refund_callback_url():
    configured = current_app.config.get("PAYU_REFUND_CALLBACK_URL", "").strip()
    if configured:
        return configured
    try:
        return url_for("api.api_payu_refund_callback", _external=True)
    except RuntimeError:
        origin = request.host_url.rstrip("/") if request else ""
        return f"{origin}/api/integrations/payu/refund-callback"


def initiate_payu_refund(*, mihpayid, token, amount):
    command = "cancel_refund_transaction"
    if not mihpayid:
        raise PayURefundError("PayU mihpayid is required before refund approval")
    if not token:
        raise PayURefundError("Refund token is required")

    body = {
        "key": current_app.config.get("PAYU_KEY", ""),
        "command": command,
        "var1": str(mihpayid),
        "var2": str(token)[:23],
        "var3": f"{float(amount or 0):.2f}",
        "var5": refund_callback_url(),
        "hash": payu_command_hash(command, mihpayid),
    }
    data = urlencode(body).encode("utf-8")
    req = Request(
        payu_postservice_url(),
        data=data,
        headers={"Accept": "application/json,text/plain,*/*", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=current_app.config.get("PAYU_TIMEOUT", 20)) as response:
            text = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        raise PayURefundError(f"PayU refund API failed with {error.code}: {text[:200]}") from error
    except URLError as error:
        raise PayURefundError(f"PayU refund API failed: {error.reason}") from error

    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {"raw": text}

    if not payu_refund_accepted(payload):
        message = payload.get("msg") or payload.get("message") or payload.get("error") or str(payload)[:200]
        raise PayURefundError(f"PayU refund was not accepted: {message}")
    return payload


def payu_refund_accepted(payload):
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or payload.get("refund_status") or payload.get("request_status") or "").lower()
    message = str(payload.get("msg") or payload.get("message") or "").lower()
    return status in {"1", "success", "queued", "pending"} or "success" in message or "queued" in message

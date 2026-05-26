import base64
import hashlib
import hmac
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class RazorpayRefundError(RuntimeError):
    pass


def razorpay_refund_enabled():
    return bool(current_app.config.get("RAZORPAY_KEY_ID") and current_app.config.get("RAZORPAY_KEY_SECRET"))


def initiate_razorpay_refund(*, payment_id, receipt, amount):
    key_id = current_app.config.get("RAZORPAY_KEY_ID", "")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise RazorpayRefundError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required for Razorpay refunds")
    if not payment_id:
        raise RazorpayRefundError("Razorpay payment id is required before refund approval")

    amount_subunits = round(float(amount or 0) * 100)
    if amount_subunits <= 0:
        raise RazorpayRefundError("Refund amount must be greater than zero")

    credentials = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    body = json.dumps(
        {
            "amount": amount_subunits,
            "speed": "normal",
            "receipt": str(receipt or "")[:40],
            "notes": {"refund_request": str(receipt or "")[:256]},
        }
    ).encode("utf-8")
    req = Request(
        f"https://api.razorpay.com/v1/payments/{payment_id}/refund",
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=current_app.config.get("RAZORPAY_TIMEOUT", 20)) as response:
            text = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        raise RazorpayRefundError(f"Razorpay refund API failed with {error.code}: {text[:200]}") from error
    except URLError as error:
        raise RazorpayRefundError(f"Razorpay refund API failed: {error.reason}") from error

    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError as error:
        raise RazorpayRefundError(f"Razorpay refund API returned invalid JSON: {text[:200]}") from error

    if str(payload.get("status") or "").lower() not in {"pending", "processed"} or not payload.get("id"):
        message = payload.get("error", {}).get("description") or payload.get("message") or str(payload)[:200]
        raise RazorpayRefundError(f"Razorpay refund was not accepted: {message}")
    return payload


def verify_razorpay_webhook(raw_body, signature):
    secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))

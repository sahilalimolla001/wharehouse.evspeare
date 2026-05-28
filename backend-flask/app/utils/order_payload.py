import json


def order_source_payload(order):
    if not order or not order.source_payload:
        return {}
    try:
        payload = json.loads(order.source_payload)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def order_automation_summary(order_or_payload):
    payload = order_or_payload if isinstance(order_or_payload, dict) else order_source_payload(order_or_payload)
    if not isinstance(payload, dict):
        payload = {}

    amounts = payload.get("amounts") if isinstance(payload.get("amounts"), dict) else {}
    delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
    promotions = payload.get("promotions") if isinstance(payload.get("promotions"), dict) else {}
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}

    auto_discount = money_number(amounts.get("autoDiscount") or promotions.get("autoDiscount"))
    delivery_mode = str(delivery.get("mode") or "").lower()
    automation = str(delivery.get("automation") or "").lower()
    is_express = delivery_mode == "fast" or "express" in automation

    return {
        "is_express": is_express,
        "delivery_mode": delivery_mode or "standard",
        "delivery_label": delivery.get("label") or ("Fast delivery" if is_express else "Standard delivery"),
        "delivery_eta": delivery.get("estimatedDays") or "",
        "automation": automation,
        "auto_discount": auto_discount,
        "promo_label": promotions.get("label") or ("Auto saving" if auto_discount else ""),
        "payment_method": payment.get("method") or payload.get("paymentMethod") or "",
        "payment_status": payment.get("status") or payload.get("paymentStatus") or "",
        "total": money_number(amounts.get("total") or payload.get("amountTotal")),
    }


def is_fast_delivery_order(order_or_payload):
    return bool(order_automation_summary(order_or_payload)["is_express"])


def money_number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0

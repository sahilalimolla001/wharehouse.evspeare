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
    coupon = promotions.get("coupon") if isinstance(promotions.get("coupon"), dict) else {}
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}

    auto_discount = money_number(amounts.get("autoDiscount") or promotions.get("autoDiscount"))
    delivery_mode = clean_text(
        delivery.get("mode")
        or delivery.get("type")
        or delivery.get("speed")
        or payload.get("deliveryMode")
        or payload.get("delivery_mode")
    )
    delivery_label = str(
        delivery.get("label")
        or payload.get("deliveryLabel")
        or payload.get("delivery_label")
        or ""
    ).strip()
    automation = clean_text(
        delivery.get("automation")
        or payload.get("deliveryAutomation")
        or payload.get("delivery_automation")
    )
    delivery_text = " ".join([delivery_mode, clean_text(delivery_label), automation])
    is_express = (
        delivery_mode in {"fast", "express", "quick", "same_day", "same-day"}
        or any(token in delivery_text for token in ["fast", "express", "quick", "same day", "same-day"])
        or payload.get("fastDelivery") is True
        or payload.get("fast_delivery") is True
    )

    return {
        "is_express": is_express,
        "delivery_mode": delivery_mode or "standard",
        "delivery_label": delivery_label or ("Fast delivery" if is_express else "Standard delivery"),
        "delivery_eta": delivery.get("estimatedDays") or "",
        "automation": automation,
        "auto_discount": auto_discount,
        "coupon_code": coupon.get("code") or promotions.get("couponCode") or "",
        "coupon_discount": money_number(coupon.get("discount") or promotions.get("couponDiscount")),
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


def clean_text(value):
    return str(value or "").strip().lower()

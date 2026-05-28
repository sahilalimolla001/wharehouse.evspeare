import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Coupon, CouponRedemption


def normalize_coupon_code(value):
    return re.sub(r"[^A-Z0-9_-]", "", str(value or "").strip().upper())[:40]


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def money_value(value):
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        amount = Decimal("0")
    return max(Decimal("0"), amount.quantize(Decimal("0.01")))


def order_subtotal_from_payload(payload):
    amounts = payload.get("amounts") if isinstance(payload.get("amounts"), dict) else {}
    if "subtotal" in amounts:
        return money_value(amounts.get("subtotal"))
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    total = Decimal("0")
    for item in items:
        if not isinstance(item, dict):
            continue
        quantity = money_value(item.get("quantity") or 1)
        price = money_value(item.get("price") or item.get("unit_price") or item.get("amount"))
        total += price * quantity
    return money_value(total)


def coupon_payload(payload):
    promotions = payload.get("promotions") if isinstance(payload.get("promotions"), dict) else {}
    coupon = promotions.get("coupon") if isinstance(promotions.get("coupon"), dict) else {}
    code = payload.get("coupon_code") or payload.get("couponCode") or promotions.get("couponCode") or coupon.get("code")
    discount = coupon.get("discount") or coupon.get("discountAmount") or promotions.get("couponDiscount")
    return {"code": normalize_coupon_code(code), "discount": money_value(discount)}


def validate_coupon(code, customer_phone, subtotal):
    code = normalize_coupon_code(code)
    phone = normalize_phone(customer_phone)
    subtotal = money_value(subtotal)
    if not code:
        raise ValueError("Coupon code is required")
    if not phone:
        raise ValueError("Customer mobile number is required")

    coupon = Coupon.query.filter_by(code=code).first()
    if not coupon:
        raise ValueError("Coupon not found")
    now = datetime.utcnow()
    if not coupon.is_active:
        raise ValueError("Coupon is inactive")
    if coupon.starts_at and coupon.starts_at > now:
        raise ValueError("Coupon is not active yet")
    if coupon.expires_at and coupon.expires_at < now:
        raise ValueError("Coupon has expired")
    if subtotal < money_value(coupon.min_order_amount):
        raise ValueError(f"Minimum order amount is Rs. {money_value(coupon.min_order_amount)}")
    if CouponRedemption.query.filter_by(coupon_id=coupon.id, customer_phone=phone).first():
        raise ValueError("This mobile number has already used this coupon")
    if coupon.max_redemptions is not None and len(coupon.redemptions) >= coupon.max_redemptions:
        raise ValueError("Coupon usage limit reached")

    if coupon.discount_type == "percent":
        discount = subtotal * money_value(coupon.discount_value) / Decimal("100")
        if coupon.max_discount_amount:
            discount = min(discount, money_value(coupon.max_discount_amount))
    else:
        discount = money_value(coupon.discount_value)
    discount = min(money_value(discount), subtotal)
    if discount <= 0:
        raise ValueError("Coupon discount is not available")

    return {
        "coupon": coupon,
        "code": coupon.code,
        "title": coupon.title,
        "discount_type": coupon.discount_type,
        "discount_value": float(coupon.discount_value or 0),
        "discount": float(discount),
        "subtotal": float(subtotal),
    }


def validate_order_coupon(payload):
    coupon = coupon_payload(payload)
    if not coupon["code"]:
        return None
    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    phone = payload.get("customer_phone") or customer.get("phone")
    subtotal = order_subtotal_from_payload(payload)
    result = validate_coupon(coupon["code"], phone, subtotal)
    submitted_discount = coupon["discount"]
    if submitted_discount and abs(submitted_discount - money_value(result["discount"])) > Decimal("0.01"):
        raise ValueError("Coupon discount amount is invalid")
    return result


def redeem_order_coupon(order, payload):
    validation = validate_order_coupon(payload)
    if not validation:
        return None
    phone = normalize_phone(order.customer_phone)
    redemption = CouponRedemption(
        coupon_id=validation["coupon"].id,
        order_id=order.id,
        customer_phone=phone,
        discount_amount=money_value(validation["discount"]),
        source_payload=json.dumps(payload, default=str, separators=(",", ":"))[:20000],
    )
    db.session.add(redemption)
    try:
        db.session.flush()
    except IntegrityError as error:
        raise ValueError("This mobile number has already used this coupon") from error
    return redemption

import json
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, jsonify, render_template, request, url_for

from ..extensions import db
from ..models import Order, ShiprocketWebhookEvent
from ..utils.shiprocket import ShiprocketError, create_shiprocket_order, is_shiprocket_configured
from ..utils.stock import log_activity
from .auth import get_current_user, role_required


shiprocket_bp = Blueprint("shiprocket", __name__)

FORM_FIELDS = [
    "local_order_id",
    "order_id",
    "order_date",
    "pickup_location",
    "channel_id",
    "comment",
    "billing_customer_name",
    "billing_last_name",
    "billing_address",
    "billing_address_2",
    "billing_city",
    "billing_pincode",
    "billing_state",
    "billing_country",
    "billing_email",
    "billing_phone",
    "billing_alternate_phone",
    "shipping_customer_name",
    "shipping_last_name",
    "shipping_address",
    "shipping_address_2",
    "shipping_city",
    "shipping_pincode",
    "shipping_state",
    "shipping_country",
    "shipping_email",
    "shipping_phone",
    "payment_method",
    "shipping_charges",
    "giftwrap_charges",
    "transaction_charges",
    "total_discount",
    "sub_total",
    "length",
    "breadth",
    "height",
    "weight",
]

ITEM_FIELDS = ["name", "sku", "units", "selling_price", "discount", "tax", "hsn"]


@shiprocket_bp.route("/shiprocket", methods=["GET", "POST"])
@role_required("manager", "staff")
def create_order():
    selected_order = load_order(request.values.get("local_order_id") or request.args.get("order_id"))
    result = None
    result_summary = None

    if request.method == "POST":
        form_data = form_data_from_request(request.form)
        selected_order = load_order(form_data.get("local_order_id"))
        try:
            payload = build_shiprocket_payload(form_data)
            result = create_shiprocket_order(payload, current_app.config)
            result_summary = summarize_shiprocket_response(result)
            if selected_order:
                save_shiprocket_response(selected_order, result, result_summary)

            current_user = get_current_user()
            reference = result_summary.get("courier_order_id") or payload["order_id"]
            log_activity(
                "shiprocket_order_create",
                f"Created Shiprocket courier order {reference}",
                user_id=current_user.id if current_user else None,
                entity_type="Order" if selected_order else None,
                entity_id=selected_order.id if selected_order else None,
                meta={"shiprocket": result_summary, "local_order_id": selected_order.id if selected_order else None},
            )
            db.session.commit()
            flash("Shiprocket courier order created.", "success")
        except (ShiprocketError, ValueError) as error:
            db.session.rollback()
            flash(f"Shiprocket order failed: {error}", "danger")
    else:
        form_data = default_form_data(selected_order)

    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(100).all()
    return render_template(
        "shiprocket_order.html",
        recent_orders=recent_orders,
        selected_order=selected_order,
        form_data=form_data,
        result=result,
        result_summary=result_summary,
        config_ready=is_shiprocket_configured(current_app.config),
    )


@shiprocket_bp.route("/shiprocket/webhooks")
@role_required("manager", "staff")
def webhook_updates():
    events = ShiprocketWebhookEvent.query.order_by(ShiprocketWebhookEvent.created_at.desc(), ShiprocketWebhookEvent.id.desc()).limit(80).all()
    latest_event = events[0] if events else None
    matched_count = ShiprocketWebhookEvent.query.filter(ShiprocketWebhookEvent.order_id.isnot(None)).count()
    total_count = ShiprocketWebhookEvent.query.count()
    token = current_app.config.get("SHIPROCKET_WEBHOOK_TOKEN", "")
    webhook_url = url_for("shiprocket.receive_webhook", _external=True)
    webhook_url_with_token = url_for("shiprocket.receive_webhook", token=token, _external=True) if token else webhook_url
    return render_template(
        "shiprocket_webhooks.html",
        events=events,
        latest_event=latest_event,
        matched_count=matched_count,
        total_count=total_count,
        webhook_url=webhook_url,
        webhook_url_with_token=webhook_url_with_token,
        webhook_token_configured=bool(token),
    )


@shiprocket_bp.get("/shiprocket/webhooks/events")
@role_required("manager", "staff")
def webhook_events():
    since_id = int_or_default(request.args.get("since_id"), 0)
    query = ShiprocketWebhookEvent.query
    if since_id:
        query = query.filter(ShiprocketWebhookEvent.id > since_id)
    events = query.order_by(ShiprocketWebhookEvent.id.desc()).limit(50).all()
    latest = ShiprocketWebhookEvent.query.order_by(ShiprocketWebhookEvent.id.desc()).first()
    return jsonify(
        {
            "ok": True,
            "latest_id": latest.id if latest else 0,
            "events": [serialize_webhook_event(event) for event in reversed(events)],
        }
    )


@shiprocket_bp.post("/api/webhooks/courier-updates")
def receive_webhook():
    if not verify_webhook_token():
        return jsonify({"ok": False, "message": "Invalid webhook token"}), 401

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict(flat=True) if request.form else {}
    payloads = payload if isinstance(payload, list) else [payload]

    created_events = []
    try:
        for entry in payloads:
            if not isinstance(entry, dict):
                entry = {"value": entry}
            event = create_webhook_event(entry)
            created_events.append(event)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception("Shiprocket webhook failed")
        return jsonify({"ok": False, "message": str(error)}), 400

    return jsonify({"ok": True, "received": len(created_events), "events": [serialize_webhook_event(event) for event in created_events]})


def default_form_data(order=None):
    now = datetime.now()
    first_name, last_name = split_name(order.customer_name if order else "")
    order_date = order.created_at if order else now
    return {
        "local_order_id": str(order.id) if order else "",
        "order_id": order.order_number if order else f"EW-{now.strftime('%Y%m%d%H%M%S')}",
        "order_date": datetime_input(order_date),
        "pickup_location": current_app.config.get("SHIPROCKET_PICKUP_LOCATION", ""),
        "channel_id": current_app.config.get("SHIPROCKET_CHANNEL_ID", ""),
        "comment": f"Warehouse order {order.order_number}" if order else "",
        "billing_customer_name": first_name,
        "billing_last_name": last_name,
        "billing_address": order.customer_address if order else "",
        "billing_address_2": "",
        "billing_city": "",
        "billing_pincode": "",
        "billing_state": "",
        "billing_country": "India",
        "billing_email": "",
        "billing_phone": order.customer_phone if order else "",
        "billing_alternate_phone": "",
        "shipping_is_billing": True,
        "shipping_customer_name": first_name,
        "shipping_last_name": last_name,
        "shipping_address": order.customer_address if order else "",
        "shipping_address_2": "",
        "shipping_city": "",
        "shipping_pincode": "",
        "shipping_state": "",
        "shipping_country": "India",
        "shipping_email": "",
        "shipping_phone": order.customer_phone if order else "",
        "payment_method": "Prepaid",
        "shipping_charges": "0",
        "giftwrap_charges": "0",
        "transaction_charges": "0",
        "total_discount": "0",
        "sub_total": decimal_to_input(order.total_value if order else 0),
        "length": decimal_to_input(current_app.config.get("SHIPROCKET_DEFAULT_LENGTH_CM", 10)),
        "breadth": decimal_to_input(current_app.config.get("SHIPROCKET_DEFAULT_BREADTH_CM", 10)),
        "height": decimal_to_input(current_app.config.get("SHIPROCKET_DEFAULT_HEIGHT_CM", 10)),
        "weight": decimal_to_input(current_app.config.get("SHIPROCKET_DEFAULT_WEIGHT_KG", 0.5)),
        "line_items": default_line_items(order),
    }


def create_webhook_event(payload):
    summary = summarize_webhook_payload(payload)
    order = find_order_for_webhook(summary)
    event = ShiprocketWebhookEvent(
        order_id=order.id if order else None,
        event_type=trim_value(summary.get("event_type"), 80),
        shiprocket_order_id=trim_value(summary.get("shiprocket_order_id"), 120),
        shipment_id=trim_value(summary.get("shipment_id"), 120),
        awb=trim_value(summary.get("awb"), 120),
        current_status=trim_value(summary.get("current_status"), 120),
        previous_status=trim_value(summary.get("previous_status"), 120),
        status_code=trim_value(summary.get("status_code"), 80),
        courier_name=trim_value(summary.get("courier_name"), 160),
        location=trim_value(summary.get("location"), 180),
        event_time=parse_event_time(summary.get("event_time")),
        payload_json=json.dumps(payload, default=str, separators=(",", ":"))[:20000],
        headers_json=json.dumps(webhook_headers(), separators=(",", ":"))[:4000],
        received_ip=trim_value(request.headers.get("X-Forwarded-For") or request.remote_addr, 80),
    )
    db.session.add(event)
    db.session.flush()
    if order:
        apply_webhook_to_order(order, summary, payload)
        log_activity(
            "shiprocket_webhook",
            f"Shiprocket update: {summary.get('current_status') or 'received'}",
            entity_type="Order",
            entity_id=order.id,
            meta={"event_id": event.id, "summary": summary},
        )
    return event


def summarize_webhook_payload(payload):
    latest_scan = latest_scan_payload(payload)
    return {
        "event_type": first_payload_value(payload, "event", "event_type", "webhook_type", "type") or str(latest_scan.get("activity") or "").strip(),
        "shiprocket_order_id": first_payload_value(payload, "order_id", "shiprocket_order_id", "sr_order_id"),
        "shipment_id": first_payload_value(payload, "shipment_id", "shiprocket_shipment_id", "sr_shipment_id"),
        "awb": first_payload_value(payload, "awb", "awb_code", "awb_number", "tracking_number"),
        "current_status": first_payload_value(payload, "current_status", "current_status_name", "shipment_status", "status", "tracking_status"),
        "previous_status": first_payload_value(payload, "previous_status", "previous_status_name", "old_status"),
        "status_code": first_payload_value(payload, "current_status_id", "status_code", "shipment_status_id"),
        "courier_name": first_payload_value(payload, "courier_name", "courier_company", "courier_partner"),
        "location": first_payload_value(payload, "location", "current_location", "scan_location") or str(latest_scan.get("location") or "").strip(),
        "event_time": first_payload_value(payload, "event_time", "status_time", "scan_date", "current_timestamp", "timestamp", "updated_at") or str(latest_scan.get("date") or "").strip(),
        "channel_order_id": first_payload_value(payload, "channel_order_id", "channel_order_number", "order_number"),
    }


def first_payload_value(payload, *keys):
    for container in payload_containers(payload):
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def payload_containers(payload):
    containers = []
    if isinstance(payload, dict):
        containers.append(payload)
        for key in ("data", "shipment", "order", "tracking_data", "tracking", "payload"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.extend(payload_containers(value))
    return containers


def latest_scan_payload(payload):
    scans = first_payload_list(payload, "scans", "scan", "activities")
    if not scans:
        return {}
    first_scan = scans[0]
    return first_scan if isinstance(first_scan, dict) else {}


def first_payload_list(payload, *keys):
    for container in payload_containers(payload):
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                return value
    return []


def find_order_for_webhook(summary):
    lookup_fields = [
        (Order.courier_order_id, summary.get("shiprocket_order_id")),
        (Order.courier_shipment_id, summary.get("shipment_id")),
        (Order.courier_awb, summary.get("awb")),
        (Order.order_number, summary.get("channel_order_id")),
    ]
    for column, value in lookup_fields:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        order = Order.query.filter(column == cleaned).first()
        if order:
            return order
    return None


def apply_webhook_to_order(order, summary, payload):
    order.courier_provider = "shiprocket"
    if summary.get("shiprocket_order_id"):
        order.courier_order_id = trim_value(summary["shiprocket_order_id"], 120)
    if summary.get("shipment_id"):
        order.courier_shipment_id = trim_value(summary["shipment_id"], 120)
    if summary.get("awb"):
        order.courier_awb = trim_value(summary["awb"], 120)
    if summary.get("current_status"):
        order.courier_status = trim_value(summary["current_status"], 80)
        mapped_status = map_shiprocket_status(summary["current_status"])
        if mapped_status and order.status not in {"completed", "cancelled"}:
            order.status = mapped_status
            if mapped_status == "completed":
                order.completed_at = datetime.utcnow()
    order.courier_response = json.dumps(payload, default=str, separators=(",", ":"))[:20000]


def map_shiprocket_status(status):
    normalized = str(status or "").strip().lower()
    if not normalized:
        return None
    if "delivered" in normalized and "rto" not in normalized:
        return "completed"
    if "cancel" in normalized:
        return "cancelled"
    if "rto" in normalized or "return" in normalized:
        return "cancelled"
    dispatched_markers = ["pickup", "picked", "shipped", "in transit", "out for delivery", "manifested"]
    if any(marker in normalized for marker in dispatched_markers):
        return "dispatched"
    return None


def parse_event_time(value):
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(cleaned[:19], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def verify_webhook_token():
    configured = str(current_app.config.get("SHIPROCKET_WEBHOOK_TOKEN") or "").strip()
    if not configured:
        return True
    supplied = (
        request.args.get("token", "").strip()
        or bearer_token()
        or request.headers.get("X-Shiprocket-Token", "").strip()
        or request.headers.get("X-Webhook-Token", "").strip()
        or request.headers.get("X-Integration-Key", "").strip()
    )
    return bool(supplied and secrets.compare_digest(configured, supplied))


def bearer_token():
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def webhook_headers():
    safe_headers = {}
    for key, value in request.headers.items():
        if key.lower() in {"authorization", "cookie", "x-shiprocket-token", "x-webhook-token", "x-integration-key"}:
            safe_headers[key] = "[redacted]"
        else:
            safe_headers[key] = value
    return safe_headers


def serialize_webhook_event(event):
    return {
        "id": event.id,
        "received_at": event.created_at.strftime("%Y-%m-%d %H:%M:%S") if event.created_at else "",
        "event_time": event.event_time.strftime("%Y-%m-%d %H:%M:%S") if event.event_time else "",
        "event_type": event.event_type or "",
        "order_id": event.order_id,
        "order_number": event.order.order_number if event.order else "",
        "shiprocket_order_id": event.shiprocket_order_id or "",
        "shipment_id": event.shipment_id or "",
        "awb": event.awb or "",
        "current_status": event.current_status or "",
        "previous_status": event.previous_status or "",
        "status_code": event.status_code or "",
        "courier_name": event.courier_name or "",
        "location": event.location or "",
        "matched": bool(event.order_id),
    }


def default_line_items(order=None):
    if not order:
        return [blank_line_item()]

    items = []
    for item in order.items:
        unit_price = item.unit_price or item.product.selling_price or 0
        items.append(
            {
                "name": item.product.name,
                "sku": item.product.sku,
                "units": str(item.quantity),
                "selling_price": decimal_to_input(unit_price),
                "discount": "0",
                "tax": "0",
                "hsn": "",
            }
        )
    return items or [blank_line_item()]


def blank_line_item():
    return {"name": "", "sku": "", "units": "1", "selling_price": "0", "discount": "0", "tax": "0", "hsn": ""}


def form_data_from_request(form):
    data = {field: str(form.get(field, "") or "").strip() for field in FORM_FIELDS}
    data["shipping_is_billing"] = form.get("shipping_is_billing") == "on"
    data["line_items"] = line_items_from_request(form)
    return data


def line_items_from_request(form):
    values = {field: form.getlist(f"item_{field}") for field in ITEM_FIELDS}
    total_rows = max([len(rows) for rows in values.values()] or [0])
    items = []
    for index in range(total_rows):
        row = {field: value_at(values[field], index) for field in ITEM_FIELDS}
        if any(row.values()):
            items.append(row)
    return items or [blank_line_item()]


def value_at(values, index):
    if index >= len(values):
        return ""
    return str(values[index] or "").strip()


def build_shiprocket_payload(data):
    required_fields = [
        ("order_id", "Order ID"),
        ("order_date", "Order date"),
        ("pickup_location", "Pickup location"),
        ("billing_customer_name", "Billing first name"),
        ("billing_address", "Billing address"),
        ("billing_city", "Billing city"),
        ("billing_pincode", "Billing pincode"),
        ("billing_state", "Billing state"),
        ("billing_country", "Billing country"),
        ("billing_phone", "Billing phone"),
    ]
    for key, label in required_fields:
        require_text(data.get(key), label)

    payment_method = require_text(data.get("payment_method"), "Payment method")
    if payment_method not in {"Prepaid", "COD"}:
        raise ValueError("Payment method must be Prepaid or COD.")

    line_items, computed_sub_total = build_order_items(data.get("line_items", []))
    sub_total = decimal_field(data.get("sub_total"), "Sub total", required=False)
    if sub_total <= 0:
        sub_total = computed_sub_total
    if sub_total <= 0:
        raise ValueError("Sub total must be greater than zero.")

    payload = {
        "order_id": data["order_id"],
        "order_date": data["order_date"].replace("T", " "),
        "pickup_location": data["pickup_location"],
        "billing_customer_name": data["billing_customer_name"],
        "billing_address": data["billing_address"],
        "billing_city": data["billing_city"],
        "billing_pincode": data["billing_pincode"],
        "billing_state": data["billing_state"],
        "billing_country": data["billing_country"],
        "billing_phone": data["billing_phone"],
        "shipping_is_billing": bool(data.get("shipping_is_billing")),
        "order_items": line_items,
        "payment_method": payment_method,
        "shipping_charges": decimal_payload(decimal_field(data.get("shipping_charges"), "Shipping charges", required=False)),
        "giftwrap_charges": decimal_payload(decimal_field(data.get("giftwrap_charges"), "Giftwrap charges", required=False)),
        "transaction_charges": decimal_payload(decimal_field(data.get("transaction_charges"), "Transaction charges", required=False)),
        "total_discount": decimal_payload(decimal_field(data.get("total_discount"), "Total discount", required=False)),
        "sub_total": decimal_payload(sub_total),
        "length": decimal_payload(decimal_field(data.get("length"), "Length", min_value=0.01)),
        "breadth": decimal_payload(decimal_field(data.get("breadth"), "Breadth", min_value=0.01)),
        "height": decimal_payload(decimal_field(data.get("height"), "Height", min_value=0.01)),
        "weight": decimal_payload(decimal_field(data.get("weight"), "Weight", min_value=0.01)),
    }

    optional_fields = [
        "channel_id",
        "comment",
        "billing_last_name",
        "billing_address_2",
        "billing_email",
        "billing_alternate_phone",
    ]
    for field in optional_fields:
        add_optional(payload, field, data.get(field))

    if not data.get("shipping_is_billing"):
        shipping_required = [
            ("shipping_customer_name", "Shipping first name"),
            ("shipping_address", "Shipping address"),
            ("shipping_city", "Shipping city"),
            ("shipping_pincode", "Shipping pincode"),
            ("shipping_state", "Shipping state"),
            ("shipping_country", "Shipping country"),
            ("shipping_phone", "Shipping phone"),
        ]
        for key, label in shipping_required:
            require_text(data.get(key), label)
        for field in [
            "shipping_customer_name",
            "shipping_last_name",
            "shipping_address",
            "shipping_address_2",
            "shipping_city",
            "shipping_pincode",
            "shipping_state",
            "shipping_country",
            "shipping_email",
            "shipping_phone",
        ]:
            add_optional(payload, field, data.get(field))

    if payload.get("channel_id"):
        payload["channel_id"] = int(payload["channel_id"]) if str(payload["channel_id"]).isdigit() else payload["channel_id"]

    return payload


def build_order_items(rows):
    items = []
    sub_total = Decimal("0")
    for row in rows:
        if not any(str(value or "").strip() for value in row.values()):
            continue
        name = require_text(row.get("name"), "Item name")
        sku = require_text(row.get("sku"), "Item SKU")
        units = int_field(row.get("units"), "Item units", min_value=1)
        selling_price = decimal_field(row.get("selling_price"), "Item selling price", min_value=0)
        discount = decimal_field(row.get("discount"), "Item discount", required=False, min_value=0)
        tax = decimal_field(row.get("tax"), "Item tax", required=False, min_value=0)
        item = {
            "name": name,
            "sku": sku,
            "units": units,
            "selling_price": decimal_to_input(selling_price),
            "discount": decimal_to_input(discount),
            "tax": decimal_to_input(tax),
        }
        hsn = str(row.get("hsn") or "").strip()
        if hsn:
            item["hsn"] = int(hsn) if hsn.isdigit() else hsn
        items.append(item)
        sub_total += Decimal(units) * selling_price

    if not items:
        raise ValueError("At least one order item is required.")
    return items, sub_total


def add_optional(payload, key, value):
    cleaned = str(value or "").strip()
    if cleaned:
        payload[key] = cleaned


def require_text(value, label):
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required.")
    return cleaned


def decimal_field(value, label, required=True, min_value=None):
    cleaned = str(value or "").strip()
    if not cleaned:
        if required:
            raise ValueError(f"{label} is required.")
        return Decimal("0")
    try:
        number = Decimal(cleaned)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be a number.") from error
    if min_value is not None and number < Decimal(str(min_value)):
        raise ValueError(f"{label} must be at least {min_value}.")
    return number


def int_field(value, label, min_value=None):
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required.")
    try:
        number = int(cleaned)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a whole number.") from error
    if min_value is not None and number < min_value:
        raise ValueError(f"{label} must be at least {min_value}.")
    return number


def int_or_default(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def decimal_payload(value):
    return float(value)


def decimal_to_input(value):
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        number = Decimal("0")
    text = format(number.quantize(Decimal("0.01")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def split_name(name):
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def datetime_input(value):
    if not value:
        value = datetime.now()
    return value.strftime("%Y-%m-%dT%H:%M")


def load_order(value):
    try:
        order_id = int(value or 0)
    except (TypeError, ValueError):
        return None
    if not order_id:
        return None
    return Order.query.get(order_id)


def summarize_shiprocket_response(response):
    return {
        "courier_order_id": response_value(response, "order_id"),
        "courier_shipment_id": response_value(response, "shipment_id"),
        "courier_awb": response_value(response, "awb_code", "awb"),
        "courier_name": response_value(response, "courier_name", "courier_company_id"),
        "courier_status": response_value(response, "status", "message"),
    }


def response_value(response, *keys):
    if not isinstance(response, dict):
        return ""
    containers = [response]
    for key in ("data", "shipment", "order"):
        value = response.get(key)
        if isinstance(value, dict):
            containers.append(value)
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def save_shiprocket_response(order, response, summary):
    order.courier_provider = "shiprocket"
    order.courier_order_id = trim_value(summary.get("courier_order_id"), 120)
    order.courier_shipment_id = trim_value(summary.get("courier_shipment_id"), 120)
    order.courier_awb = trim_value(summary.get("courier_awb"), 120)
    order.courier_status = trim_value(summary.get("courier_status"), 80)
    order.courier_response = json.dumps(response, default=str, separators=(",", ":"))[:20000]


def trim_value(value, limit):
    cleaned = str(value or "").strip()
    return cleaned[:limit] if cleaned else None

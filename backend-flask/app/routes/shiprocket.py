import json
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, jsonify, render_template, request, url_for

from ..extensions import db
from ..models import Order, ShiprocketWebhookEvent
from ..utils.customer_website import notify_shipping_status_change
from ..utils.shiprocket import ShiprocketError, create_shiprocket_order, create_shiprocket_return_order, generate_shiprocket_label, is_shiprocket_configured
from ..utils.stock import log_activity
from .auth import get_current_user, role_required, selected_warehouse


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
                save_package_dimensions(selected_order, package_dimensions_from_data(form_data, required=True))
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

    warehouse = selected_warehouse()
    recent_query = Order.query
    if warehouse:
        recent_query = recent_query.filter(Order.warehouse_id == warehouse.id)
    recent_orders = recent_query.order_by(Order.created_at.desc()).limit(100).all()
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


@shiprocket_bp.route("/shipping-status")
@role_required("manager", "staff")
def shipping_status():
    orders = shipping_status_orders()
    latest_event = ShiprocketWebhookEvent.query.order_by(ShiprocketWebhookEvent.id.desc()).first()
    return render_template(
        "shipping_status.html",
        shipping_rows=[serialize_shipping_status_order(order) for order in orders],
        latest_event=latest_event,
    )


@shiprocket_bp.get("/shipping-status/live")
@role_required("manager", "staff")
def shipping_status_live():
    latest_event = ShiprocketWebhookEvent.query.order_by(ShiprocketWebhookEvent.id.desc()).first()
    return jsonify(
        {
            "ok": True,
            "latest_id": latest_event.id if latest_event else 0,
            "latest_status": latest_event.current_status if latest_event else "",
            "orders": [serialize_shipping_status_order(order) for order in shipping_status_orders()],
        }
    )


@shiprocket_bp.route("/shipping-status/<int:order_id>")
@role_required("manager", "staff")
def shipping_status_detail(order_id):
    order = Order.query.get_or_404(order_id)
    warehouse = selected_warehouse()
    if warehouse and order.warehouse_id != warehouse.id:
        abort(403)
    return render_template(
        "shipping_status_detail.html",
        tracking=serialize_shipping_tracking(order),
    )


@shiprocket_bp.get("/shipping-status/<int:order_id>/live")
@role_required("manager", "staff")
def shipping_status_detail_live(order_id):
    order = Order.query.get_or_404(order_id)
    warehouse = selected_warehouse()
    if warehouse and order.warehouse_id != warehouse.id:
        return jsonify({"ok": False, "message": "Permission denied"}), 403
    return jsonify({"ok": True, "tracking": serialize_shipping_tracking(order)})


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

    push_results = push_shipping_status_updates(created_events)
    return jsonify({"ok": True, "received": len(created_events), "events": [serialize_webhook_event(event) for event in created_events], "customer_app": push_results})


def default_form_data(order=None):
    now = datetime.now()
    source = order_source_payload(order)
    billing_address = source_address(source, "billing", order)
    shipping_address = source_address(source, "shipping", order, fallback=billing_address)
    first_name, last_name = split_name(source_customer_name(source, order))
    billing_first_name = billing_address.get("first_name") or first_name
    billing_last_name = billing_address.get("last_name") or last_name
    shipping_first_name = shipping_address.get("first_name") or billing_first_name
    shipping_last_name = shipping_address.get("last_name") or billing_last_name
    order_date = source_order_date(source) or (order.created_at if order else now)
    package = order_package_defaults(order)
    return {
        "local_order_id": str(order.id) if order else "",
        "order_id": order.order_number if order else f"EW-{now.strftime('%Y%m%d%H%M%S')}",
        "order_date": datetime_input(order_date),
        "pickup_location": shiprocket_pickup_location(order),
        "channel_id": current_app.config.get("SHIPROCKET_CHANNEL_ID", ""),
        "comment": f"Warehouse order {order.order_number}" if order else "",
        "billing_customer_name": billing_first_name,
        "billing_last_name": billing_last_name,
        "billing_address": billing_address.get("address", ""),
        "billing_address_2": billing_address.get("address_2", ""),
        "billing_city": billing_address.get("city", ""),
        "billing_pincode": billing_address.get("pincode", ""),
        "billing_state": billing_address.get("state", ""),
        "billing_country": billing_address.get("country", "India"),
        "billing_email": billing_address.get("email", ""),
        "billing_phone": billing_address.get("phone", ""),
        "billing_alternate_phone": billing_address.get("alternate_phone", ""),
        "shipping_is_billing": addresses_match(billing_address, shipping_address),
        "shipping_customer_name": shipping_first_name,
        "shipping_last_name": shipping_last_name,
        "shipping_address": shipping_address.get("address", ""),
        "shipping_address_2": shipping_address.get("address_2", ""),
        "shipping_city": shipping_address.get("city", ""),
        "shipping_pincode": shipping_address.get("pincode", ""),
        "shipping_state": shipping_address.get("state", ""),
        "shipping_country": shipping_address.get("country", "India"),
        "shipping_email": shipping_address.get("email", ""),
        "shipping_phone": shipping_address.get("phone", ""),
        "payment_method": source_payment_method(source),
        "shipping_charges": "0",
        "giftwrap_charges": "0",
        "transaction_charges": "0",
        "total_discount": "0",
        "sub_total": decimal_to_input(order.total_value if order else 0),
        "length": decimal_to_input(package["length"]),
        "breadth": decimal_to_input(package["breadth"]),
        "height": decimal_to_input(package["height"]),
        "weight": decimal_to_input(package["weight"]),
        "line_items": default_line_items(order, source),
    }


def shiprocket_pickup_location(order=None):
    configured_location = str(current_app.config.get("SHIPROCKET_PICKUP_LOCATION", "") or "").strip()
    if configured_location:
        return configured_location
    if order and order.warehouse:
        return str(order.warehouse.code or "").strip()
    return ""


def dispatch_order_with_shiprocket(order, package_input, user_id=None):
    package = package_dimensions_from_data(package_input, required=False)
    defaults = order_package_defaults(order)
    package = {key: package[key] if package[key] else defaults[key] for key in package}
    save_package_dimensions(order, package)

    result = None
    result_summary = current_shiprocket_summary(order)
    created = False
    skipped = False
    if not order.courier_order_id and not order.courier_shipment_id and is_shiprocket_configured(current_app.config):
        payload = build_shiprocket_payload_for_order(order, package)
        result = create_shiprocket_order(payload, current_app.config)
        result_summary = summarize_shiprocket_response(result)
        save_shiprocket_response(order, result, result_summary)
        created = True
    elif not order.courier_order_id and not order.courier_shipment_id:
        skipped = True

    order.status = "dispatched"
    dispatch_mode = "via Shiprocket" if order.courier_order_id or order.courier_shipment_id else "without Shiprocket courier"
    log_activity(
        "order_dispatch",
        f"Order {order.order_number} dispatched {dispatch_mode}",
        user_id=user_id,
        entity_type="Order",
        entity_id=order.id,
        meta={"shiprocket": result_summary, "package": serialize_package(package), "created_courier_order": created, "shiprocket_skipped": skipped},
    )
    return {"created": created, "skipped": skipped, "result": result, "summary": result_summary, "package": package}


def ensure_shiprocket_order(order, user_id=None, package_input=None):
    if not is_shiprocket_configured(current_app.config):
        return {"created": False, "skipped": True, "summary": current_shiprocket_summary(order), "message": "Shiprocket is not configured"}
    if order.courier_order_id or order.courier_shipment_id:
        return {"created": False, "skipped": False, "summary": current_shiprocket_summary(order)}
    package = package_dimensions_from_data(package_input, required=True) if package_input else order_package_defaults(order)
    payload = build_shiprocket_payload_for_order(order, package)
    result = create_shiprocket_order(payload, current_app.config)
    summary = summarize_shiprocket_response(result)
    save_package_dimensions(order, package)
    save_shiprocket_response(order, result, summary)
    log_activity(
        "shiprocket_order_auto_create",
        f"Auto-created Shiprocket order for {order.order_number}",
        user_id=user_id,
        entity_type="Order",
        entity_id=order.id,
        meta={"shiprocket": summary},
    )
    return {"created": True, "skipped": False, "result": result, "summary": summary}


def ensure_shiprocket_label(order, user_id=None, package_input=None):
    label_url = shiprocket_label_url(order)
    if label_url:
        return {"created": False, "label_url": label_url, "summary": current_shiprocket_summary(order)}
    if not order.courier_shipment_id:
        ensure_shiprocket_order(order, user_id=user_id, package_input=package_input)
    if not order.courier_shipment_id:
        raise ShiprocketError("Shiprocket shipment id is missing. Label can be generated after shipment/AWB creation.")
    result = generate_shiprocket_label([order.courier_shipment_id], current_app.config)
    label_url = response_value(result, "label_url", "label", "label_url_s3", "url", "download_url")
    if not label_url:
        label_url = response_value(result, "label_url", "label", "url")
    merge_courier_response(order, {"label": result, "label_url": label_url})
    log_activity(
        "shiprocket_label_generate",
        f"Generated Shiprocket label for {order.order_number}",
        user_id=user_id,
        entity_type="Order",
        entity_id=order.id,
        meta={"label_url": label_url},
    )
    return {"created": True, "label_url": label_url, "summary": current_shiprocket_summary(order), "result": result}


def create_shiprocket_return_for_customer_return(return_order, user_id=None):
    if not is_shiprocket_configured(current_app.config):
        return {"created": False, "skipped": True, "message": "Shiprocket is not configured"}
    source_order = return_order.order
    if not source_order:
        return {"created": False, "skipped": True, "message": "Original order is not linked"}
    package = order_package_defaults(source_order)
    payload = build_shiprocket_payload_for_order(source_order, package)
    payload["order_id"] = return_order.return_number
    payload["comment"] = f"Return for {source_order.order_number}"
    payload.update(return_payload_fields(payload, source_order))
    payload["length"] = decimal_payload(package["length"])
    payload["breadth"] = decimal_payload(package["breadth"])
    payload["height"] = decimal_payload(package["height"])
    payload["weight"] = decimal_payload(package["weight"])
    result = create_shiprocket_return_order(payload, current_app.config)
    return_order.notes = append_note(return_order.notes, f"Shiprocket return created: {json.dumps(summarize_shiprocket_response(result), default=str)}")
    log_activity(
        "shiprocket_return_auto_create",
        f"Auto-created Shiprocket return {return_order.return_number}",
        user_id=user_id,
        entity_type="CustomerReturnOrder",
        entity_id=return_order.id,
        meta={"shiprocket": summarize_shiprocket_response(result)},
    )
    return {"created": True, "result": result, "summary": summarize_shiprocket_response(result)}


def return_payload_fields(forward_payload, source_order=None):
    fields = {
        "pickup_customer_name": forward_payload.get("shipping_customer_name") or forward_payload.get("billing_customer_name"),
        "pickup_last_name": forward_payload.get("shipping_last_name") or forward_payload.get("billing_last_name", ""),
        "pickup_address": forward_payload.get("shipping_address") or forward_payload.get("billing_address"),
        "pickup_address_2": forward_payload.get("shipping_address_2") or forward_payload.get("billing_address_2", ""),
        "pickup_city": forward_payload.get("shipping_city") or forward_payload.get("billing_city"),
        "pickup_state": forward_payload.get("shipping_state") or forward_payload.get("billing_state"),
        "pickup_country": forward_payload.get("shipping_country") or forward_payload.get("billing_country", "India"),
        "pickup_pincode": forward_payload.get("shipping_pincode") or forward_payload.get("billing_pincode"),
        "pickup_email": forward_payload.get("shipping_email") or forward_payload.get("billing_email", ""),
        "pickup_phone": forward_payload.get("shipping_phone") or forward_payload.get("billing_phone"),
    }
    warehouse_id = current_app.config.get("SHIPROCKET_RETURN_WAREHOUSE_ID", "") or (source_order.warehouse_id if source_order else "")
    if str(warehouse_id).strip():
        fields["return_warehouse_id"] = int(warehouse_id) if str(warehouse_id).isdigit() else warehouse_id
    return fields


def build_shiprocket_payload_for_order(order, package_input):
    form_data = default_form_data(order)
    package = package_dimensions_from_data(package_input, required=True)
    form_data["length"] = decimal_to_input(package["length"])
    form_data["breadth"] = decimal_to_input(package["breadth"])
    form_data["height"] = decimal_to_input(package["height"])
    form_data["weight"] = decimal_to_input(package["weight"])
    return build_shiprocket_payload(form_data)


def package_dimensions_from_data(data, required=True):
    data = data or {}
    package = {
        "length": package_decimal(data, ["length", "package_length_cm"], "Package length", required),
        "breadth": package_decimal(data, ["breadth", "width", "package_breadth_cm"], "Package breadth", required),
        "height": package_decimal(data, ["height", "package_height_cm"], "Package height", required),
        "weight": package_decimal(data, ["weight", "package_weight_kg"], "Package weight", required),
    }
    return package


def package_decimal(data, keys, label, required):
    value = first_mapping_value(data, keys)
    return decimal_field(value, label, required=required, min_value=0.01)


def first_mapping_value(data, keys):
    if hasattr(data, "get"):
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
    return ""


def save_package_dimensions(order, package):
    order.package_length_cm = package["length"]
    order.package_breadth_cm = package["breadth"]
    order.package_height_cm = package["height"]
    order.package_weight_kg = package["weight"]


def serialize_package(package):
    return {key: decimal_to_input(value) for key, value in package.items()}


def current_shiprocket_summary(order):
    return {
        "courier_order_id": order.courier_order_id or "",
        "courier_shipment_id": order.courier_shipment_id or "",
        "courier_awb": order.courier_awb or "",
        "courier_status": order.courier_status or "",
    }


def order_package_defaults(order):
    return {
        "length": order.package_length_cm if order and order.package_length_cm else current_app.config.get("SHIPROCKET_DEFAULT_LENGTH_CM", 10),
        "breadth": order.package_breadth_cm if order and order.package_breadth_cm else current_app.config.get("SHIPROCKET_DEFAULT_BREADTH_CM", 10),
        "height": order.package_height_cm if order and order.package_height_cm else current_app.config.get("SHIPROCKET_DEFAULT_HEIGHT_CM", 10),
        "weight": order.package_weight_kg if order and order.package_weight_kg else current_app.config.get("SHIPROCKET_DEFAULT_WEIGHT_KG", 0.5),
    }


def order_source_payload(order):
    if not order or not order.source_payload:
        return {}
    try:
        payload = json.loads(order.source_payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def source_customer_name(source, order=None):
    customer = source.get("customer") if isinstance(source.get("customer"), dict) else {}
    return (
        source_text(source.get("customer_name"))
        or source_text(source.get("name"))
        or source_text(customer.get("name"))
        or " ".join(part for part in [source_text(customer.get("first_name")), source_text(customer.get("last_name"))] if part)
        or (order.customer_name if order else "")
    )


def source_address(source, kind, order=None, fallback=None):
    aliases = {
        "billing": ["billing_address", "billing", "customer"],
        "shipping": ["shipping_address", "shipping", "delivery_address", "delivery"],
    }[kind]
    raw = first_source_entry(source, aliases)
    if raw in (None, "") and kind == "billing":
        raw = first_source_entry(source, ["customer_address", "address"])
    if raw in (None, "") and kind == "shipping":
        raw = first_source_entry(source, ["customer_address", "address"])
    if raw in (None, "") and fallback:
        return dict(fallback)

    customer = source.get("customer") if isinstance(source.get("customer"), dict) else {}
    customer_name = source_customer_name(source, order)
    first_name, last_name = split_name(customer_name)
    stored_address = parse_customer_address_text(order.customer_address if order else "")
    address = {
        "first_name": first_name,
        "last_name": last_name,
        "address": stored_address["address"],
        "address_2": "",
        "city": stored_address["city"],
        "pincode": stored_address["pincode"],
        "state": stored_address["state"],
        "country": stored_address["country"],
        "email": source_text(source.get("customer_email") or source.get("email") or customer.get("email")),
        "phone": source_text(source.get("customer_phone") or source.get("phone") or customer.get("phone") or (order.customer_phone if order else "")),
        "alternate_phone": source_text(source.get("alternate_phone") or source.get("customer_alternate_phone")),
    }

    if isinstance(raw, str):
        parsed_raw = parse_customer_address_text(raw)
        address.update({key: value or address[key] for key, value in parsed_raw.items()})
        return address
    if not isinstance(raw, dict):
        return address

    raw_first, raw_last = source_name_parts(raw)
    location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    coordinates = raw.get("coordinates") if isinstance(raw.get("coordinates"), dict) else location.get("coordinates") if isinstance(location.get("coordinates"), dict) else {}
    latitude = coordinates.get("latitude") or coordinates.get("lat")
    longitude = coordinates.get("longitude") or coordinates.get("lng") or coordinates.get("lon")
    map_location = source_text(raw.get("mapLocation") or raw.get("map_location") or location.get("mapLocation") or location.get("map_location"))
    if not map_location and latitude and longitude:
        map_location = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
    address_2 = source_text(raw.get("address_2") or raw.get("line2") or raw.get("address2") or raw.get("street2") or location.get("address2"))
    parsed_raw = parse_customer_address_text(raw.get("address") or raw.get("full_address"))
    if map_location and map_location not in address_2:
        address_2 = " | ".join(part for part in [address_2, f"Map: {map_location}"] if part)
    address.update(
        {
            "first_name": raw_first or first_name,
            "last_name": raw_last or last_name,
            "address": source_text(raw.get("line1") or raw.get("address1") or raw.get("street") or raw.get("street1") or location.get("address")) or parsed_raw["address"] or address["address"],
            "address_2": address_2,
            "city": source_text(raw.get("city") or raw.get("town") or location.get("city")) or parsed_raw["city"] or address["city"],
            "pincode": source_text(raw.get("pincode") or raw.get("postal_code") or raw.get("postcode") or raw.get("zip") or location.get("pincode")) or parsed_raw["pincode"] or address["pincode"],
            "state": source_text(raw.get("state") or raw.get("province") or raw.get("region") or location.get("state")) or parsed_raw["state"] or address["state"],
            "country": source_text(raw.get("country")) or parsed_raw["country"] or address["country"],
            "email": source_text(raw.get("email")) or address["email"],
            "phone": source_text(raw.get("phone") or raw.get("mobile")) or address["phone"],
            "alternate_phone": source_text(raw.get("alternate_phone")) or address["alternate_phone"],
        }
    )
    return address


def parse_customer_address_text(value):
    text = source_text(value)
    parsed = {"address": text, "city": "", "pincode": "", "state": "", "country": "India"}
    parts = [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]
    pin_index = next((index for index in range(len(parts) - 1, -1, -1) if re.fullmatch(r"\d{6}", parts[index])), None)
    if pin_index is None or pin_index < 2:
        return parsed
    parsed.update(
        {
            "address": ", ".join(parts[: pin_index - 2]) or text,
            "city": parts[pin_index - 2],
            "state": parts[pin_index - 1],
            "pincode": parts[pin_index],
            "country": parts[pin_index + 1] if pin_index + 1 < len(parts) else "India",
        }
    )
    return parsed


def first_source_entry(source, aliases):
    for key in aliases:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def source_name_parts(data):
    first_name = source_text(data.get("first_name") or data.get("firstName"))
    last_name = source_text(data.get("last_name") or data.get("lastName"))
    if first_name or last_name:
        return first_name, last_name
    return split_name(source_text(data.get("name") or data.get("customer_name")))


def source_payment_method(source):
    payment = source.get("payment") if isinstance(source.get("payment"), dict) else {}
    raw = source_text(
        source.get("payment_method")
        or source.get("payment_mode")
        or source.get("paymentMode")
        or source.get("mode_of_payment")
        or payment.get("method")
        or payment.get("mode")
        or payment.get("type")
    ).lower()
    is_cod = bool(source.get("is_cod") or source.get("cod") or payment.get("is_cod"))
    if is_cod or raw in {"cod", "cash on delivery", "cash_on_delivery"}:
        return "COD"
    return "Prepaid"


def source_order_date(source):
    raw = source_text(source.get("order_date") or source.get("created_at") or source.get("createdAt") or source.get("date"))
    if not raw:
        return None
    return parse_event_time(raw) or None


def source_items(source):
    for key in ("items", "line_items", "order_items", "products"):
        value = source.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def source_text(value):
    return str(value or "").strip()


def addresses_match(left, right):
    keys = ["first_name", "last_name", "address", "address_2", "city", "pincode", "state", "country", "email", "phone"]
    return all(source_text(left.get(key)).lower() == source_text(right.get(key)).lower() for key in keys)


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
        return not current_app.config.get("IS_PRODUCTION", False)
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


def shipping_status_orders():
    warehouse = selected_warehouse()
    query = Order.query
    if warehouse:
        query = query.filter(Order.warehouse_id == warehouse.id)
    return (
        query.filter(
            db.or_(
                Order.courier_provider.isnot(None),
                Order.courier_order_id.isnot(None),
                Order.courier_shipment_id.isnot(None),
                Order.courier_awb.isnot(None),
                Order.courier_status.isnot(None),
                Order.status.in_(["dispatched", "completed", "cancelled"]),
            )
        )
        .order_by(Order.updated_at.desc(), Order.created_at.desc())
        .limit(200)
        .all()
    )


def serialize_shipping_status_order(order):
    latest_event = latest_shiprocket_event(order)
    destination = order_shipping_destination(order)
    return {
        "id": order.id,
        "website_order_id": order.external_order_id or order.order_number or "",
        "warehouse_order_number": order.order_number or "",
        "shiprocket_order_id": (latest_event.shiprocket_order_id if latest_event else "") or order.courier_order_id or "",
        "awb": (latest_event.awb if latest_event else "") or order.courier_awb or "",
        "latest_status": (latest_event.current_status if latest_event else "") or order.courier_status or order.status or "",
        "courier": (latest_event.courier_name if latest_event else "") or order.courier_provider or "",
        "destination": destination,
        "updated_at": shipping_status_updated_at(order, latest_event),
        "order_url": url_for("shiprocket.shipping_status_detail", order_id=order.id),
        "warehouse_order_url": url_for("orders.order_detail", order_id=order.id),
    }


def latest_shiprocket_event(order):
    if not order:
        return None
    conditions = [ShiprocketWebhookEvent.order_id == order.id]
    if order.courier_order_id:
        conditions.append(ShiprocketWebhookEvent.shiprocket_order_id == order.courier_order_id)
    if order.courier_awb:
        conditions.append(ShiprocketWebhookEvent.awb == order.courier_awb)
    if order.courier_shipment_id:
        conditions.append(ShiprocketWebhookEvent.shipment_id == order.courier_shipment_id)
    query = ShiprocketWebhookEvent.query.filter(db.or_(*conditions))
    return query.order_by(ShiprocketWebhookEvent.created_at.desc(), ShiprocketWebhookEvent.id.desc()).first()


def order_shipping_destination(order):
    source = order_source_payload(order)
    shipping_address = source_address(source, "shipping", order)
    parts = [
        shipping_address.get("city"),
        shipping_address.get("state"),
        shipping_address.get("pincode"),
    ]
    destination = ", ".join(str(part).strip() for part in parts if str(part or "").strip())
    return destination or order.customer_address or ""


def shipping_status_updated_at(order, latest_event):
    value = None
    if latest_event:
        value = latest_event.event_time or latest_event.created_at
    value = value or order.updated_at or order.created_at
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def serialize_shipping_tracking(order):
    row = serialize_shipping_status_order(order)
    history = shipping_tracking_history(order)
    latest = history[0] if history else {}
    status = row["latest_status"] or latest.get("activity") or ""
    return {
        **row,
        "latest_activity": latest.get("activity") or status,
        "latest_location": latest.get("location") or "",
        "progress_stage": tracking_progress_stage(status),
        "history": history,
    }


def shipping_tracking_history(order):
    events = shipping_tracking_events(order)
    rows = []
    for event in events:
        payload = event_payload(event)
        scans = tracking_scans_from_payload(payload)
        if not scans:
            scans = [
                {
                    "date": event.event_time.strftime("%Y-%m-%d %H:%M:%S") if event.event_time else event.created_at.strftime("%Y-%m-%d %H:%M:%S") if event.created_at else "",
                    "activity": event.current_status or event.event_type or "",
                    "location": event.location or "",
                }
            ]
        rows.extend(scans)
    return unique_tracking_rows(rows)


def shipping_tracking_events(order):
    conditions = [ShiprocketWebhookEvent.order_id == order.id]
    if order.courier_order_id:
        conditions.append(ShiprocketWebhookEvent.shiprocket_order_id == order.courier_order_id)
    if order.courier_awb:
        conditions.append(ShiprocketWebhookEvent.awb == order.courier_awb)
    if order.courier_shipment_id:
        conditions.append(ShiprocketWebhookEvent.shipment_id == order.courier_shipment_id)
    return (
        ShiprocketWebhookEvent.query.filter(db.or_(*conditions))
        .order_by(ShiprocketWebhookEvent.created_at.desc(), ShiprocketWebhookEvent.id.desc())
        .limit(200)
        .all()
    )


def event_payload(event):
    try:
        payload = json.loads(event.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def tracking_scans_from_payload(payload):
    scans = []
    for value in payload_lists(payload, "scans", "scan", "activities", "tracking_history", "shipment_track_activities"):
        for item in value:
            if isinstance(item, dict):
                scans.append(
                    {
                        "date": source_text(item.get("date") or item.get("scan_date") or item.get("time") or item.get("timestamp") or item.get("event_time")),
                        "activity": source_text(item.get("activity") or item.get("status") or item.get("current_status") or item.get("description")),
                        "location": source_text(item.get("location") or item.get("scan_location") or item.get("current_location")),
                    }
                )
    return [scan for scan in scans if scan["date"] or scan["activity"] or scan["location"]]


def payload_lists(payload, *keys):
    lists = []
    if not isinstance(payload, dict):
        return lists
    for container in payload_containers(payload):
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                lists.append(value)
    return lists


def unique_tracking_rows(rows):
    unique = []
    seen = set()
    for row in rows:
        key = (row.get("date") or "", row.get("activity") or "", row.get("location") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return sorted(unique, key=lambda row: row.get("date") or "", reverse=True)


def tracking_progress_stage(status):
    normalized = str(status or "").strip().lower()
    if "deliver" in normalized and "undeliver" not in normalized and "rto" not in normalized:
        return "delivered"
    if "out for delivery" in normalized or "transit" in normalized or "hub" in normalized or "arrived" in normalized or "connected" in normalized:
        return "transit"
    if "ship" in normalized or "pickup" in normalized or "picked" in normalized or "manifest" in normalized:
        return "shipped"
    return "placed"


def push_shipping_status_updates(events):
    results = []
    for event in events:
        if not event.order:
            results.append({"event_id": event.id, "skipped": True, "message": "No matched warehouse order"})
            continue
        result = notify_shipping_status_change(event.order, event)
        result["event_id"] = event.id
        results.append(result)
        if not result.get("ok") and not result.get("skipped"):
            current_app.logger.warning("Customer shipping webhook failed for event %s: %s", event.id, result.get("message"))
    return results


def default_line_items(order=None, source=None):
    if not order:
        return [blank_line_item()]

    source_rows = source_items(source or {})
    items = []
    for index, item in enumerate(order.items):
        source_row = source_item_for_order_item(source_rows, item, index)
        unit_price = item.unit_price or item.product.selling_price or 0
        items.append(
            {
                "name": source_text(source_row.get("name") or source_row.get("product_name") or source_row.get("title")) or item.product.name,
                "sku": source_text(source_row.get("sku") or source_row.get("product_sku")) or item.product.sku,
                "units": str(item.quantity),
                "selling_price": decimal_to_input(source_row.get("selling_price") or source_row.get("unit_price") or source_row.get("price") or unit_price),
                "discount": decimal_to_input(source_row.get("discount") or 0),
                "tax": decimal_to_input(source_row.get("tax") or 0),
                "hsn": source_text(source_row.get("hsn") or source_row.get("hsn_code")),
            }
        )
    return items or [blank_line_item()]


def source_item_for_order_item(source_rows, item, index):
    if not source_rows:
        return {}
    sku = str(item.product.sku or "").strip().lower()
    for row in source_rows:
        row_sku = source_text(row.get("sku") or row.get("product_sku") or row.get("product")).lower()
        if row_sku and row_sku == sku:
            return row
    if index < len(source_rows):
        return source_rows[index]
    return {}


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
    order = Order.query.get(order_id)
    warehouse = selected_warehouse()
    if order and warehouse and order.warehouse_id != warehouse.id:
        return None
    return order


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


def shiprocket_label_url(order):
    payload = courier_response_payload(order)
    return response_value(payload, "label_url", "label", "label_url_s3", "url", "download_url")


def courier_response_payload(order):
    try:
        payload = json.loads(order.courier_response or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def merge_courier_response(order, extra):
    payload = courier_response_payload(order)
    payload.update(extra)
    order.courier_response = json.dumps(payload, default=str, separators=(",", ":"))[:20000]


def append_note(existing, note):
    rows = [str(existing or "").strip(), str(note or "").strip()]
    return "\n".join(row for row in rows if row)[:2000]


def trim_value(value, limit):
    cleaned = str(value or "").strip()
    return cleaned[:limit] if cleaned else None

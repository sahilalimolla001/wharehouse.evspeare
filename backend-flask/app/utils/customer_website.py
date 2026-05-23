import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app, url_for


def notify_product_change(product, event="product.saved"):
    webhook_url = current_app.config.get("CUSTOMER_PRODUCT_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return {"ok": False, "skipped": True, "message": "Customer product webhook is not configured"}

    payload = {
        "event": event,
        "source": "evsphere-warehouse",
        "feed_url": url_for("api.api_public_products", _external=True),
        "product": customer_product_payload(product),
    }
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Warehouse-Event": event,
    }
    token = current_app.config.get("CUSTOMER_PRODUCT_WEBHOOK_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(webhook_url, data=body, headers=headers, method="POST")
    timeout = current_app.config.get("CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT", 10)
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= response.status < 300, "skipped": False, "status": response.status, "message": response_body or "Customer website updated"}
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "skipped": False, "status": error.code, "message": f"Customer website webhook failed with HTTP {error.code}: {error_body}"}
    except URLError as error:
        return {"ok": False, "skipped": False, "message": f"Customer website webhook failed: {error.reason}"}
    except TimeoutError:
        return {"ok": False, "skipped": False, "message": "Customer website webhook timed out"}


def notify_shipping_status_change(order, event_record=None, event="shipping.status.updated"):
    webhook_url = current_app.config.get("CUSTOMER_SHIPPING_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return {"ok": False, "skipped": True, "message": "Customer shipping webhook is not configured"}

    payload = {
        "event": event,
        "source": "evsphere-warehouse",
        "order": customer_shipping_status_payload(order, event_record),
    }
    return post_customer_webhook(
        webhook_url,
        payload,
        event,
        current_app.config.get("CUSTOMER_SHIPPING_WEBHOOK_TOKEN", "").strip(),
        current_app.config.get("CUSTOMER_SHIPPING_WEBHOOK_TIMEOUT", current_app.config.get("CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT", 10)),
    )


def post_customer_webhook(webhook_url, payload, event, token="", timeout=10):
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Warehouse-Event": event,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(webhook_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= response.status < 300, "skipped": False, "status": response.status, "message": response_body or "Customer website updated"}
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "skipped": False, "status": error.code, "message": f"Customer website webhook failed with HTTP {error.code}: {error_body}"}
    except URLError as error:
        return {"ok": False, "skipped": False, "message": f"Customer website webhook failed: {error.reason}"}
    except TimeoutError:
        return {"ok": False, "skipped": False, "message": "Customer website webhook timed out"}


def customer_product_payload(product):
    image_url = url_for("api.api_public_product_image", product_id=product.id, _external=True) if product.image_url and product.is_active else None
    value = product.selling_price or product.purchase_price or 0
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "brand": product.brand or "",
        "description": product.description or "",
        "unit": product.unit,
        "purchase_price": float(product.purchase_price or 0),
        "selling_price": float(product.selling_price or 0),
        "value": float(value),
        "minimum_stock": product.minimum_stock,
        "total_quantity": product.total_quantity,
        "available_quantity": product.available_quantity,
        "in_stock": product.available_quantity > 0,
        "is_active": product.is_active,
        "image_url": image_url,
        "updated_at": product.updated_at.isoformat() + "Z" if product.updated_at else None,
    }


def customer_shipping_status_payload(order, event_record=None):
    return {
        "id": order.id,
        "website_order_id": order.external_order_id or order.order_number,
        "warehouse_order_number": order.order_number,
        "shiprocket_order_id": event_value(event_record, "shiprocket_order_id") or order.courier_order_id or "",
        "shiprocket_shipment_id": event_value(event_record, "shipment_id") or order.courier_shipment_id or "",
        "awb": event_value(event_record, "awb") or order.courier_awb or "",
        "latest_status": event_value(event_record, "current_status") or order.courier_status or order.status,
        "previous_status": event_value(event_record, "previous_status"),
        "status_code": event_value(event_record, "status_code"),
        "courier": event_value(event_record, "courier_name") or order.courier_provider or "",
        "location": event_value(event_record, "location"),
        "event_time": iso_datetime(getattr(event_record, "event_time", None)),
        "updated_at": iso_datetime(getattr(event_record, "created_at", None) or order.updated_at),
        "tracking_history": customer_shipping_tracking_history(order, event_record),
    }


def event_value(event_record, field):
    return str(getattr(event_record, field, "") or "").strip() if event_record else ""


def iso_datetime(value):
    return value.isoformat() + "Z" if value else None


def customer_shipping_tracking_history(order, event_record=None):
    events = []
    if event_record:
        events.append(event_record)
    events.extend(
        sorted(
            [event for event in getattr(order, "shiprocket_events", []) if not event_record or event.id != event_record.id],
            key=lambda event: (event.created_at, event.id),
            reverse=True,
        )
    )

    rows = []
    for event in events[:200]:
        scans = tracking_scans_from_event(event)
        if not scans:
            scans = [
                {
                    "date": event_value(event, "event_time") or event_value(event, "created_at"),
                    "activity": event_value(event, "current_status") or event_value(event, "event_type"),
                    "location": event_value(event, "location"),
                }
            ]
        rows.extend(scans)
    return unique_tracking_rows(rows)


def tracking_scans_from_event(event):
    try:
        payload = json.loads(getattr(event, "payload_json", "") or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    scans = []
    for value in payload_lists(payload, "scans", "scan", "activities", "tracking_history", "shipment_track_activities"):
        for item in value:
            if isinstance(item, dict):
                scans.append(
                    {
                        "date": text_value(item.get("date") or item.get("scan_date") or item.get("time") or item.get("timestamp") or item.get("event_time")),
                        "activity": text_value(item.get("activity") or item.get("status") or item.get("current_status") or item.get("description")),
                        "location": text_value(item.get("location") or item.get("scan_location") or item.get("current_location")),
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


def payload_containers(payload):
    containers = []
    if isinstance(payload, dict):
        containers.append(payload)
        for key in ("data", "shipment", "order", "tracking_data", "tracking", "payload"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.extend(payload_containers(value))
    return containers


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


def text_value(value):
    return str(value or "").strip()

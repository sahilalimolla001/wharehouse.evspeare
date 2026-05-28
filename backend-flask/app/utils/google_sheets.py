import json
import threading
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app
from sqlalchemy import event

from ..extensions import db
from .google_credentials import load_google_credentials


SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
SYNC_FLAG = "google_sheets_sync_required"
SYNC_REASON = "google_sheets_sync_reason"
SYNC_LOCK = threading.Lock()


def sheet_range(tab_name, columns="A:Z"):
    escaped_name = tab_name.replace("'", "''")
    return f"'{escaped_name}'!{columns}"


def append_rows_to_sheet(rows, range_name=None):
    if current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL"):
        return send_rows_to_apps_script(rows, range_name=range_name, mode="append")

    service = get_sheets_service()
    body = {"values": rows}
    target_range = range_name or current_app.config.get("GOOGLE_SHEETS_RANGE", "CurrentStock!A:H")
    return (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=current_app.config["GOOGLE_SHEETS_SPREADSHEET_ID"],
            range=target_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )


def write_rows_to_sheet(rows, range_name=None):
    if current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL"):
        return send_rows_to_apps_script(rows, range_name=range_name, mode="replace")

    service = get_sheets_service()
    target_range = range_name or current_app.config.get("GOOGLE_SHEETS_RANGE", "CurrentStock!A:H")
    spreadsheet_id = current_app.config["GOOGLE_SHEETS_SPREADSHEET_ID"]
    ensure_sheet_tab(service, spreadsheet_id, target_range)
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=target_range, body={}).execute()
    return (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=target_range,
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        )
        .execute()
    )


def get_sheets_service():
    spreadsheet_id = current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is not configured")

    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError("Google Sheets packages are not installed") from error

    credentials = load_google_credentials(current_app.config, SHEETS_SCOPE)

    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def ensure_sheet_tab(service, spreadsheet_id, range_name):
    tab_name = range_name.split("!", 1)[0].strip("'")
    if not tab_name:
        return

    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    existing_tabs = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
    if tab_name in existing_tabs:
        return

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
    ).execute()


def send_rows_to_apps_script(rows, range_name=None, mode="replace"):
    webhook_url = current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("GOOGLE_APPS_SCRIPT_WEBHOOK_URL is not configured")

    target_range = range_name or current_app.config.get("GOOGLE_SHEETS_RANGE", "CurrentStock!A:H")
    payload = {
        "range": target_range,
        "mode": mode,
        "rows": rows,
        "token": current_app.config.get("GOOGLE_APPS_SCRIPT_TOKEN", ""),
    }
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        if error.code == 403 and ("You need access" in error_body or "Access denied" in error_body):
            raise RuntimeError(
                "Apps Script access denied. Deploy it as a Web app with Execute as 'Me' and Who has access 'Anyone', then use the /exec Web App URL."
            ) from error
        raise RuntimeError(f"Apps Script sync failed with HTTP {error.code}: {error_body}") from error
    except URLError as error:
        raise RuntimeError(f"Apps Script sync failed: {error.reason}") from error

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Apps Script returned invalid JSON: {response_body}") from error

    if not result.get("ok"):
        raise RuntimeError(result.get("message") or "Apps Script sync failed")

    updated_range = result.get("updatedRange") or target_range
    return {"updatedRange": updated_range, "updates": {"updatedRange": updated_range}}


def format_google_sheets_error(error):
    message = str(error)
    if message.startswith("Google credentials are not configured"):
        return f"{message} Then share the Google Sheet with the service account email."
    if message.startswith("Apps Script"):
        return message

    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        HttpError = None

    if HttpError and isinstance(error, HttpError):
        status = getattr(error.resp, "status", None)
        reason = error._get_reason() if hasattr(error, "_get_reason") else str(error)
        if status in (401, 403):
            return "Google Sheets permission denied. Share the spreadsheet with the service account email and make sure the Google Sheets API is enabled."
        if status == 404:
            return "Google Sheet not found. Check GOOGLE_SHEETS_SPREADSHEET_ID and make sure the tab in GOOGLE_SHEETS_RANGE exists."
        if status == 400:
            return "Google Sheets rejected the range. Check GOOGLE_SHEETS_RANGE, for example Sheet1!A:H or CurrentStock!A:H."
        return f"Google Sheets API error {status}: {reason}"

    return message


def auto_sync_current_stock_sheet(reason="inventory_update"):
    if not current_app.config.get("GOOGLE_SHEETS_AUTO_SYNC", True):
        return {"ok": False, "skipped": True, "message": "Google Sheets auto-sync is disabled"}

    if not current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID") and not current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL"):
        return {"ok": False, "skipped": True, "message": "Google Sheets spreadsheet ID is not configured"}

    try:
        if current_app.config.get("GOOGLE_SHEETS_SYNC_MODE", "full").lower() == "current_stock":
            from ..models import Inventory, Product

            inventory_rows = Inventory.query.join(Product).order_by(Product.sku).all()
            result = write_rows_to_sheet(current_stock_sheet_rows(inventory_rows))
            updated_range = result.get("updatedRange") or result.get("updates", {}).get("updatedRange", "")
            return {"ok": True, "skipped": False, "message": f"Google Sheet synced after {reason}", "updated_range": updated_range}
        return sync_google_sheets_workbook(reason)
    except Exception as error:
        message = format_google_sheets_error(error)
        current_app.logger.warning("Google Sheets auto-sync failed after %s: %s", reason, message)
        return {"ok": False, "skipped": False, "message": message}


def current_stock_sheet_rows(inventory_rows):
    exported_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    rows = [["Exported At", "SKU", "Product", "Location", "Quantity", "Reserved", "Available", "Stock Value"]]
    for row in inventory_rows:
        rows.append(
            [
                exported_at,
                row.product.sku,
                row.product.name,
                row.location.full_code,
                row.quantity,
                row.reserved_quantity,
                row.available_quantity,
                float(row.product.purchase_price or 0) * row.quantity,
            ]
        )
    return rows


def sync_google_sheets_workbook(reason="data_update"):
    if not current_app.config.get("GOOGLE_SHEETS_AUTO_SYNC", True):
        return {"ok": False, "skipped": True, "message": "Google Sheets auto-sync is disabled"}

    if not current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID") and not current_app.config.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL"):
        return {"ok": False, "skipped": True, "message": "Google Sheets spreadsheet ID is not configured"}

    updated_ranges = []
    for tab_name, rows in google_sheets_workbook_rows().items():
        result = write_rows_to_sheet(rows, sheet_range(tab_name))
        updated_ranges.append(result.get("updatedRange") or result.get("updates", {}).get("updatedRange", tab_name))
    return {
        "ok": True,
        "skipped": False,
        "message": f"Full Google Sheet workbook synced after {reason}",
        "updated_range": ", ".join(updated_ranges),
    }


def google_sheets_workbook_rows():
    from ..models import (
        ActivityLog,
        Barcode,
        Category,
        CustomerReturnItem,
        CustomerReturnOrder,
        Inventory,
        Invoice,
        ItemNotFoundReport,
        MoneyTransaction,
        Order,
        OrderItem,
        PaymentRefund,
        Product,
        ShiprocketWebhookEvent,
        StockIn,
        StockOut,
        Supplier,
        User,
        Warehouse,
        WarehouseLocation,
    )

    return {
        "Users": users_sheet_rows(User.query.order_by(User.full_name).all()),
        "Warehouses": warehouses_sheet_rows(Warehouse.query.order_by(Warehouse.code).all()),
        "Suppliers": suppliers_sheet_rows(Supplier.query.order_by(Supplier.name).all()),
        "Categories": categories_sheet_rows(Category.query.order_by(Category.name).all()),
        "Products": products_sheet_rows(Product.query.order_by(Product.sku).all()),
        "Barcodes": barcodes_sheet_rows(Barcode.query.order_by(Barcode.id).all()),
        "Locations": locations_sheet_rows(WarehouseLocation.query.join(Warehouse).order_by(Warehouse.code, WarehouseLocation.zone, WarehouseLocation.rack, WarehouseLocation.shelf, WarehouseLocation.bin_code).all()),
        "CurrentStock": current_stock_sheet_rows(Inventory.query.join(Product).order_by(Product.sku).all()),
        "StockIn": stock_in_sheet_rows(StockIn.query.order_by(StockIn.received_at.desc(), StockIn.id.desc()).all()),
        "StockOut": stock_out_sheet_rows(StockOut.query.order_by(StockOut.dispatched_at.desc(), StockOut.id.desc()).all()),
        "Orders": orders_sheet_rows(Order.query.order_by(Order.created_at.desc(), Order.id.desc()).all()),
        "OrderItems": order_items_sheet_rows(OrderItem.query.order_by(OrderItem.id.desc()).all()),
        "ShiprocketEvents": shiprocket_events_sheet_rows(ShiprocketWebhookEvent.query.order_by(ShiprocketWebhookEvent.created_at.desc(), ShiprocketWebhookEvent.id.desc()).all()),
        "Returns": returns_sheet_rows(CustomerReturnOrder.query.order_by(CustomerReturnOrder.requested_at.desc(), CustomerReturnOrder.id.desc()).all()),
        "ReturnItems": return_items_sheet_rows(CustomerReturnItem.query.order_by(CustomerReturnItem.id.desc()).all()),
        "Refunds": refunds_sheet_rows(PaymentRefund.query.order_by(PaymentRefund.requested_at.desc(), PaymentRefund.id.desc()).all()),
        "MoneyTransactions": money_sheet_rows(MoneyTransaction.query.order_by(MoneyTransaction.created_at.desc(), MoneyTransaction.id.desc()).all()),
        "Invoices": invoices_sheet_rows(Invoice.query.order_by(Invoice.issued_at.desc(), Invoice.id.desc()).all()),
        "ItemNotFound": item_not_found_sheet_rows(ItemNotFoundReport.query.order_by(ItemNotFoundReport.created_at.desc(), ItemNotFoundReport.id.desc()).all()),
        "ActivityLog": activity_sheet_rows(ActivityLog.query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(5000).all()),
    }


def exported_at():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def date_value(value):
    return value.isoformat() if value else ""


def money_value(value):
    return float(value or 0)


def users_sheet_rows(rows):
    data = [["Exported At", "ID", "Name", "Email", "Phone", "Role", "Picker Code", "Active", "Warehouses", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.full_name, row.email, row.phone or "", row.role, row.picker_code or "", row.is_active, ", ".join(warehouse.code for warehouse in row.warehouses), dt(row.created_at), dt(row.updated_at)])
    return data


def warehouses_sheet_rows(rows):
    data = [["Exported At", "ID", "Code", "Name", "Pincode", "Address", "Active", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.code, row.name, row.pincode, row.address or "", row.is_active, dt(row.created_at), dt(row.updated_at)])
    return data


def suppliers_sheet_rows(rows):
    data = [["Exported At", "ID", "Name", "Phone", "Email", "GST", "Address", "Notes", "Active", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.name, row.phone or "", row.email or "", row.gst_number or "", row.address or "", row.notes or "", row.is_active, dt(row.created_at), dt(row.updated_at)])
    return data


def categories_sheet_rows(rows):
    data = [["Exported At", "ID", "Name", "Description", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.name, row.description or "", dt(row.created_at), dt(row.updated_at)])
    return data


def products_sheet_rows(rows):
    data = [["Exported At", "ID", "SKU", "Name", "Brand", "Unit", "Category", "Supplier", "Purchase Price", "Selling Price", "Minimum Stock", "Total Quantity", "Available Quantity", "Stock Value", "Image URL", "Active", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.sku, row.name, row.brand or "", row.unit, row.category.name if row.category else "", row.supplier.name if row.supplier else "", money_value(row.purchase_price), money_value(row.selling_price), row.minimum_stock, row.total_quantity, row.available_quantity, money_value(row.stock_value), row.image_url or "", row.is_active, dt(row.created_at), dt(row.updated_at)])
    return data


def barcodes_sheet_rows(rows):
    data = [["Exported At", "ID", "Product ID", "SKU", "Product", "Code", "Type", "Active", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.product_id, row.product.sku if row.product else "", row.product.name if row.product else "", row.code, row.barcode_type, row.is_active, dt(row.created_at), dt(row.updated_at)])
    return data


def locations_sheet_rows(rows):
    data = [["Exported At", "ID", "Warehouse", "Warehouse Name", "Zone", "Rack", "Shelf", "Bin", "Full Code", "Barcode", "Virtual", "Active", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.warehouse.code if row.warehouse else "", row.warehouse.name if row.warehouse else "", row.zone, row.rack, row.shelf, row.bin_code, row.full_code, row.barcode or "", row.is_virtual, row.is_active, dt(row.created_at), dt(row.updated_at)])
    return data


def stock_in_sheet_rows(rows):
    data = [["Exported At", "ID", "Received At", "SKU", "Product", "Supplier", "Warehouse", "Location", "Quantity", "Unit Cost", "Invoice Number", "Received By", "Notes", "Created At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, dt(row.received_at), row.product.sku if row.product else "", row.product.name if row.product else "", row.supplier.name if row.supplier else "", row.location.warehouse.code if row.location and row.location.warehouse else "", row.location.full_code if row.location else "", row.quantity, money_value(row.unit_cost), row.invoice_number or "", row.received_by.full_name if row.received_by else "", row.notes or "", dt(row.created_at)])
    return data


def stock_out_sheet_rows(rows):
    data = [["Exported At", "ID", "Dispatched At", "SKU", "Product", "Order Number", "Warehouse", "Location", "Quantity", "Reason", "Dispatched By", "Notes", "Created At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, dt(row.dispatched_at), row.product.sku if row.product else "", row.product.name if row.product else "", row.order.order_number if row.order else "", row.location.warehouse.code if row.location and row.location.warehouse else "", row.location.full_code if row.location else "", row.quantity, row.reason, row.dispatched_by.full_name if row.dispatched_by else "", row.notes or "", dt(row.created_at)])
    return data


def orders_sheet_rows(rows):
    data = [["Exported At", "ID", "Order Number", "External Source", "External Order ID", "Warehouse", "Customer", "Phone", "Address", "Status", "Priority", "Assigned To", "Created By", "Expected Dispatch", "Completed At", "Courier", "Courier Order ID", "Shipment ID", "AWB", "Courier Status", "Total Items", "Total Value", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.order_number, row.external_source or "", row.external_order_id or "", row.warehouse.code if row.warehouse else "", row.customer_name, row.customer_phone or "", row.customer_address or "", row.status, row.priority, row.assigned_to.full_name if row.assigned_to else "", row.created_by.full_name if row.created_by else "", date_value(row.expected_dispatch_date), dt(row.completed_at), row.courier_provider or "", row.courier_order_id or "", row.courier_shipment_id or "", row.courier_awb or "", row.courier_status or "", row.total_items, money_value(row.total_value), dt(row.created_at), dt(row.updated_at)])
    return data


def order_items_sheet_rows(rows):
    data = [["Exported At", "ID", "Order Number", "SKU", "Product", "Quantity", "Picked", "Packed", "Unit Price", "Line Total", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.order.order_number if row.order else "", row.product.sku if row.product else "", row.product.name if row.product else "", row.quantity, row.picked_quantity, row.packed_quantity, money_value(row.unit_price), money_value(row.unit_price) * row.quantity, dt(row.created_at), dt(row.updated_at)])
    return data


def shiprocket_events_sheet_rows(rows):
    data = [["Exported At", "ID", "Order Number", "Event Type", "Shiprocket Order ID", "Shipment ID", "AWB", "Current Status", "Previous Status", "Status Code", "Courier", "Location", "Event Time", "Received IP", "Created At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.order.order_number if row.order else "", row.event_type or "", row.shiprocket_order_id or "", row.shipment_id or "", row.awb or "", row.current_status or "", row.previous_status or "", row.status_code or "", row.courier_name or "", row.location or "", dt(row.event_time), row.received_ip or "", dt(row.created_at)])
    return data


def returns_sheet_rows(rows):
    data = [["Exported At", "ID", "Return Number", "Order Number", "Website Order ID", "Customer", "Phone", "Reason", "Status", "Refund Status", "Assigned To", "Approved By", "Notes", "Requested At", "Resolved At", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.return_number, row.order.order_number if row.order else "", row.website_order_id or "", row.customer_name, row.customer_phone or "", row.reason, row.status, row.refund_status, row.assigned_to.full_name if row.assigned_to else "", row.approved_by.full_name if row.approved_by else "", row.notes or "", dt(row.requested_at), dt(row.resolved_at), dt(row.created_at), dt(row.updated_at)])
    return data


def return_items_sheet_rows(rows):
    data = [["Exported At", "ID", "Return Number", "SKU", "Product", "Expected", "Picked", "Stocked", "Issue Qty", "Status", "Notes", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.return_order.return_number if row.return_order else "", row.product.sku if row.product else "", row.product.name if row.product else "", row.expected_quantity, row.picked_quantity, row.stocked_quantity, row.issue_quantity, row.status, row.notes or "", dt(row.created_at), dt(row.updated_at)])
    return data


def refunds_sheet_rows(rows):
    data = [["Exported At", "ID", "Refund Number", "Order Number", "Website Order ID", "Request ID", "Customer", "Phone", "Gateway", "Gateway Payment ID", "Gateway Transaction ID", "Amount", "Currency", "Reason", "Status", "Requested At", "Approved At", "Approved By", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.refund_number, row.order.order_number if row.order else "", row.website_order_id or "", row.request_id or "", row.customer_name, row.customer_phone or "", row.gateway, row.gateway_payment_id or "", row.gateway_transaction_id or "", money_value(row.amount), row.currency, row.reason or "", row.status, dt(row.requested_at), dt(row.approved_at), row.approved_by.full_name if row.approved_by else "", dt(row.created_at), dt(row.updated_at)])
    return data


def money_sheet_rows(rows):
    data = [["Exported At", "ID", "Transaction Number", "Warehouse", "Order Number", "Refund Number", "Invoice Number", "Type", "Direction", "Status", "Gateway", "Reference", "Amount", "Currency", "Customer", "Phone", "Notes", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.transaction_number, row.warehouse.code if row.warehouse else "", row.order.order_number if row.order else "", row.refund.refund_number if row.refund else "", row.invoice.invoice_number if row.invoice else "", row.transaction_type, row.direction, row.status, row.gateway or "", row.reference or "", money_value(row.amount), row.currency, row.customer_name or "", row.customer_phone or "", row.notes or "", dt(row.created_at), dt(row.updated_at)])
    return data


def invoices_sheet_rows(rows):
    data = [["Exported At", "ID", "Invoice Number", "Order Number", "Type", "Status", "Customer", "Phone", "Amount", "Currency", "Issued At", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.invoice_number, row.order.order_number if row.order else "", row.invoice_type, row.status, row.customer_name, row.customer_phone or "", money_value(row.amount), row.currency, dt(row.issued_at), dt(row.created_at), dt(row.updated_at)])
    return data


def item_not_found_sheet_rows(rows):
    data = [["Exported At", "ID", "Order Number", "SKU", "Product", "Warehouse", "Location", "Picker", "Quantity", "Stock Deducted", "Unit Price", "Amount", "Notes", "Created At", "Updated At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.order.order_number if row.order else "", row.product.sku if row.product else "", row.product.name if row.product else "", row.warehouse.code if row.warehouse else "", row.location.full_code if row.location else "", row.picker.full_name if row.picker else "", row.quantity, row.stock_deducted_quantity, money_value(row.unit_price), money_value(row.unit_price) * row.quantity, row.notes or "", dt(row.created_at), dt(row.updated_at)])
    return data


def activity_sheet_rows(rows):
    data = [["Exported At", "ID", "User", "Action", "Entity Type", "Entity ID", "Message", "Meta JSON", "Created At"]]
    stamp = exported_at()
    for row in rows:
        data.append([stamp, row.id, row.user.full_name if row.user else "", row.action, row.entity_type or "", row.entity_id or "", row.message, row.meta_json or "", dt(row.created_at)])
    return data


def register_google_sheets_auto_sync(app):
    if app.config.get("_GOOGLE_SHEETS_AUTO_SYNC_EVENTS_REGISTERED"):
        return
    app.config["_GOOGLE_SHEETS_AUTO_SYNC_EVENTS_REGISTERED"] = True

    @event.listens_for(db.session, "before_flush")
    def mark_google_sheets_sync(session, flush_context, instances):
        if not current_app.config.get("GOOGLE_SHEETS_AUTO_SYNC", True):
            return
        if has_syncable_change(session.new) or has_syncable_change(session.dirty) or has_syncable_change(session.deleted):
            session.info[SYNC_FLAG] = True
            session.info[SYNC_REASON] = "database_commit"

    @event.listens_for(db.session, "after_commit")
    def sync_google_sheets_after_commit(session):
        if not session.info.pop(SYNC_FLAG, False):
            return
        reason = session.info.pop(SYNC_REASON, "database_commit")
        worker = threading.Thread(target=sync_google_sheets_in_app_context, args=(app, reason), daemon=True)
        worker.start()

    @event.listens_for(db.session, "after_rollback")
    def clear_google_sheets_sync_flag(session):
        session.info.pop(SYNC_FLAG, None)
        session.info.pop(SYNC_REASON, None)


def has_syncable_change(rows):
    from ..models import (
        ActivityLog,
        Barcode,
        Category,
        CustomerReturnItem,
        CustomerReturnOrder,
        Inventory,
        Invoice,
        ItemNotFoundReport,
        MoneyTransaction,
        Order,
        OrderItem,
        PaymentRefund,
        Product,
        ShiprocketWebhookEvent,
        StockIn,
        StockOut,
        Supplier,
        User,
        Warehouse,
        WarehouseLocation,
    )

    syncable_models = (
        ActivityLog,
        Barcode,
        Category,
        CustomerReturnItem,
        CustomerReturnOrder,
        Inventory,
        Invoice,
        ItemNotFoundReport,
        MoneyTransaction,
        Order,
        OrderItem,
        PaymentRefund,
        Product,
        ShiprocketWebhookEvent,
        StockIn,
        StockOut,
        Supplier,
        User,
        Warehouse,
        WarehouseLocation,
    )
    return any(isinstance(row, syncable_models) for row in rows)


def sync_google_sheets_in_app_context(app, reason):
    with SYNC_LOCK:
        with app.app_context():
            try:
                result = auto_sync_current_stock_sheet(reason)
                if not result.get("ok") and not result.get("skipped"):
                    app.logger.warning("Google Sheets auto-sync failed after commit: %s", result.get("message"))
            finally:
                db.session.remove()

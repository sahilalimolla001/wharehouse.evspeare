import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from .google_credentials import load_google_credentials


SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]


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
        from ..models import Inventory, Product

        inventory_rows = Inventory.query.join(Product).order_by(Product.sku).all()
        result = write_rows_to_sheet(current_stock_sheet_rows(inventory_rows))
        updated_range = result.get("updatedRange") or result.get("updates", {}).get("updatedRange", "")
        return {"ok": True, "skipped": False, "message": f"Google Sheet synced after {reason}", "updated_range": updated_range}
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

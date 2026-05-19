# pgAdmin, Google Cloud Storage, and Google Sheets Setup

## PostgreSQL URL In pgAdmin

Your Flask app reads PostgreSQL from:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
```

If your password has special characters like `@`, `#`, `:`, `/`, or space, the app will URL-encode it automatically. For pgAdmin, paste the original password normally.

pgAdmin does not save a full URL in one box. Add a new server and copy the URL parts:

```text
Host name/address: HOST
Port: 5432
Maintenance database: DBNAME
Username: USER
Password: PASSWORD
```

You can print these fields from the project:

```powershell
cd backend-flask
python -m flask --app run.py pgadmin-info
```

If Windows opens the Microsoft Store alias for `python`, use your real Python path or `py`.

## Google Cloud Storage

1. Create a Google Cloud project.
2. Enable Cloud Storage.
3. Create a bucket.
4. Create a service account and download its JSON key.
5. Give the service account Storage Object Admin permission on the bucket.
6. Set environment variables:

```text
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
GOOGLE_APPLICATION_CREDENTIALS_JSON=
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_STORAGE_BUCKET=your-bucket-name
GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX=products
GOOGLE_CLOUD_STORAGE_PUBLIC=false
```

For hosting providers where a JSON file path is not convenient, set `GOOGLE_APPLICATION_CREDENTIALS_JSON` to the raw service-account JSON or base64-encoded JSON instead of using `GOOGLE_APPLICATION_CREDENTIALS`.

Product image uploads from `/add-product` will now go to Google Cloud Storage and save a `gs://...` URL. If your bucket is public and you set `GOOGLE_CLOUD_STORAGE_PUBLIC=true`, the app saves a public HTTPS URL. Put SKU-named product images under `GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX` to import them from the Products page.

Check the connection:

```powershell
cd backend-flask
python -m flask --app run.py test-google-storage
```

## Google Sheets Reports With Apps Script

This is the easiest option for Google Sheet sync. It does not need a service-account JSON key.

1. Open your Google Sheet.
2. Create a tab named `Sheet1`, or change `GOOGLE_SHEETS_RANGE` to your tab name.
3. Go to Extensions > Apps Script.
4. Paste this code:

```javascript
const SECRET_TOKEN = "change-this-token";

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || "{}");
    if (SECRET_TOKEN && payload.token !== SECRET_TOKEN) {
      return jsonResponse({ ok: false, message: "Invalid token" });
    }

    const rangeName = payload.range || "Sheet1!A:H";
    const sheetName = rangeName.split("!")[0].replace(/^'|'$/g, "");
    const rows = payload.rows || [];
    const mode = payload.mode || "replace";
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = spreadsheet.getSheetByName(sheetName) || spreadsheet.insertSheet(sheetName);

    if (mode === "replace") {
      sheet.clearContents();
      if (rows.length) {
        sheet.getRange(1, 1, rows.length, rows[0].length).setValues(rows);
      }
    } else {
      if (rows.length) {
        sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
      }
    }

    return jsonResponse({
      ok: true,
      updatedRange: sheetName + "!A1:H" + Math.max(rows.length, 1),
    });
  } catch (error) {
    return jsonResponse({ ok: false, message: String(error) });
  }
}

function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
```

5. Click Deploy > New deployment > Web app.
6. Set **Execute as** to **Me**.
7. Set **Who has access** to **Anyone**.
8. Copy the Web App URL.
9. Set environment variables:

```text
GOOGLE_SHEETS_SPREADSHEET_ID=your-sheet-id
GOOGLE_SHEETS_RANGE=Sheet1!A:H
GOOGLE_SHEETS_AUTO_SYNC=true
GOOGLE_APPS_SCRIPT_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
GOOGLE_APPS_SCRIPT_TOKEN=change-this-token
```

After stock in, stock out, or mobile location update, the app automatically refreshes that tab with the latest inventory. You can also open `/reports` and click **Sync Google Sheet Now**.

If `GOOGLE_APPS_SCRIPT_WEBHOOK_URL` is empty, the app falls back to the service-account Google Sheets API setup.

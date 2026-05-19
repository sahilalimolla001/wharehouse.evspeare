# Deploy On Render

This project is ready for Render Blueprint deployment from the repository root.

## 1. Prepare GitHub

Do not commit real `.env` files. The root `.gitignore` already excludes them.

```powershell
cd "C:\Users\DELL\OneDrive\evspere wherehouse"
git init
git add .
git status
git commit -m "Prepare warehouse app for production deploy"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

If `git status` shows `backend-flask/.env`, `backend-flask/env-backup/`, a service-account JSON, or any private key, stop and remove it from Git before pushing.

## 2. Create Render Blueprint

1. Open Render Dashboard.
2. Click `New` > `Blueprint`.
3. Connect the GitHub repository.
4. Use the default Blueprint path: `render.yaml`.
5. Render will create:
   - `evsphere-warehouse-backend`
   - `evsphere-warehouse-mobile`
   - `evsphere-warehouse-db`

## 3. Fill Required Environment Values

During Blueprint creation, Render asks for values marked `sync: false`.

Required:

```text
API_ALLOWED_ORIGINS=https://evsphere-warehouse-mobile.onrender.com,https://evsphere-warehouse-backend.onrender.com
ADMIN_EMAIL=owner@your-company.com
ADMIN_PASSWORD=use-a-strong-password
ADMIN_NAME=Owner Admin
INTEGRATION_API_KEY=use-a-strong-random-api-key
WAREHOUSE_API_BASE=https://evsphere-warehouse-backend.onrender.com/api
```

If Render changes the service URLs because the names are taken, use the final URLs Render shows in the dashboard.

Optional, but needed for uploads/sheets:

```text
GOOGLE_APPLICATION_CREDENTIALS_JSON=your-service-account-json-or-base64-json
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_STORAGE_BUCKET=your-bucket-name
GOOGLE_SHEETS_SPREADSHEET_ID=your-sheet-id
GOOGLE_APPS_SCRIPT_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
GOOGLE_APPS_SCRIPT_TOKEN=strong-random-token
```

## 4. First Deploy

The backend pre-deploy command runs:

```text
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
```

The first deploy hook runs:

```text
python -m flask --app run.py init-db
```

That creates the first admin from `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

## 5. After Deploy

Open:

```text
https://evsphere-warehouse-backend.onrender.com/login
https://evsphere-warehouse-mobile.onrender.com
```

Then test:

1. Admin login.
2. Add a manager/staff user.
3. Product, supplier, location, stock-in, stock-out.
4. Mobile app login with a staff user.
5. Order picking, packing, dispatch.

## 6. Send Orders From Another Website

Use server-to-server API calls. Do not put `INTEGRATION_API_KEY` in browser JavaScript.

Endpoint:

```text
POST https://evsphere-warehouse-backend.onrender.com/api/integrations/orders
Authorization: Bearer YOUR_INTEGRATION_API_KEY
Content-Type: application/json
```

Example body:

```json
{
  "source": "shopify",
  "external_order_id": "100045",
  "order_number": "SHOP-100045",
  "customer_name": "Rahul Sharma",
  "customer_phone": "+91 90000 00000",
  "customer_address": "Delhi, India",
  "priority": "normal",
  "items": [
    {
      "sku": "SKU-1001",
      "quantity": 2,
      "unit_price": 2400
    }
  ]
}
```

The same `source` + `external_order_id` can be posted again safely; the API returns the existing order instead of creating a duplicate.

## 7. Commercial Notes

- The Blueprint uses a paid Postgres plan (`basic-256mb`) because commercial warehouse data needs backups.
- Do not run `seed-demo` on production.
- Use custom domains before sharing with staff.
- Update `API_ALLOWED_ORIGINS` and `WAREHOUSE_API_BASE` if you add custom domains.
- Keep `ALLOW_INSECURE_USER_HEADER=false`.

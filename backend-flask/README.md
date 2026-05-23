# Backend Flask

Common backend for admin website and mobile warehouse app.

## Local Setup

```powershell
cd backend-flask
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m flask --app run.py db upgrade
python -m flask --app run.py seed-demo
python -m flask --app run.py run
```

Open:

- Admin website: `http://127.0.0.1:5000/login`
- API health: `http://127.0.0.1:5000/api/health`

Demo login:

```text
admin@warehouse.local
admin123
```

## PostgreSQL

Set this environment variable before running:

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"
```

Without `DATABASE_URL`, local SQLite is used for development.

## Database Migrations

After changing models, create and apply a migration:

```powershell
python -m flask --app run.py db migrate -m "Describe schema change"
python -m flask --app run.py db upgrade
```

If an existing database was already created with `init-db`, stamp it once before using future migrations:

```powershell
python -m flask --app run.py db stamp head
```

## Roles And Access

- `admin`: full access, including users and settings.
- `manager`: products, suppliers, stock, locations, orders, and reports.
- `staff`: stock in/out, inventory, locations, orders, and mobile warehouse APIs.
- `picker`: assigned order picking and stock movement APIs.
- `packer`: assigned order packing APIs.
- `delivery`: assigned order dispatch/status APIs.

## Render Hosting

For the easiest production deploy, use the root-level Blueprint:

```text
../render.yaml
../DEPLOY_RENDER.md
```

If creating only the backend as a manual Web Service, set Root Directory to `backend-flask`.

Build command:

```text
pip install -r requirements.txt
```

Pre-deploy command:

```text
python -m flask --app run.py validate-production && python -m flask --app run.py db upgrade
```

Start command:

```text
gunicorn --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile - run:app
```

Environment variables:

```text
APP_ENV=production
FLASK_DEBUG=false
SECRET_KEY=your-strong-random-secret
DATABASE_URL=postgresql://...
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=Lax
TRUST_PROXY_HEADERS=true
API_ALLOWED_ORIGINS=https://your-admin-domain.com,https://your-mobile-domain.com
ALLOW_INSECURE_USER_HEADER=false
INTEGRATION_API_KEY=strong-random-integration-key
ADMIN_EMAIL=owner@your-company.com
ADMIN_PASSWORD=strong-initial-admin-password
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-service-account.json
GOOGLE_APPLICATION_CREDENTIALS_JSON=
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_STORAGE_BUCKET=your-bucket-name
GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX=products
GOOGLE_CLOUD_STORAGE_PUBLIC=false
GOOGLE_SHEETS_SPREADSHEET_ID=your-sheet-id
GOOGLE_SHEETS_RANGE=Sheet1!A:H
GOOGLE_SHEETS_AUTO_SYNC=true
GOOGLE_APPS_SCRIPT_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
GOOGLE_APPS_SCRIPT_TOKEN=change-this-token
CUSTOMER_PRODUCT_WEBHOOK_URL=https://your-customer-website.com/api/warehouse/products
CUSTOMER_PRODUCT_WEBHOOK_TOKEN=strong-shared-secret
CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT=10
CUSTOMER_SHIPPING_WEBHOOK_URL=https://your-customer-website.com/api/warehouse/shipping-status
CUSTOMER_SHIPPING_WEBHOOK_TOKEN=strong-shared-secret
CUSTOMER_SHIPPING_WEBHOOK_TIMEOUT=10
SHIPROCKET_API_BASE_URL=https://apiv2.shiprocket.in/v1/external
SHIPROCKET_EMAIL=shiprocket-api-user@example.com
SHIPROCKET_PASSWORD=strong-shiprocket-api-password
SHIPROCKET_TOKEN=
SHIPROCKET_PICKUP_LOCATION=Primary
SHIPROCKET_CHANNEL_ID=
SHIPROCKET_WEBHOOK_TOKEN=strong-random-webhook-token
SHIPROCKET_DEFAULT_LENGTH_CM=10
SHIPROCKET_DEFAULT_BREADTH_CM=10
SHIPROCKET_DEFAULT_HEIGHT_CM=10
SHIPROCKET_DEFAULT_WEIGHT_KG=0.5
```

Before accepting real warehouse data:

```powershell
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
python -m flask --app run.py init-db
```

Do not run `seed-demo` against a real production database. `init-db` creates the first admin from `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

To create or reset a mobile picker/staff login from environment variables:

```powershell
python -m flask --app run.py create-staff
```

Set `STAFF_EMAIL`, `STAFF_PASSWORD`, `STAFF_NAME`, and `STAFF_ROLE=picker` before running it.

For Google Sheet sync, `GOOGLE_APPS_SCRIPT_WEBHOOK_URL` is the simplest option. If it is empty, the app falls back to the service-account Google Sheets API setup. Use either `GOOGLE_APPLICATION_CREDENTIALS` for a local JSON key file, or `GOOGLE_APPLICATION_CREDENTIALS_JSON` for raw/base64 service-account JSON in hosted environments.

To test Google Cloud Storage locally:

```powershell
python -m flask --app run.py test-google-storage
```

## Shiprocket Courier Orders

Set `SHIPROCKET_EMAIL` and `SHIPROCKET_PASSWORD` to the API user created in Shiprocket, then set `SHIPROCKET_PICKUP_LOCATION` to the pickup location name from your Shiprocket account. `SHIPROCKET_TOKEN` is optional and only useful when you want to provide a temporary token yourself.

After running migrations, open the admin page:

```text
/shiprocket
```

You can load an existing warehouse order, fill the required billing/shipping pincode, city, state, package dimensions, and create the Shiprocket courier order. The returned Shiprocket order ID, shipment ID, AWB, and status are saved back on the warehouse order when a local order is selected.

When orders are imported through `/api/integrations/orders`, the app reads `payment_method`, `billing_address`, `shipping_address`, and `items` from the saved source payload. After picking/packing, the mobile Ship page asks only for package length, breadth, height, and weight; submitting Dispatch automatically creates the Shiprocket courier order and marks the warehouse order as dispatched.

For real-time tracking updates, open:

```text
/shiprocket/webhooks
```

Copy the generated webhook URL into Shiprocket under Settings > API > Webhooks. Use `SHIPROCKET_WEBHOOK_TOKEN` and keep the token in the URL query string so incoming webhook calls can be verified. Incoming updates are stored in `shiprocket_webhook_events`; when an update matches an existing warehouse order by Shiprocket order ID, shipment ID, AWB, or order number, the order's courier status is refreshed automatically.

Open `/shipping-status` for the live shipping table. Shiprocket order ID, AWB, latest status, and courier are read from the latest Shiprocket webhook event first, with saved order courier fields as fallback. Set `CUSTOMER_SHIPPING_WEBHOOK_URL` to push each matched Shiprocket status update to your customer app.

For pgAdmin and Google setup, see `PGADMIN_GOOGLE_SETUP.md`.

## API Routes For Mobile

- `GET /api/public/products`
- `GET /api/public/products/<id>/image`
- `POST /api/login`
- `GET /api/dashboard`
- `GET /api/products`
- `GET /api/scan/<code>`
- `GET /api/locations`
- `GET /api/location-inventory/<location-code-or-id>`
- `POST /api/stock-in`
- `POST /api/stock-out`
- `POST /api/location-update`
- `GET /api/pick-list`
- `POST /api/orders/<id>/status`
- `POST /api/integrations/orders`

External order import details are in `INTEGRATION_API.md`.

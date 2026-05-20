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
```

Before accepting real warehouse data:

```powershell
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
python -m flask --app run.py init-db
```

Do not run `seed-demo` against a real production database. `init-db` creates the first admin from `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

For Google Sheet sync, `GOOGLE_APPS_SCRIPT_WEBHOOK_URL` is the simplest option. If it is empty, the app falls back to the service-account Google Sheets API setup. Use either `GOOGLE_APPLICATION_CREDENTIALS` for a local JSON key file, or `GOOGLE_APPLICATION_CREDENTIALS_JSON` for raw/base64 service-account JSON in hosted environments.

To test Google Cloud Storage locally:

```powershell
python -m flask --app run.py test-google-storage
```

For pgAdmin and Google setup, see `PGADMIN_GOOGLE_SETUP.md`.

## API Routes For Mobile

- `GET /api/public/products`
- `GET /api/public/products/<id>/image`
- `POST /api/login`
- `GET /api/dashboard`
- `GET /api/products`
- `GET /api/scan/<code>`
- `GET /api/locations`
- `POST /api/stock-in`
- `POST /api/stock-out`
- `POST /api/location-update`
- `GET /api/pick-list`
- `POST /api/orders/<id>/status`
- `POST /api/integrations/orders`

External order import details are in `INTEGRATION_API.md`.

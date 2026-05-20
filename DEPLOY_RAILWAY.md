# Deploy On Railway

This repository is ready for Railway with two services:

- `warehouse-backend`: Flask admin site and API from `backend-flask`
- `warehouse-mobile`: staff PWA from `mobile-app`
- `Postgres`: Railway PostgreSQL database

## 1. Push To GitHub

Do not commit real `.env` files or service-account JSON files. They are already ignored.

```powershell
cd "C:\Users\DELL\OneDrive\evspere wherehouse"
git add .
git commit -m "Prepare warehouse app for Railway deploy"
git push
```

## 2. Create Railway Project

1. Open Railway and create a new project from the GitHub repository.
2. Add a PostgreSQL database service. Keep the service name as `Postgres`, or update the references below.
3. Add a backend service from the same repository:
   - Service name: `warehouse-backend`
   - Root Directory: `/backend-flask`
   - Config File: `/backend-flask/railway.json`
4. Add a mobile service from the same repository:
   - Service name: `warehouse-mobile`
   - Root Directory: `/mobile-app`
   - Config File: `/mobile-app/railway.json`
   - Builder: Dockerfile
   - Build Command: leave empty
   - Start Command: leave empty

The backend config runs migrations, creates or updates the admin from `ADMIN_EMAIL` and `ADMIN_PASSWORD`, starts Gunicorn on Railway's `$PORT`, and checks `/api/health`.
Run `validate-production` manually after domains and variables are final. Keeping it out of Railway's pre-deploy step prevents first deploy failures while public domains are still being created.

## 3. Backend Variables

Open `warehouse-backend` -> Variables -> Raw Editor and add:

```text
APP_ENV=production
FLASK_DEBUG=false
SECRET_KEY=replace-with-a-strong-random-secret-at-least-32-chars
DATABASE_URL=${{Postgres.DATABASE_URL}}
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=None
TRUST_PROXY_HEADERS=true
API_ALLOWED_ORIGINS=https://${{warehouse-mobile.RAILWAY_PUBLIC_DOMAIN}},https://${{warehouse-backend.RAILWAY_PUBLIC_DOMAIN}}
ALLOW_INSECURE_USER_HEADER=false
INTEGRATION_API_KEY=replace-with-a-strong-random-integration-key
ADMIN_EMAIL=owner@your-company.com
ADMIN_PASSWORD=replace-with-a-strong-password
ADMIN_NAME=Owner Admin
GOOGLE_SHEETS_AUTO_SYNC=true
```

If Railway shows `problem processing` while saving variables, the service reference is not resolving yet. First generate public domains for both services, then either keep the reference variables above or paste the final domains literally:

```text
API_ALLOWED_ORIGINS=https://your-mobile-domain.up.railway.app,https://your-backend-domain.up.railway.app
```

Also confirm your service names are exactly `warehouse-backend`, `warehouse-mobile`, and `Postgres` if you use the reference syntax.

Optional, only if you use Google uploads or Sheets:

```text
GOOGLE_APPLICATION_CREDENTIALS_JSON=
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_STORAGE_BUCKET=
GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX=products
GOOGLE_CLOUD_STORAGE_PUBLIC=false
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_RANGE=CurrentStock!A:H
GOOGLE_APPS_SCRIPT_WEBHOOK_URL=
GOOGLE_APPS_SCRIPT_TOKEN=
```

## 4. Mobile Variables

Open `warehouse-mobile` -> Variables -> Raw Editor and add:

```text
WAREHOUSE_API_BASE=https://${{warehouse-backend.RAILWAY_PUBLIC_DOMAIN}}/api
```

The mobile Dockerfile writes this value into `config.js` at startup.
The mobile app also stores this URL in the browser. If it was opened earlier with a wrong API URL, open `API Settings`, paste the backend `/api` URL, and press `Test API`.

If Railway cannot process the reference variable, paste the final backend URL literally:

```text
WAREHOUSE_API_BASE=https://your-backend-domain.up.railway.app/api
```

## 5. Public URLs

For both `warehouse-backend` and `warehouse-mobile`:

1. Go to Settings -> Networking.
2. Generate a Railway public domain.
3. Deploy or redeploy the staged changes.

Open:

```text
https://<backend-domain>/login
https://<backend-domain>/api/health
https://<mobile-domain>/
```

Login with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

If login says `Invalid email or password`, update `ADMIN_EMAIL` and `ADMIN_PASSWORD` in backend Variables, then redeploy `warehouse-backend`. The pre-deploy command runs `create-admin` and resets the admin login from those variables.

After login works, run this in the backend service shell if you want a final production check:

```sh
python -m flask --app run.py validate-production
```

## 6. If Deploy Fails

- Mobile build shows `printf ... config.js`: open `warehouse-mobile` -> Settings -> Build and delete the Build Command. Keep Root Directory `/mobile-app` and Config File `/mobile-app/railway.json`, then redeploy.
- Mobile app cannot connect: confirm `WAREHOUSE_API_BASE=https://your-backend-domain.up.railway.app/api`, confirm backend `API_ALLOWED_ORIGINS` includes the mobile domain, then use the mobile login screen `API Settings` -> `Test API`.
- Mobile login works then immediately logs out: redeploy the latest backend and mobile code. The app now uses a bearer token after login so it does not depend only on cross-domain cookies.
- `problem processing` in Variables: generate public domains first, confirm service names, or paste literal URLs instead of `${{...}}` references.
- `validate-production` fails: check all required backend variables.
- Database error: confirm `DATABASE_URL=${{Postgres.DATABASE_URL}}` and the Postgres service name.
- Mobile cannot login: confirm `WAREHOUSE_API_BASE` and `API_ALLOWED_ORIGINS`.
- Cookie/session issue on mobile: keep `SESSION_COOKIE_SAMESITE=None` and `SESSION_COOKIE_SECURE=true`.
- Product image uploads fail: configure Google Cloud Storage variables or leave uploads disabled.

## 7. Google Cloud And Sheets

For Google Cloud Storage product images, set these backend variables:

```text
GOOGLE_APPLICATION_CREDENTIALS_JSON=raw-or-base64-service-account-json
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_STORAGE_BUCKET=your-bucket-name
GOOGLE_CLOUD_STORAGE_PRODUCTS_PREFIX=products
GOOGLE_CLOUD_STORAGE_PUBLIC=false
```

For Google Sheets sync, set:

```text
GOOGLE_SHEETS_SPREADSHEET_ID=your-sheet-id
GOOGLE_SHEETS_RANGE=CurrentStock!A:H
GOOGLE_SHEETS_AUTO_SYNC=true
```

Share the Google Sheet with the service account `client_email`. For images imported from the bucket, upload files under the prefix with names matching product SKUs, for example:

```text
products/SKU-1001.jpg
products/SKU-1002.png
```

Then open Admin -> Products -> `Import Images`. Open Admin -> Settings -> `Test Storage` and `Test Sheet` to see the exact Google error if permissions or variables are wrong.

Do not run `seed-demo` on a real production database.

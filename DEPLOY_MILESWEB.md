# Deploy On MilesWeb

This app can run on MilesWeb in two ways:

- MilesWeb cPanel Python hosting: easiest if your plan supports `Setup Python App` and PostgreSQL.
- MilesWeb VPS/Cloud: recommended for commercial warehouse data because you can install PostgreSQL, Gunicorn, Nginx, backups, and monitoring.

For real production use, use PostgreSQL. The app does not support MySQL.

## Option A: cPanel Python Hosting

Use this when cPanel has `Setup Python App` and either PostgreSQL is available in cPanel or you have an external PostgreSQL database.

### 1. Upload Code

Upload the repository outside `public_html`, for example:

```text
/home/CPANEL_USER/evsphere-warehouse
```

You can upload a ZIP with File Manager, or use Git/Terminal if your MilesWeb plan enables it:

```sh
cd ~
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git evsphere-warehouse
cd evsphere-warehouse/backend-flask
```

### 2. Create Python App In cPanel

Open cPanel -> `Setup Python App` -> `Create Application`.

Use:

```text
Python version: 3.12 if available, otherwise 3.11
Application root: evsphere-warehouse/backend-flask
Application URL: your backend domain or subdomain
Application startup file: passenger_wsgi.py
Application entry point: application
```

After creating it, cPanel shows an activation command. Open Terminal and run that command, then install dependencies:

```sh
cd ~/evsphere-warehouse/backend-flask
pip install --upgrade pip
pip install -r requirements.txt
```

If your cPanel UI has an environment variable section, add the variables there. Otherwise create a server-only `.env` file in `backend-flask`.

### 3. Database

If MilesWeb cPanel provides PostgreSQL, create a database and user from cPanel. Your `DATABASE_URL` will usually look like:

```text
postgresql://CPANEL_USER_DBUSER:DB_PASSWORD@localhost:5432/CPANEL_USER_DBNAME
```

If your MilesWeb plan only provides MySQL, do not use that shared plan for this production app. Use MilesWeb VPS/Cloud or an external PostgreSQL provider, then set that PostgreSQL connection string as `DATABASE_URL`.

### 4. Backend Variables

Required:

```text
APP_ENV=production
FLASK_DEBUG=false
SECRET_KEY=replace-with-a-strong-random-secret-at-least-32-chars
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=None
TRUST_PROXY_HEADERS=true
API_ALLOWED_ORIGINS=https://your-backend-domain.com,https://your-mobile-domain.com
ALLOW_INSECURE_USER_HEADER=false
INTEGRATION_API_KEY=replace-with-a-strong-random-integration-key
ADMIN_EMAIL=owner@your-company.com
ADMIN_PASSWORD=replace-with-a-strong-password
ADMIN_NAME=Owner Admin
GOOGLE_SHEETS_AUTO_SYNC=true
```

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

### 5. Initialize Backend

In the activated Python app terminal:

```sh
cd ~/evsphere-warehouse/backend-flask
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
python -m flask --app run.py init-db
```

Then click `Restart` for the Python app in cPanel.

Open:

```text
https://your-backend-domain.com/login
https://your-backend-domain.com/api/health
```

Login with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

### 6. Mobile PWA

Create a subdomain such as:

```text
staff.yourdomain.com
```

Point its document root to:

```text
/home/CPANEL_USER/evsphere-warehouse/mobile-app
```

Edit `mobile-app/config.js` on the server:

```js
window.WAREHOUSE_API_BASE = "https://your-backend-domain.com/api";
```

Add the mobile URL to backend `API_ALLOWED_ORIGINS`, then restart the Python app.

## Option B: MilesWeb VPS/Cloud

Use this for real warehouse operations if cPanel lacks PostgreSQL or if you need stronger reliability.

High-level setup:

```sh
sudo apt update
sudo apt install -y python3.12-venv python3-pip postgresql nginx
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /opt/evsphere-warehouse
cd /opt/evsphere-warehouse/backend-flask
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create PostgreSQL database/user, add a production `.env`, then run:

```sh
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
python -m flask --app run.py init-db
```

Run the backend with Gunicorn:

```sh
gunicorn --bind 127.0.0.1:8000 --workers 2 --threads 4 --timeout 120 run:app
```

For permanent hosting, create a `systemd` service for Gunicorn and an Nginx reverse proxy with HTTPS. Serve `mobile-app` from a separate Nginx server block or subdomain.

## Updates

For cPanel:

```sh
cd ~/evsphere-warehouse
git pull origin main
cd backend-flask
pip install -r requirements.txt
python -m flask --app run.py db upgrade
```

Then restart the Python app in cPanel.

For VPS, run the same update commands and restart the Gunicorn service.

## Troubleshooting

- `503 Service Unavailable`: check cPanel Python app logs and confirm `passenger_wsgi.py` uses entry point `application`.
- `validate-production` fails: one or more required environment variables are missing.
- Database error: confirm the database is PostgreSQL, not MySQL.
- Mobile login fails: check `WAREHOUSE_API_BASE`, `API_ALLOWED_ORIGINS`, and cookie settings.
- Static mobile opens but API fails: use HTTPS URLs only.

Do not run `seed-demo` on a real production database.

# Deploy On alwaysdata

This app can run on alwaysdata as a Python WSGI site with alwaysdata PostgreSQL.

## 1. Create Account And Database

1. Create or open your alwaysdata account.
2. In `Databases > PostgreSQL`, create a PostgreSQL database and user.
3. Note these values:
   - account name
   - database name
   - database user
   - database password

The PostgreSQL host format is:

```text
postgresql-ACCOUNT.alwaysdata.net
```

The app's `DATABASE_URL` format is:

```text
postgresql://USER:PASSWORD@postgresql-ACCOUNT.alwaysdata.net:5432/DATABASE
```

If the password contains special URL characters like `@`, `:`, `/`, `#`, or `%`, either generate a simpler database password or URL-encode it.

## 2. Upload Code With Git

SSH into alwaysdata:

```sh
ssh ACCOUNT@ssh-ACCOUNT.alwaysdata.net
```

Clone the repository:

```sh
git clone https://github.com/sahilalimolla001/wharehouse.evspeare.git ~/wharehouse.evspeare
cd ~/wharehouse.evspeare/backend-flask
```

## 3. Create Python Environment

alwaysdata recommends using `python`, not `python3`.

```sh
python -m venv ~/venvs/warehouse
source ~/venvs/warehouse/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. Configure Secrets

Create the server-only `.env` file:

```sh
cp alwaysdata.env.example .env
nano .env
```

Required values:

```text
APP_ENV=production
FLASK_DEBUG=false
SECRET_KEY=long-random-secret
DATABASE_URL=postgresql://USER:PASSWORD@postgresql-ACCOUNT.alwaysdata.net:5432/DATABASE
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=None
TRUST_PROXY_HEADERS=true
API_ALLOWED_ORIGINS=https://ACCOUNT.alwaysdata.net
ALLOW_INSECURE_USER_HEADER=false
INTEGRATION_API_KEY=long-random-api-key
ADMIN_EMAIL=your-email@example.com
ADMIN_PASSWORD=strong-admin-password
ADMIN_NAME=Owner Admin
```

For the first deploy, keep Google integrations empty unless they are already configured.

## 5. Initialize Database

Run:

```sh
source ~/venvs/warehouse/bin/activate
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
python -m flask --app run.py init-db
```

`init-db` creates the first admin user from `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `ADMIN_NAME`.

## 6. Create The Web Site

In alwaysdata admin:

1. Go to `Web > Sites`.
2. Add a site.
3. Use these settings:

```text
Type: Python WSGI
Application path: /home/ACCOUNT/wharehouse.evspeare/backend-flask/wsgi.py
Working directory: /home/ACCOUNT/wharehouse.evspeare/backend-flask
Virtualenv directory: /home/ACCOUNT/venvs/warehouse
Python version: 3.12 or your selected account default
Address: https://ACCOUNT.alwaysdata.net
```

If you do not use the `.env` file, add the same environment variables in the site settings.

Open:

```text
https://ACCOUNT.alwaysdata.net/login
```

## 7. Deploy Updates Later

```sh
cd ~/wharehouse.evspeare
git pull origin main
cd backend-flask
source ~/venvs/warehouse/bin/activate
python -m pip install -r requirements.txt
python -m flask --app run.py db upgrade
```

Then reload the site from `Web > Sites` in alwaysdata admin.

## 8. Optional Mobile Static Site

If you also want the mobile PWA live:

1. Add another alwaysdata site with a static file type.
2. Point it to:

```text
/home/ACCOUNT/wharehouse.evspeare/mobile-app
```

3. Edit `mobile-app/config.js` on the server so it contains:

```js
window.WAREHOUSE_API_BASE = "https://ACCOUNT.alwaysdata.net/api";
```

Then add the mobile site's URL to `API_ALLOWED_ORIGINS` and reload the backend site.

# Production Checklist

Use this before commercial warehouse use.

## Required

- Host the Flask backend on HTTPS.
- Use PostgreSQL, not SQLite.
- Set `APP_ENV=production` and `FLASK_DEBUG=false`.
- Set a strong `SECRET_KEY`.
- Set `SESSION_COOKIE_SECURE=true`.
- Set `API_ALLOWED_ORIGINS` to the exact HTTPS domains for the admin website and mobile app.
- Keep `ALLOW_INSECURE_USER_HEADER=false`.
- Set a strong `INTEGRATION_API_KEY` and keep it only on trusted server-side systems.
- Run migrations before startup: `python -m flask --app run.py db upgrade`.
- Create the first admin with `ADMIN_EMAIL` and `ADMIN_PASSWORD`, then run `python -m flask --app run.py init-db`.
- Do not run `seed-demo` on the production database.

## Recommended

- Put the admin website and mobile PWA behind the same trusted domain when possible.
- Use a paid database plan with automated backups for commercial use.
- Turn on provider-level monitoring, uptime alerts, and log retention.
- Restrict Google Cloud Storage bucket permissions and use signed/private access unless public product photos are intentional.
- Create a dedicated Shiprocket API user and store its credentials only in server-side environment variables.
- Rotate `SECRET_KEY`, `ADMIN_PASSWORD`, Google tokens, and service-account keys if they were ever shared.
- Test stock-in, stock-out, location movement, order picking, packing, dispatch, and reports with real staff roles before launch.

## Final Check

```powershell
python -m flask --app run.py validate-production
```

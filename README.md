# Evsphere Warehouse System

Flask backend, PostgreSQL-ready database models, Bootstrap admin website, and mobile staff PWA for warehouse operations.

## Project Structure

```text
backend-flask/
  app/
    models.py
    routes/
    templates/
    static/
    utils/
  config.py
  run.py
  requirements.txt

mobile-app/
  index.html
  styles.css
  app.js
  manifest.webmanifest
  sw.js
```

The older static prototype remains in the root files (`index.html`, `styles.css`, `app.js`). The production foundation is now inside `backend-flask` and `mobile-app`.

## Production

Commercial deployment can use Railway, alwaysdata, or Render.

For Railway:

```text
DEPLOY_RAILWAY.md
```

For MilesWeb:

```text
DEPLOY_MILESWEB.md
```

For alwaysdata:

```text
DEPLOY_ALWAYSDATA.md
```

For Render Blueprint from the repository root:

```text
render.yaml
DEPLOY_RENDER.md
```

Security checks and launch requirements are documented in:

```text
backend-flask/PRODUCTION_CHECKLIST.md
```

Before using real warehouse data on any host, run:

```powershell
cd backend-flask
python -m flask --app run.py validate-production
python -m flask --app run.py db upgrade
python -m flask --app run.py init-db
```

## Workflow

```text
Supplier se maal aaya
  -> Stock In entry
  -> Product quantity increase
  -> Warehouse location assign
  -> Order aaya
  -> Pick list
  -> Packing
  -> Stock Out
  -> Quantity decrease
  -> Dispatch / invoice
  -> Report update
```

## Core Modules

- Admin dashboard
- Product add/edit
- Supplier management
- Stock in/out
- Inventory by warehouse location
- Orders and pick list
- External website order import API
- Reports
- Users and staff roles
- Mobile scan, stock movement, packing, dispatch, and location update

## Database Tables

- User
- Product
- Category
- Supplier
- StockIn
- StockOut
- Inventory
- WarehouseLocation
- Order
- OrderItem
- Barcode
- ActivityLog

## Next Build Steps

1. Add multi-item order form.
2. Add PDF invoices.
3. Add payment/accounting export if needed.
4. Convert the mobile PWA into Android app if needed.

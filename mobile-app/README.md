# Evsphere Warehouse Staff Mobile App

This is a browser-based PWA shell for warehouse staff.

## Features

- API login
- Barcode / QR scan with `BarcodeDetector` when the browser supports it
- Manual SKU number / barcode fallback
- Stock in
- Stock out
- Pick list
- Packing status
- Dispatch status
- Location update

## Local use

1. Start the Flask backend from `backend-flask`.
2. Open `mobile-app/index.html` in a browser, or serve this folder over HTTP.
3. Set API URL to `http://127.0.0.1:5000/api`.
4. Login with the seeded admin or staff user.

For Android camera scan, serve over HTTPS or use localhost during development. Some mobile browsers only enable camera APIs on secure origins.

## Production use

1. Host this folder over HTTPS.
2. Set the API URL to the HTTPS backend `/api` URL.
3. Add this app origin to backend `API_ALLOWED_ORIGINS`.
4. If the mobile app is on a different domain than the backend, set backend `SESSION_COOKIE_SAMESITE=None` and keep `SESSION_COOKIE_SECURE=true`.

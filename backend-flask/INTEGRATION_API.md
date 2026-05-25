# External Order Import API

Use this API when another website, marketplace, or ecommerce backend needs to send orders into Evsphere Warehouse.

Do this from the other website's backend or webhook handler. Do not expose `INTEGRATION_API_KEY` in frontend JavaScript.

For customer website checkout examples, see:

```text
../CUSTOMER_ORDER_INTEGRATION.md
```

## Endpoint

```text
POST /api/integrations/orders
Authorization: Bearer YOUR_INTEGRATION_API_KEY
Content-Type: application/json
```

You can also send the key as:

```text
X-Integration-Key: YOUR_INTEGRATION_API_KEY
```

## Central Panel User Creation

Use this endpoint when the EV Speare central panel creates admin, manager, staff, or picker users.

```text
GET /api/central-panel/users
Authorization: Bearer YOUR_INTEGRATION_API_KEY
```

```text
POST /api/central-panel/users
Authorization: Bearer YOUR_INTEGRATION_API_KEY
Content-Type: application/json
```

```json
{
  "userId": "picker01@evspeare.com",
  "password": "strong-password",
  "name": "Picker 01",
  "phone": "9999999999",
  "role": "picker",
  "warehouseId": "1",
  "status": "active"
}
```

`warehouseId` accepts either a numeric warehouse ID or an active warehouse code.

## Payload

```json
{
  "source": "shopify",
  "external_order_id": "100045",
  "order_number": "SHOP-100045",
  "customer_name": "Rahul Sharma",
  "customer_phone": "+91 90000 00000",
  "customer_address": "Delhi, India",
  "payment_method": "Prepaid",
  "billing_address": {
    "first_name": "Rahul",
    "last_name": "Sharma",
    "address": "221B Market Road",
    "address_2": "Near Metro Gate",
    "city": "Delhi",
    "state": "Delhi",
    "pincode": "110001",
    "country": "India",
    "email": "rahul@example.com",
    "phone": "+91 90000 00000"
  },
  "shipping_address": {
    "first_name": "Rahul",
    "last_name": "Sharma",
    "address": "221B Market Road",
    "address_2": "Near Metro Gate",
    "city": "Delhi",
    "state": "Delhi",
    "pincode": "110001",
    "country": "India",
    "email": "rahul@example.com",
    "phone": "+91 90000 00000"
  },
  "priority": "normal",
  "expected_dispatch_date": "2026-05-20",
  "assigned_to_email": "picker@your-company.com",
  "items": [
    {
      "sku": "1001",
      "name": "Barcode Scanner",
      "quantity": 2,
      "unit_price": 2400,
      "discount": 0,
      "tax": 0,
      "hsn": "8471"
    }
  ]
}
```

## Required Fields

- `external_order_id`: the order ID from the other website.
- `customer_name`: customer name.
- `items`: non-empty list of products.
- `items[].sku` or `items[].product_id` or `items[].barcode`.
- SKU values should be the number only, for example `1001`. Legacy values like `SKU-1001` are still accepted.
- `items[].quantity`: greater than zero.

For automatic Shiprocket dispatch, also send structured `billing_address`, `shipping_address`, and `payment_method` (`Prepaid` or `COD`). The warehouse keeps the full payload and uses it to create the Shiprocket courier order after package dimensions are entered during dispatch.

## Duplicate Safety

The API uses `source` + `external_order_id` as the duplicate check. If the same external order is sent twice, the existing warehouse order is returned.

## Example cURL

```bash
curl -X POST "https://your-backend.onrender.com/api/integrations/orders" \
  -H "Authorization: Bearer YOUR_INTEGRATION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "website",
    "external_order_id": "WEB-5001",
    "customer_name": "Rahul Sharma",
    "customer_phone": "+91 90000 00000",
    "customer_address": "Delhi, India",
    "items": [
      {"sku": "1001", "quantity": 1}
    ]
  }'
```

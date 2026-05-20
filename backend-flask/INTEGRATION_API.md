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

## Payload

```json
{
  "source": "shopify",
  "external_order_id": "100045",
  "order_number": "SHOP-100045",
  "customer_name": "Rahul Sharma",
  "customer_phone": "+91 90000 00000",
  "customer_address": "Delhi, India",
  "priority": "normal",
  "expected_dispatch_date": "2026-05-20",
  "assigned_to_email": "picker@your-company.com",
  "items": [
    {
      "sku": "SKU-1001",
      "quantity": 2,
      "unit_price": 2400
    }
  ]
}
```

## Required Fields

- `external_order_id`: the order ID from the other website.
- `customer_name`: customer name.
- `items`: non-empty list of products.
- `items[].sku` or `items[].product_id` or `items[].barcode`.
- `items[].quantity`: greater than zero.

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
      {"sku": "SKU-1001", "quantity": 1}
    ]
  }'
```

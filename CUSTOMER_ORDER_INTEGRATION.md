# Customer Website Orders To Warehouse

Use this flow when a customer places an order on the customer website and the order must appear in the warehouse admin.

Your customer website:

```text
https://evspeare.up.railway.app
```

## Warehouse Endpoint

```text
POST https://YOUR-BACKEND-DOMAIN.up.railway.app/api/integrations/orders
Authorization: Bearer YOUR_INTEGRATION_API_KEY
Content-Type: application/json
```

Do this from the customer website backend, not from browser JavaScript. Keep `INTEGRATION_API_KEY` secret.

## Railway Backend Variable

Set this on `evsphere-warehouse-backend`:

```text
INTEGRATION_API_KEY=strong-random-secret-key
```

Redeploy backend after changing it.

## Payload

The customer website cart must send warehouse SKU numbers. The product feed already gives each product `sku`.

```json
{
  "source": "customer-website",
  "external_order_id": "WEB-100045",
  "order_number": "WEB-100045",
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
  "items": [
    {
      "sku": "1001",
      "quantity": 2,
      "unit_price": 2400
    }
  ]
}
```

Required:

- `external_order_id`
- `customer_name`
- `items`
- `items[].sku`
- `items[].quantity`

For automatic Shiprocket courier creation at dispatch time, send `payment_method`, `billing_address`, and `shipping_address` with city, state, and pincode. The picker will only enter package length, breadth, height, and weight on the Ship page.

Duplicate safety: the same `source` + `external_order_id` will not create duplicate orders.

## PHP Example

Use this in the customer website backend after checkout succeeds.

```php
<?php
function sendOrderToWarehouse($order) {
    $warehouseUrl = "https://YOUR-BACKEND-DOMAIN.up.railway.app/api/integrations/orders";
    $apiKey = getenv("WAREHOUSE_INTEGRATION_API_KEY");

    $payload = json_encode([
        "source" => "customer-website",
        "external_order_id" => $order["id"],
        "order_number" => "WEB-" . $order["id"],
        "customer_name" => $order["customer_name"],
        "customer_phone" => $order["customer_phone"],
        "customer_address" => $order["customer_address"],
        "priority" => "normal",
        "items" => array_map(function ($item) {
            return [
                "sku" => $item["sku"],
                "quantity" => (int) $item["quantity"],
                "unit_price" => (float) $item["price"]
            ];
        }, $order["items"])
    ]);

    $ch = curl_init($warehouseUrl);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            "Authorization: Bearer " . $apiKey,
            "Content-Type: application/json"
        ],
        CURLOPT_POSTFIELDS => $payload,
        CURLOPT_TIMEOUT => 20
    ]);

    $response = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($status < 200 || $status >= 300) {
        error_log("Warehouse order sync failed: " . $response);
    }

    return [$status, $response];
}
?>
```

## Node/Express Example

```js
app.post("/checkout", async (req, res) => {
  const order = await saveCustomerOrder(req.body);

  const payload = {
    source: "customer-website",
    external_order_id: String(order.id),
    order_number: `WEB-${order.id}`,
    customer_name: order.customerName,
    customer_phone: order.customerPhone,
    customer_address: order.customerAddress,
    priority: "normal",
    items: order.items.map((item) => ({
      sku: item.sku,
      quantity: item.quantity,
      unit_price: item.price
    }))
  };

  const response = await fetch("https://YOUR-BACKEND-DOMAIN.up.railway.app/api/integrations/orders", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${process.env.WAREHOUSE_INTEGRATION_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    console.error("Warehouse order sync failed", await response.text());
  }

  res.json({ ok: true, order_id: order.id });
});
```

## Browser Checkout Rule

Browser JavaScript should call your customer website backend:

```js
await fetch("/checkout", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cartAndCustomerDetails)
});
```

Do not call the warehouse endpoint directly from browser JavaScript, because that would expose `INTEGRATION_API_KEY`.

## Test From PowerShell

```powershell
$body = @{
  source = "customer-website"
  external_order_id = "TEST-1001"
  order_number = "TEST-1001"
  customer_name = "Test Customer"
  customer_phone = "+91 90000 00000"
  customer_address = "Test Address"
  items = @(@{ sku = "1001"; quantity = 1; unit_price = 2400 })
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "https://YOUR-BACKEND-DOMAIN.up.railway.app/api/integrations/orders" `
  -Method Post `
  -Headers @{ Authorization = "Bearer YOUR_INTEGRATION_API_KEY" } `
  -ContentType "application/json" `
  -Body $body
```

After success, open:

```text
Warehouse Admin -> Orders
```

The order will appear as `pending`, and the mobile picker app will show it in the pick queue. If the order has no `assigned_to_email`, it still appears for picker users as an unassigned order. When a picker starts it, the order is assigned to that picker.

When the picker increases an item picked quantity, warehouse inventory is reduced immediately from available stock and a `StockOut` entry is created with reason `order_pick`. If picked quantity is reduced before packing, the stock is restored.

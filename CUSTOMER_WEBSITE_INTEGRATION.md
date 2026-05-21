# Customer Website Product Feed

Use this public API from the customer website to show live warehouse product data.

Your customer website origin:

```text
https://evspeare.up.railway.app
```

Add this origin to the warehouse backend `API_ALLOWED_ORIGINS` value along with the mobile/backend domains.

```text
GET https://your-backend-domain.com/api/public/products
```

Local test URL:

```text
http://127.0.0.1:5000/api/public/products
```

The response includes customer-safe fields:

```json
{
  "ok": true,
  "count": 1,
  "updated_at": "2026-05-18T09:30:00Z",
  "products": [
    {
      "id": 1,
      "sku": "SKU-1001",
      "name": "Product name",
      "description": "Product details",
      "value": 2499.0,
      "unit": "pcs",
      "available_quantity": 12,
      "in_stock": true,
      "image_url": "https://your-backend-domain.com/api/public/products/1/image",
      "updated_at": "2026-05-18T09:29:00Z"
    }
  ]
}
```

For hosted customer websites, add the customer site domain to backend `.env`:

```text
API_ALLOWED_ORIGINS=https://your-mobile-domain.up.railway.app,https://your-backend-domain.up.railway.app,https://evspeare.up.railway.app
```

## Frontend Snippet

```html
<section id="product-grid"></section>

<script>
  const WAREHOUSE_API = "https://your-backend-domain.com";
  const productGrid = document.getElementById("product-grid");

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[char]);
  }

  async function loadProducts() {
    const response = await fetch(`${WAREHOUSE_API}/api/public/products`, { cache: "no-store" });
    const data = await response.json();

    productGrid.innerHTML = data.products.map((product) => `
      <article class="product-card">
        ${product.image_url ? `<img src="${product.image_url}" alt="${escapeHtml(product.name)}">` : ""}
        <h3>${escapeHtml(product.name)}</h3>
        <p>${escapeHtml(product.description)}</p>
        <strong>Rs. ${product.value.toLocaleString("en-IN")}</strong>
        <span>${product.in_stock ? "In stock" : "Out of stock"}</span>
      </article>
    `).join("");
  }

  loadProducts();
  setInterval(loadProducts, 30000);
</script>
```

The `setInterval` keeps the customer website refreshed every 30 seconds, so Stock In, product edits, image changes, and price updates show without manual export.

## Optional Push Webhook

If the customer website has a backend API, the warehouse can push product changes to it whenever a product is added, edited, archived, or stock quantity changes.

Set these variables on the warehouse backend:

```text
CUSTOMER_PRODUCT_WEBHOOK_URL=https://your-customer-website.com/api/warehouse/products
CUSTOMER_PRODUCT_WEBHOOK_TOKEN=strong-shared-secret
CUSTOMER_PRODUCT_WEBHOOK_TIMEOUT=10
```

The warehouse sends:

```http
POST /api/warehouse/products
Authorization: Bearer strong-shared-secret
Content-Type: application/json
X-Warehouse-Event: product.saved
```

Example payload:

```json
{
  "event": "product.saved",
  "source": "evsphere-warehouse",
  "feed_url": "https://your-backend-domain.com/api/public/products",
  "product": {
    "id": 1,
    "sku": "SKU-1001",
    "name": "Product name",
    "description": "Product details",
    "value": 2499.0,
    "available_quantity": 12,
    "in_stock": true,
    "is_active": true,
    "image_url": "https://your-backend-domain.com/api/public/products/1/image"
  }
}
```

Supported events:

- `product.saved`
- `product.archived`
- `stock.changed`
- `product.test`

If the customer website is only static HTML/JavaScript, use the public product feed above instead of webhook push.

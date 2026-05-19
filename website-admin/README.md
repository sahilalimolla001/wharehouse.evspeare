# Website Admin

The admin website is implemented as Flask/Jinja templates inside:

```text
backend-flask/app/templates/
backend-flask/app/static/
```

This keeps the Bootstrap admin panel and Flask routes together, which is simpler for server-rendered pages on Render.

Main admin URLs:

- `/login`
- `/dashboard`
- `/products`
- `/add-product`
- `/product/<id>`
- `/suppliers`
- `/add-supplier`
- `/stock-in`
- `/stock-out`
- `/inventory`
- `/warehouse-locations`
- `/add-location`
- `/orders`
- `/add-order`
- `/order/<id>`
- `/reports`
- `/users`
- `/settings`

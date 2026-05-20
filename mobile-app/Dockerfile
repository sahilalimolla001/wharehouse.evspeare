FROM caddy:2-alpine

WORKDIR /srv

COPY . .
COPY Caddyfile /etc/caddy/Caddyfile

CMD ["sh", "-c", "printf 'window.WAREHOUSE_API_BASE = \"%s\";\\n' \"$WAREHOUSE_API_BASE\" > /srv/config.js && exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile"]

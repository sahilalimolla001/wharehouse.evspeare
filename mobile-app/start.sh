#!/bin/sh
set -eu

cat > /srv/config.js <<EOF
window.WAREHOUSE_API_BASE = "${WAREHOUSE_API_BASE:-}";
window.WAREHOUSE_API_CANDIDATES = [
  "${WAREHOUSE_API_BASE:-}",
  "${WAREHOUSE_BACKEND_URL:-}",
  "${WAREHOUSE_BACKEND_PUBLIC_URL:-}",
  "${BACKEND_PUBLIC_URL:-}"
];
EOF

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile

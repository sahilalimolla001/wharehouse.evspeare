#!/bin/sh
set -eu

cat > /srv/config.js <<EOF
window.WAREHOUSE_API_BASE = "${WAREHOUSE_API_BASE:-}";
EOF

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile

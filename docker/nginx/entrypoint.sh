#!/bin/sh
set -e

# ── Substitute ${DOMAIN} in the config template ──────────────────────────────
# We only replace ${DOMAIN} – nginx's own $host, $uri etc. are left untouched.
echo "[nginx] Generating config for domain: ${DOMAIN}"
envsubst '${DOMAIN}' \
  < /etc/nginx/templates/app.conf.template \
  > /etc/nginx/conf.d/app.conf

# ── Schedule periodic reload to pick up renewed TLS certificates ──────────────
# certbot renews ~30 days before expiry; nginx must reload to load the new cert.
echo "0 */12 * * * nginx -s reload" | crontab -
crond

echo "[nginx] Starting…"
exec "$@"

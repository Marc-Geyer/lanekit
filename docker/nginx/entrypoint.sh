#!/bin/sh
set -e

# ── Substitute ${DOMAIN} in the config template ──────────────────────────────
# We only replace ${DOMAIN} and ${ALIAS_DOMAINS} – nginx's own $host, $uri etc. are left untouched.
# nginx rejects an empty server_name, so use a placeholder when there are no aliases.
export ALIAS_DOMAINS="${ALIAS_DOMAINS:-unused.invalid}"
echo "[nginx] Generating config for domain: ${DOMAIN} (aliases: ${ALIAS_DOMAINS})"
envsubst '${DOMAIN} ${ALIAS_DOMAINS}' \
  < /etc/nginx/templates/app.conf.template \
  > /etc/nginx/conf.d/app.conf

# ── Schedule periodic reload to pick up renewed TLS certificates ──────────────
# certbot renews ~30 days before expiry; nginx must reload to load the new cert.
echo "0 */12 * * * nginx -s reload" | crontab -
crond

echo "[nginx] Starting…"
exec "$@"

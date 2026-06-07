#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LaneKit – First-time Let's Encrypt certificate setup
#
# Run this ONCE on a fresh server before starting the production stack:
#
#   chmod +x docker/certbot/init-letsencrypt.sh
#   ./docker/certbot/init-letsencrypt.sh
#
# Requirements:
#   • .env file present with DOMAIN, CERTBOT_EMAIL, CERTBOT_STAGING_FLAG set
#   • Ports 80 and 443 reachable from the internet
#   • DNS A record for $DOMAIN pointing to this server
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Load variables from .env ──────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Copy .env.example to .env and fill it in."
  exit 1
fi
# shellcheck disable=SC2046
export $(grep -v '^#' .env | grep -v '^$' | xargs)

DOMAIN="${DOMAIN:?DOMAIN must be set in .env}"
EMAIL="${CERTBOT_EMAIL:?CERTBOT_EMAIL must be set in .env}"
STAGING_FLAG="${CERTBOT_STAGING_FLAG:---staging}"   # default to staging for safety
COMPOSE="docker compose -f docker-compose.prod.yml"

echo "══════════════════════════════════════════════════════"
echo "  LaneKit – Let's Encrypt certificate initialisation"
echo "  Domain : $DOMAIN"
echo "  Email  : $EMAIL"
echo "  Mode   : ${STAGING_FLAG:-(PRODUCTION – real certificate)}"
echo "══════════════════════════════════════════════════════"
echo ""

if [ "$STAGING_FLAG" = "--staging" ]; then
  echo "⚠  STAGING MODE: the certificate will NOT be trusted by browsers."
  echo "   When you are happy everything works, set CERTBOT_STAGING_FLAG="
  echo "   (empty string) in .env and re-run this script."
  echo ""
fi

# ── 1. Create volume directories nginx needs to start ─────────────────────────
echo "▶ Creating certbot directories…"
mkdir -p ./docker/certbot/www

# ── 2. Create a temporary self-signed certificate ─────────────────────────────
# nginx won't start without something at the cert paths; we replace it next.
echo "▶ Generating temporary self-signed certificate for $DOMAIN…"
$COMPOSE run --rm --no-deps --entrypoint \
  "openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
   -keyout /etc/letsencrypt/live/${DOMAIN}/privkey.pem \
   -out    /etc/letsencrypt/live/${DOMAIN}/fullchain.pem \
   -subj   /CN=localhost" \
  certbot
echo "   ✓ Temporary certificate created."

# ── 3. Start nginx with the dummy cert ───────────────────────────────────────
echo "▶ Starting nginx…"
$COMPOSE up --force-recreate -d nginx
sleep 3   # give nginx a moment to bind ports

# ── 4. Delete the dummy cert ──────────────────────────────────────────────────
echo "▶ Removing temporary certificate…"
$COMPOSE run --rm --no-deps --entrypoint \
  "rm -rf /etc/letsencrypt/live/${DOMAIN} \
          /etc/letsencrypt/archive/${DOMAIN} \
          /etc/letsencrypt/renewal/${DOMAIN}.conf" \
  certbot

# ── 5. Request the real certificate from Let's Encrypt ───────────────────────
echo "▶ Requesting Let's Encrypt certificate…"
$COMPOSE run --rm --no-deps --entrypoint \
  "certbot certonly \
     --webroot -w /var/www/certbot \
     ${STAGING_FLAG} \
     --email ${EMAIL} \
     -d ${DOMAIN} \
     --rsa-key-size 4096 \
     --agree-tos \
     --force-renewal \
     --non-interactive" \
  certbot

# ── 6. Reload nginx with the real certificate ─────────────────────────────────
echo "▶ Reloading nginx with the real certificate…"
$COMPOSE exec nginx nginx -s reload

# ── 7. Bring up the rest of the stack ────────────────────────────────────────
echo "▶ Starting full production stack…"
$COMPOSE up -d

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✅  Done!  LaneKit is live at https://${DOMAIN}"
echo ""
echo "  To follow logs:  $COMPOSE logs -f"
echo "  To stop:         $COMPOSE down"
echo "══════════════════════════════════════════════════════"

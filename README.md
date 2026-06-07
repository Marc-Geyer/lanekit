# 🏊 LaneKit

A self-hosted Django application for managing swimming groups, training sessions, attendance, and club members — with real-time collaboration via WebSockets.

> **Organisation name** is configurable via a single environment variable — no code changes needed to brand it for your club.

---

## Contents

- [Branding](#branding--organisation-name)
- [Tech stack](#tech-stack)
- [Development with Docker](#development-with-docker)
- [Production deployment](#production-deployment)
- [Running without Docker](#running-without-docker)
- [Key URLs](#key-urls)
- [How it works](#how-it-works)

---

## Branding & Organisation Name

Set `ORGANISATION_NAME` to put your club's name in the navbar, page titles, and registration page.

**In `.env`** (recommended):
```
ORGANISATION_NAME=SC Neptune 1921
```

**Result in the navbar:**
```
🌊  SC Neptune 1921  [LaneKit]   ← with org name
🌊  LaneKit                       ← without org name
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 4.2, Django Channels 4 (ASGI) |
| WebSockets | Daphne + channels-redis |
| Database | PostgreSQL 16 |
| Cache / Channel layer | Redis 7 |
| Reverse proxy | Nginx 1.27 |
| TLS certificates | Let's Encrypt via Certbot |
| Frontend | Bootstrap 5.3, FullCalendar 6, SortableJS |
| Container runtime | Docker + Docker Compose |

---

## Development with Docker

The dev stack hot-reloads Python files, exposes PostgreSQL and Redis ports for inspection, and needs zero manual setup beyond Docker being installed.

### 1 — Prerequisites

- Docker Desktop (Mac / Windows) **or** Docker Engine + Docker Compose plugin (Linux)

### 2 — Configure environment

```bash
cp .env.example .env
```

Edit `.env`. For development these are the only lines you need to change:

```dotenv
ORGANISATION_NAME=My Club          # shown in the navbar
DEBUG=True                         # keep True for dev
# everything else can stay as-is
```

### 3 — Start the stack

```bash
docker compose up          # add -d to run in the background
```

On first boot the entrypoint will:
1. Wait for PostgreSQL to accept connections
2. Run `manage.py migrate` automatically
3. Create the superuser defined in `.env` (`admin` / `admin` by default)

The app is now at **http://localhost:8000**

### 4 — Day-to-day commands

```bash
# Tail logs
docker compose logs -f app

# Open a Django shell
docker compose exec app python manage.py shell

# Create a new migration after changing a model
docker compose exec app python manage.py makemigrations

# Run tests
docker compose exec app python manage.py test

# Stop everything (data is preserved in named volumes)
docker compose down

# Destroy volumes too (full reset)
docker compose down -v
```

---

## Production Deployment

### Requirements

- A Linux server (Ubuntu 22.04 LTS recommended)
- Docker Engine + Docker Compose plugin installed
- A domain name with an **A record pointing to the server's public IP**
- Ports **80** and **443** open in the firewall

### Step 1 — Install Docker on the server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # then log out and back in
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/your-org/lanekit.git
cd lanekit
```

### Step 3 — Configure environment

```bash
cp .env.example .env
nano .env    # or your preferred editor
```

Fill in **all** values, paying special attention to:

```dotenv
# Your public domain (DNS must already point here)
DOMAIN=lanekit.myclub.de

# A strong random string – generate one with:
#   python3 -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=<long-random-string>

# Your club name
ORGANISATION_NAME=SC Neptune 1921

# Database credentials (choose something strong)
DB_PASSWORD=<strong-password>

# First-boot superuser
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<strong-password>

# Let's Encrypt contact e-mail
CERTBOT_EMAIL=you@myclub.de

# IMPORTANT: test with staging first, then switch to real cert
# Staging (browser warning, unlimited retries):
CERTBOT_STAGING_FLAG=--staging
# Production (real trusted cert) – set this AFTER staging works:
# CERTBOT_STAGING_FLAG=
```

### Step 4 — Run the certificate init script (once only)

This script:
1. Creates a temporary self-signed cert so nginx can start
2. Starts nginx
3. Requests a real certificate from Let's Encrypt via the HTTP challenge
4. Reloads nginx with the real cert
5. Brings up the full stack

```bash
chmod +x docker/certbot/init-letsencrypt.sh
./docker/certbot/init-letsencrypt.sh
```

**Test with staging first** (`CERTBOT_STAGING_FLAG=--staging` in `.env`). When the site loads correctly (ignore the browser certificate warning), switch to a real certificate:

```bash
# 1. Edit .env:  CERTBOT_STAGING_FLAG=   (empty – remove the flag)
# 2. Re-run the init script to get a trusted cert:
./docker/certbot/init-letsencrypt.sh
```

Your site is now live at **https://lanekit.myclub.de** 🎉

### Step 5 — Remove first-boot superuser credentials

Once you have logged in and verified the admin account works, remove those lines from `.env` so they are not re-applied on container restarts:

```dotenv
# Remove or comment out:
# DJANGO_SUPERUSER_USERNAME=
# DJANGO_SUPERUSER_PASSWORD=
# DJANGO_SUPERUSER_EMAIL=
```

Then restart the app container:

```bash
docker compose -f docker-compose.prod.yml up -d app
```

---

### Certificate renewal

Certbot runs inside its own container and automatically attempts renewal every 12 hours. Let's Encrypt certificates are valid for 90 days; certbot renews them ~30 days before expiry. Nginx reloads its config every 12 hours (via a container-internal cron job) to pick up any newly issued certificates — no manual intervention is required.

To manually force a renewal:

```bash
docker compose -f docker-compose.prod.yml run --rm certbot certbot renew --force-renewal
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

---

### Production day-to-day commands

```bash
COMPOSE="docker compose -f docker-compose.prod.yml"

# View all logs
$COMPOSE logs -f

# View app logs only
$COMPOSE logs -f app

# Apply new migrations after an update
$COMPOSE exec app python manage.py migrate

# Open a Django shell
$COMPOSE exec app python manage.py shell

# Pull latest code and redeploy
git pull
$COMPOSE build app
$COMPOSE up -d app

# Full restart
$COMPOSE restart

# Stop (data preserved)
$COMPOSE down

# Check certificate expiry
$COMPOSE run --rm certbot certbot certificates
```

---

### Production architecture

```
Internet
   │  HTTPS :443 / HTTP :80
   ▼
┌──────────────────────────────────────────┐
│               nginx container            │
│  • TLS termination (Let's Encrypt)       │
│  • Serves /static/ and /media/ directly  │
│  • Rate-limits /accounts/login/          │
│  • Proxies /ws/ with WebSocket upgrade   │
│  • Proxies everything else to Daphne     │
└──────┬───────────────────────────────────┘
       │ HTTP :8000 (internal Docker network)
       ▼
┌──────────────────────────────────────────┐
│           app container (Daphne)         │
│  • Django 4.2 / Channels 4 (ASGI)        │
│  • Handles HTTP requests + WebSockets    │
└──────┬───────────────┬────────────────────┘
       │               │
       ▼               ▼
┌────────────┐  ┌─────────────────────────┐
│ PostgreSQL │  │  Redis                  │
│ (db)       │  │  WebSocket channel layer│
└────────────┘  └─────────────────────────┘

certbot container: loops every 12 h, renews cert when needed
nginx:             reloads every 12 h via internal cron
```

---

## Running Without Docker

For local development without Docker (SQLite, in-memory channels):

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver          # Channels overrides this with ASGI support
```

Set `ORGANISATION_NAME` in your shell:

```bash
export ORGANISATION_NAME="My Club"
python manage.py runserver
```

---

## Key URLs

| URL | Description |
|---|---|
| `/` | Calendar (main page) |
| `/training/events/?start=…&end=…` | Calendar event JSON API (FullCalendar feed) |
| `/training/session/<id>/<date>/` | Session modal content – GET=view, POST=create instance |
| `/ws/session/<instance_id>/` | WebSocket endpoint (live attendance + training plan) |
| `/groups/` | Group list |
| `/swimmers/` | People search |
| `/accounts/login/` | Login |
| `/excuse/<uuid>/` | Self-excuse link (no login needed) |
| `/admin/` | Django admin |

---

## How It Works

**Calendar** — `/training/events/` iterates the date range, applies exceptions (shown in red), checks for instances (full opacity) vs planned slots (slightly transparent), and returns FullCalendar-compatible JSON. Logged-out users see everything read-only; logged-in users can toggle "My Sessions" to filter to their groups.

**Session Modal** — Clicking a calendar event loads the modal via an AJAX GET. If no instance exists yet, trainers see a "Start Session" button that POSTs to create the instance and pre-populate an attendance row for each group member.

**WebSocket Live Sync** — `SessionConsumer` verifies the connecting user is a trainer of that group, then joins a per-session channel group. Every action (attendance toggle, plan entry CRUD, drag-reorder, notes autosave) is saved to the database and broadcast to every connected client. The coloured dot in the modal corner shows the connection state.

**Excuse Tokens** — A trainer generates a shareable one-time URL via `POST /training/excuse/generate/`. The swimmer visits the link, confirms, and their attendance is automatically set to "excused" — no login required.

**TLS Renewal** — Certbot runs `certbot renew` in a loop inside its own container. nginx picks up new certificates every 12 hours via an internal cron that runs `nginx -s reload`.

# 🏊 LaneKit

A self-hosted Django application for managing swimming groups, training sessions, attendance, and club members — with real-time collaboration via WebSockets.

> **Organisation name** is configurable via a single environment variable — no code changes needed to brand it for your club.

---

## Contents

- [Features](#features)
- [Branding](#branding--organisation-name)
- [Tech stack](#tech-stack)
- [Development with Docker](#development-with-docker)
- [Production deployment](#production-deployment)
- [Running without Docker](#running-without-docker)
- [Translation system](#translation-system)
- [Access control](#access-control)
- [WebSocket + fallback](#websocket--polling-fallback)
- [Key URLs](#key-urls)
- [How it works](#how-it-works)

---

## Features

| Area | What it does |
|---|---|
| **Calendar** | FullCalendar view of all recurring sessions; exceptions shown in red; click to open detail modal |
| **Session modal** | Trainer starts session, live-edits training plan and attendance via WebSocket |
| **WebSocket sync** | Multiple trainers edit simultaneously; 3-retry reconnect + HTTP polling fallback if WS drops |
| **Groups** | Create groups with a colour, manage members (swimmer / trainer roles), configure recurring slots |
| **People** | Search/filter all swimmers, view/edit profile, emergency contacts |
| **Excuse tokens** | Generate a shareable one-time URL so a swimmer can self-excuse without logging in |
| **Multilingual** | 🇬🇧 English · 🇩🇪 Deutsch · 🇺🇦 Українська · 🇸🇦 العربية (RTL) — switchable per user in the navbar |
| **User accounts** | Django-auth based with extended profile (admin / trainer / swimmer roles) |
| **Exceptions** | Mark a date as cancelled for specific sessions or all sessions (holidays) |

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
| Cache / Channel layer | Redis 7 (redis-py **4.x** — see note below) |
| Reverse proxy | Nginx 1.27 |
| TLS certificates | Let's Encrypt via Certbot |
| Frontend | Bootstrap 5.3, FullCalendar 6, SortableJS |
| Container runtime | Docker + Docker Compose |

> **Redis version note:** `redis-py` is pinned to `<5.0`. Version 5+ defaults to the RESP3 protocol which causes `TimeoutError` in channels-redis 4.x subscriptions. RESP2 (4.x) is stable and fully supported.

---

## Development with Docker

### 1 — Prerequisites

- Docker Desktop (Mac / Windows) **or** Docker Engine + Docker Compose plugin (Linux)

### 2 — Configure environment

```bash
cp .env.example .env
```

Minimal changes for development:

```dotenv
ORGANISATION_NAME=My Club
DEBUG=True
```

### 3 — Start the stack

```bash
docker compose up
```

On first boot the entrypoint will:
1. Wait for PostgreSQL and Redis to accept connections
2. Run `manage.py migrate` automatically
3. Create the superuser defined in `.env` (`admin` / `admin` by default)

The app is now at **http://localhost:8000**

### 4 — Day-to-day commands

```bash
docker compose logs -f app
docker compose exec app python manage.py shell
docker compose exec app python manage.py makemigrations
docker compose exec app python manage.py test
docker compose down        # preserves data
docker compose down -v     # full reset
```

---

## Production Deployment

### Requirements

- A Linux server (Ubuntu 22.04 LTS recommended)
- Docker Engine + Docker Compose plugin
- A domain name with an A record pointing to the server's public IP
- Ports **80** and **443** open

### Step 1 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### Step 2 — Clone and configure

```bash
git clone https://github.com/Marc-Geyer/lanekit.git
cd lanekit
cp .env.example .env
nano .env
```

Key values to set:

```dotenv
DOMAIN=lanekit.myclub.de
SECRET_KEY=<long-random-string>   # python3 -c "import secrets; print(secrets.token_urlsafe(64))"
ORGANISATION_NAME=SC Neptune 1921
DB_PASSWORD=<strong-password>
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<strong-password>
CERTBOT_EMAIL=you@myclub.de
CERTBOT_STAGING_FLAG=--staging    # test with staging first
```

### Step 3 — First-time TLS certificate

```bash
chmod +x docker/certbot/init-letsencrypt.sh
./docker/certbot/init-letsencrypt.sh
```

Test with staging first (browser shows cert warning — that's fine). When it loads correctly:

```dotenv
# .env: remove the staging flag
CERTBOT_STAGING_FLAG=
```

Re-run the init script to get a trusted certificate. Site is live at **https://lanekit.myclub.de** 🎉

### Step 4 — Remove first-boot credentials

After confirming the admin account works, remove from `.env`:

```dotenv
# DJANGO_SUPERUSER_USERNAME=
# DJANGO_SUPERUSER_PASSWORD=
# DJANGO_SUPERUSER_EMAIL=
```

Then: `docker compose -f docker-compose.prod.yml up -d app`

### Certificate renewal

Certbot renews automatically every 12 h. Nginx reloads every 12 h via internal cron to pick up new certs — no manual intervention needed.

```bash
# Force manual renewal
docker compose -f docker-compose.prod.yml run --rm certbot certbot renew --force-renewal
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### Production day-to-day

```bash
COMPOSE="docker compose -f docker-compose.prod.yml"
$COMPOSE logs -f
$COMPOSE exec app python manage.py migrate
git pull && $COMPOSE build app && $COMPOSE up -d app
$COMPOSE run --rm certbot certbot certificates
```

### Architecture

```
Internet  :443/:80
    ↓
┌─────────────────────────────┐
│  nginx (TLS, static files,  │
│  rate-limit login, WS proxy)│
└──────────┬──────────────────┘
           │ :8000
    ┌──────▼────────────────┐
    │  app (Daphne / ASGI)  │
    └──────┬──────────┬─────┘
           ↓          ↓
     PostgreSQL     Redis
                 (WS channel layer)

certbot: renews cert every 12 h
nginx:   reloads config every 12 h
```

---

## Running Without Docker

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
ORGANISATION_NAME="My Club" python manage.py runserver
```

---

## Translation System

LaneKit uses a **custom lightweight i18n system** — not Django's gettext. All strings live in one file per language with no compilation step required.

```
translations/
  registry.py   ← THE place to register a new language (one import + one tuple)
  helpers.py    ← tr(request, 'msg_key') for use in Python views
  en.py         English
  de.py         German (default)
  uk.py         Ukrainian
  ar.py         Arabic (RTL — Bootstrap RTL CSS loaded automatically)
```

**In templates:** `{{ t.some_key }}` (no `{% load %}` tag needed)  
**In views:** `from translations.helpers import tr` → `messages.success(request, tr(request, 'msg_profile_updated'))`  
**Language switching:** navbar flag dropdown → `GET /set-language/?lang=uk`

### Adding a new language

1. Create `translations/xx.py` — copy `en.py`, translate the values
2. In `translations/registry.py` add one import and one tuple to `LANGUAGES`
3. If RTL, add the code to `RTL_LANGUAGES`

### Missing key behaviour

`TranslationDict` catches missing keys at runtime without crashing:
- **DEBUG mode:** renders `⚠ [key_name]` visibly on the page
- **Production:** renders the bare key name (always readable)
- **Always:** logs `WARNING translations: Missing translation key 'key_name'` to the console

---

## Access Control

| Role | Capabilities |
|---|---|
| **Anonymous** | View calendar (read-only), view group list, use excuse token links |
| **Swimmer** | All of above + view/edit own swimmer profile, filter calendar to own sessions |
| **Trainer** | All of above + start sessions, edit training plan, mark attendance, manage group members, add exceptions |
| **Admin** | Full access including user management and group creation |

Role is set on `UserProfile.role`. Trainer status for a specific group is additionally controlled by `GroupMembership.role`.

---

## WebSocket + Polling Fallback

The session modal connects to `ws[s]://host/ws/session/<instance_id>/` on open.

**Connection lifecycle:**
1. Connect → send `init` event with current attendance + plan state
2. Every change (attendance, plan entry, notes, reorder) → saved to DB + broadcast to all connected clients
3. On disconnect: retry up to **3 times** (2 s / 5 s / 10 s backoff)
4. After 3 failures: fall back to **HTTP polling** every 5 s via `GET /training/session/<id>/state/`
5. In polling mode: attendance writes use `POST /training/session/<id>/attendance/` directly

**Status indicator** (dot in modal corner):  
🟢 `connected` · 🟡 `connecting` · 🔵 `polling` · 🔴 `error`

---

## Key URLs

| URL | Description |
|---|---|
| `/` | Calendar (main page) |
| `/training/events/?start=…&end=…` | Calendar event JSON API |
| `/training/session/<id>/<date>/` | Session modal — returns `{html, instance_id, is_trainer}` JSON |
| `/training/session/<id>/state/` | Polling fallback state endpoint |
| `/training/session/<id>/attendance/` | REST attendance update (polling fallback) |
| `/ws/session/<instance_id>/` | WebSocket endpoint |
| `/set-language/?lang=xx` | Switch UI language |
| `/groups/` | Group list |
| `/swimmers/` | People search |
| `/accounts/login/` | Login |
| `/excuse/<uuid>/` | Self-excuse link (no login required) |
| `/admin/` | Django admin |

---

## How It Works

**Calendar** — `/training/events/` iterates the date range, applies exceptions (red), checks for instances (full opacity) vs planned slots (transparent), returns FullCalendar JSON. Logged-out users see everything read-only; logged-in users can toggle "My Sessions."

**Session Modal** — Click a calendar event → AJAX GET returns JSON `{html, instance_id, is_trainer}`. If trainer + instance exists → WebSocket connects immediately (instance_id comes from JSON, not injected script tags which browsers never execute via innerHTML).

**WebSocket Live Sync** — `SessionConsumer` verifies the connecting user is a trainer of that group, joins `session_<id>` channel group. Every action is saved to DB and broadcast to all connected clients.

**Excuse Tokens** — Trainer generates a one-time URL via `POST /training/excuse/generate/`. Swimmer visits, confirms, attendance set to "excused" — no login required.

**TLS Renewal** — Certbot loops every 12 h inside its container. Nginx reloads every 12 h via internal cron to pick up new certificates.
# 🏊 LaneKit

A self-hosted Django application for managing swimming groups, training sessions, attendance, and club members — with real-time collaboration via WebSockets.

> **Organisation name** is configurable via a single environment variable — no code changes needed to brand it for your club.

---

## Contents

- [Branding](#branding--organisation-name)
- [Tech stack](#tech-stack)
- [Development with Docker](#development-with-docker)
- [Demo data for development](#demo-data-for-development)
- [Production deployment](#production-deployment)
- [Git on the server](#git-on-the-server)
- [Running without Docker](#running-without-docker)
- [Statistics](#statistics)
- [Performance results](#performance-results)
- [Key URLs](#key-urls)
- [Access control](#access-control)
- [Security](#security)
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
| Backend | Django 6.0, Django Channels 4 (ASGI) |
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

## Demo data for development

`seed_dev_data` creates one account per access scenario plus groups, sessions, plans, attendance and swim times, so every rule from [Access control](#access-control) can be tried in the browser within a minute. It only exists for development: it refuses to run with `DEBUG=False` (override with `--force`, never do that in production).

```bash
# with Docker (dev stack running)
docker compose exec app python manage.py seed_dev_data

# without Docker
python manage.py seed_dev_data

# start over: removes everything the command created (and nothing else), then recreates it
python manage.py seed_dev_data --reset
```

The command is idempotent – running it again refreshes passwords and adds whatever is missing. **Every demo account has the password `demo`.**

| Login | Level | Good for trying |
|---|---|---|
| `demo_admin` | Admin | everything; link `demo_unlinked` to a person; create groups; edit exceptions for all sessions |
| `demo_trainer_a` | Trainer of *Demo Group A* | full access in A, basic info only for people of B; accept the pending change proposal of `demo_swimmer_a` |
| `demo_trainer_b` | Trainer of *Demo Group B* | the mirror image – must not see A's contact data, notes or statistics |
| `demo_trainer_free` | Profile trainer without a group | sees name + age of everybody, nothing else; cannot start sessions |
| `demo_assistant` | Assistant in A (swimmer in B) | operate A's sessions, tick plan entries, but no plan editing, no new people, no memberships; in B only a swimmer |
| `demo_swimmer_a` | Swimmer in A | own profile, propose changes, last week's finished session (plan, own status, own times); next week's session shows nothing |
| `demo_swimmer_b` | Swimmer in B | must not see anything of group A |
| `demo_unlinked` | account without a person | admin linking flow |
| *(not logged in)* | Anonymous | calendar with group names only |

Each group has one session on *today's weekday* with no instance yet (open it as a trainer or assistant and press "Start session"), a finished instance last week and an upcoming one next week. A cancellation for all sessions is entered two weeks ahead, and `demo_swimmer_a` has an open change proposal. Tip: use one normal and one private browser window to compare two roles side by side.

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

### Step 2 — Open firewall ports

Ports 80 (HTTP) and 443 (HTTPS) must be reachable from the internet. On Ubuntu with `ufw`:

```bash
sudo ufw allow 80
sudo ufw allow 443
sudo ufw reload
```

### Step 3 — Clone the repository

```bash
git clone https://github.com/your-org/lanekit.git
cd lanekit
```

### Step 4 — Configure environment

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

### Step 5 — Run the certificate init script (once only)

> **Important:** Run this script from the project root directory (the folder containing `docker-compose.prod.yml`), not from inside `docker/certbot/`.

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

### Step 6 — Remove first-boot superuser credentials

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
│  • Django 6.0 / Channels 4 (ASGI)        │
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

## Git on the Server

The production server is typically managed without a Git GUI, so here are the commands you'll need most.

### Deploy a new version

```bash
# Pull the latest code from the remote
git pull

# Rebuild the app image and restart the container
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d app

# Apply any new migrations
docker compose -f docker-compose.prod.yml exec app python manage.py migrate
```

### Check what's changed

```bash
# Show unpushed local commits
git log origin/main..HEAD --oneline

# Show which files differ from the remote
git status

# Show the diff of uncommitted changes
git diff

# Show recent commit history
git log --oneline -10
```

### Undo things

```bash
# Discard all local uncommitted changes (destructive!)
git checkout -- .

# Reset to exactly what's on the remote (destructive!)
git fetch origin
git reset --hard origin/main
```

### Switching branches / tags

```bash
# List available branches
git branch -a

# Switch to a specific branch
git checkout <branch-name>

# Switch back to main
git checkout main
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

## Statistics

Attendance statistics help trainers judge absences and spot people who are missing repeatedly over a longer period. Because club-level decisions are based on them, they are only visible to users whose **profile role is Trainer or Administrator** — being trainer of a single group is *not* enough (group trainers keep their normal live-session rights).

**Where to find them**

| View | Location | Content |
|---|---|---|
| Person | *People → person detail*, section "Attendance statistics" | Attendance rate, present / absent / excused, share of excused absences, current streak of missed sessions, per-session status list |
| Group | *Groups → group detail → Statistics* (`/training/group/<id>/stats/`) | Table per session (present / absent / excused / unknown / rate), summary (sessions, Ø present, rate), ranking of members by attendance (lowest first) |

**Filters** (both views) — quick ranges *Last month* (previous calendar month), *Last 30 days*, *Last quarter*, *Current quarter*, or a custom from/to range; the end is capped at today. Optional sessions can be included via a checkbox.

**How the numbers are defined**

- Attendance rate = present ÷ (present + absent + excused). *Unknown* is shown separately and **never counted as a miss**.
- Excused share = excused ÷ (absent + excused).
- Trainers of the group are left out of group statistics (same as the trainer report). Only sessions that were actually opened (a `SessionInstance` exists) are counted.
- **Optional sessions** — a trainer can mark a session as optional in the session modal (e.g. during holidays, when only a few swimmers are expected). Optional sessions are excluded by default so they don't distort the numbers; the page tells you how many were left out.

**Lanes and utilisation per lane**

- `Location.lanes`, `RecurringSession.lanes` and `SessionInstance.lanes` are all optional; a location without lanes (e.g. a gym) stays valid.
- A recurring slot cannot use more lanes than its location has (checked in the form, admin and session modal). A new slot takes its location's lane count as the default; every new session takes the slot's lane count. A trainer only has to correct a single session when it deviates (lane field in the session modal).
- Lane counts added **retroactively** are back-filled: sessions without a lane count receive it (slot → its sessions, location → its slots and their sessions). Sessions that were already corrected by hand, and history from before a later change (e.g. 6 → 4 lanes), are left untouched.
- Switching on **Per lane** in the group view shows present swimmers per lane for each session and as an average. Sessions without a lane count are not part of the per-lane value; the page shows how many were skipped.

**Upgrading** — this adds migration `training/0007_lanes_optional_sessions.py`; run `python manage.py migrate` (production: `$COMPOSE exec app python manage.py migrate`). New texts are available in all four languages.

---

## Performance results

Trainers can record swim times during a session; the development per swimmer is shown as a chart.

**Recording (trainer of the group, session modal)** — open a session that has been started, expand **Record times**, choose the stroke (freestyle, backstroke, breaststroke, butterfly, medley) and the distance, and enter a time for every swimmer in the table. The table lists everyone currently marked *present* (use *Load present swimmers* after changing attendance); empty rows are skipped and **Enter** jumps to the next swimmer. Starts usually follow performance rather than the name list, so rows can be **dragged by their handle** into start order (*A–Z* resets it); the order is remembered on that device only, so two trainers can time different heats. A check mark with the time next to a swimmer shows that a time for the selected stroke/distance already exists — e.g. entered by the other trainer — so nobody enters it twice. Day and location are taken from the session, the pool length (25 / 50 m) from the location type. All times recorded this way are marked **unofficial**. Recorded times are listed next to the form and can be corrected or deleted there.

**Live sync** — saving, correcting or deleting a time notifies every device connected to the session over the WebSocket (`results_changed`), which then re-fetches the list; so parallel entry by several trainers shows up everywhere within moments, like attendance. The message is sent by the server after the save, never relayed from a client. In polling-fallback mode the list is refreshed together with the 5-second state poll, and after every reconnect.

Accepted time formats: `32,45`, `32.45`, `1:05,32`, `65,32`; a single decimal digit means tenths (`32,1` = 32.10 s). If any time in a submission is invalid nothing is saved and the offending fields are highlighted.

**Chart (person detail → "Performance development")** — one line per combination of stroke, distance and pool length. Filter by stroke, distance, pool length, date range and official / unofficial; *Evaluate pool lengths separately* (default on) can be switched off to merge 25 m and 50 m times into one line per discipline (a warning reminds that these are not directly comparable); click a legend entry to hide or show a single line. The Y axis can show the time or the time per 100 m, so different distances become comparable. Below the chart, a table lists the filtered times and marks the personal best (per line, within the current filter). Triangles mark official times, circles unofficial ones.

**Group overview** — *Groups → group detail → Statistics* has two tabs: *Attendance* (as before) and *Swim times* (`/training/group/<id>/stats/?tab=times`). The times tab uses the same period filter and adds filters for stroke, distance and pool length (separate by default, or merged). For every discipline it ranks the group's active swimmers by best time and shows the latest time, number of times and the development (latest vs. first time in the period, green = faster). Trainers of the group are left out. Like all statistics it is visible to profile trainers and admins only.

**Who sees what** — recording and correcting: trainers of the session's group (and admins). Chart: everyone who may edit the person — profile trainers/admins, trainers of the person's groups and the person themself. Other members do not see anyone's times.

**Data model** — `training.PerformanceResult`: swimmer, optional session, date, optional location, stroke, distance (m), time in hundredths of a second, pool length (25 / 50, derived from the location when empty), `is_official` (always `False` for training times — reserved so competition results can be added later without a schema change), notes, recorded by. Times of different pool lengths are kept in separate lines because they are not directly comparable.

**Upgrading** — this adds migration `training/0008_performance_result.py`; run `python manage.py migrate` (production: `$COMPOSE exec app python manage.py migrate`). The chart uses Chart.js 4.4.7 from jsDelivr, like the other front-end libraries. New texts are available in all four languages.

---

## Key URLs

| URL | Description |
|---|---|
| `/` | Calendar (main page) |
| `/training/events/?start=…&end=…` | Calendar event JSON API (FullCalendar feed; anonymous users get group names and time slots only) |
| `/training/session/<id>/<date>/` | Session modal content – GET=view (full for assistants/trainers, own data for participants of a finished session, 403 anonymous), POST=create instance (assistant or higher) |
| `/training/session/<id>/state/` | Polling fallback – current attendance + plan state (used when the WebSocket drops) |
| `/training/session/<id>/attendance/` | REST attendance update – polling fallback for WebSocket writes |
| `/training/session/<id>/settings/` | Trainer: set a session's lane count and "optional" flag (POST, JSON) |
| `/training/session/<id>/add-swimmer/` | Trainer: add a swimmer to the live session |
| `/training/session/<id>/results/` | Trainer: GET list / POST record swim times (stroke, distance, one time per swimmer; JSON) |
| `/training/result/<id>/update/`, `/training/result/<id>/delete/` | Trainer: correct / delete a recorded time (POST, JSON) |
| `/training/session/<id>/plan-entry/photo-create/` | Trainer: create a plan entry directly from a photo |
| `/training/plan-entry/<id>/photo/` | Trainer: upload/remove the photo of a plan entry |
| `/training/recurring/new/<group_id>/`, `/training/recurring/<id>/edit/` | Trainer: create/edit a recurring session |
| `/training/exception/new/` | Trainer: create a session exception (cancellation) |
| `/training/trainer/report/` | Trainer: quarterly attendance report |
| `/training/group/<id>/stats/` | Trainer of that group / admin: group statistics – tab *Attendance* (default) and `?tab=times` (swim-time ranking) |
| `/ws/session/<instance_id>/` | WebSocket endpoint (live attendance + training plan) |
| `/groups/` | Group list (everybody: name + number of current sessions; trainers/admins: members and detail page of every group, assistants: of their own groups) |
| `/swimmers/` | People list (trainers: name + age of everybody; assistants: members of their groups; swimmers: not available) |
| `/swimmers/<id>/` | Person page – scope depends on the viewer (see *Access control*) |
| `/swimmers/proposals/` | Bell target: open change proposals the user may decide on (trainers of a group, admin) |
| `/swimmers/<id>/propose/` | Swimmer: propose a change to the own record (POST) |
| `/swimmers/<id>/proposals/<req>/approve/`, `…/reject/` | Trainer of one of the person's groups / admin: decide on a proposal (POST) |
| `/accounts/login/` | Login (rate-limited) |
| `/accounts/register/` | Self-registration – only for people already known as a `Swimmer` by e-mail (rate-limited) |
| `/accounts/activate/<uidb64>/<token>/` | Account activation link (from the registration e-mail) |
| `/accounts/verify-email/<token>/` | Confirms an e-mail address change (signed token, 3-day validity) |
| `/accounts/profile/` | Own profile, incl. e-mail change (triggers re-verification) |
| `/accounts/users/`, `/accounts/users/<id>/` | Admin: user list / detail, incl. linking a user to a `Swimmer` |
| `/excuse/<uuid>/` | Self-excuse link (no login needed, single-use UUIDv4 token) |
| `/excuse/generate/` | Trainer: generate a self-excuse link for a swimmer |
| `/set-language/?lang=xx` | Switch UI language (stored in session) |
| `/manifest.webmanifest`, `/sw.js`, `/offline/` | PWA manifest, service worker, offline fallback page |
| `/admin/` | Django admin |

---

## Access control

All access decisions live in one place: **`accounts/permissions.py`**. Views, the WebSocket consumer and the navigation only ask `can_*` functions from that module – nobody tests `profile.role` or `GroupMembership.role` on their own. There are four levels (plus anonymous visitors):

| Level | How someone gets it | What they may do |
|---|---|---|
| **Anonymous** | not logged in | Calendar with group names and time slots only, plus the number of *current* sessions per group on the group list. No locations, no cancellation reasons, no session modal, no member lists. |
| **Swimmer** | profile role *swimmer*, trainer nowhere | Own person page with attendance and swim-time statistics. After a session has ended: the plan entries that were ticked off (open ones stay hidden, no strike-through – that is a trainer-side aid), the own attendance status and the own times. Cannot edit anything directly, but can **propose** changes to their own person record. |
| **Assistant** (Hilfstrainer) | profile role *swimmer* **and** entered as *trainer* in a group | Only in **that** group: everything in the session modal (attendance, notes, lanes, swim times, adding people to the session, excuse links), but plan entries can only be ticked off – not created, edited, deleted or reordered. Sees name + age of the group's members, no contact data. Cannot create people or change memberships. |
| **Trainer** | profile role *trainer* | Sees name + age of **everybody**, the member list and recurring sessions of **every** group (read-only) and the group pills in the people list. In groups where they are entered as trainer: full read/write access to members, sessions, plan, statistics, memberships (including handing out trainer rights), recurring sessions and exceptions. Other groups give no deeper insight – no session modal, attendance, notes, plan, contact data or statistics. Persons outside their groups: basic info and swim-time statistics only. Creates people only into one of their own groups. |
| **Admin** | profile role *admin* | Everything. Exclusive: creating/deleting groups, exceptions that affect *all* sessions, user accounts and roles, swim times that belong to no session, deleting people. |

Things worth knowing:

- **Assistants are not a role of their own.** They are swimmers in the profile who additionally carry a *trainer* entry in a group. A profile trainer without a trainer entry in a group has no group rights there. The old login hook that promoted group trainers to profile role *trainer* is gone – existing accounts it already promoted have to be set back to *swimmer* by an admin (Accounts → user → role) if they should only be assistants.
- **Group rights are per group**, evaluated against *active* memberships. Deactivating a trainer entry takes the rights away immediately, including for a running WebSocket connection (rights are re-checked on every message).
- **Swim times** are only recorded for people on the session's attendance list (members and guests added to the session) – even trainers cannot time someone who is not on that list. Times without a session can only be created or changed by an admin.
- **Change proposals** (`PersonChangeRequest`): a swimmer proposes new values for name, phone, birthday or emergency contact. A trainer of one of the person's groups, or an admin, accepts or rejects; nothing is written before that. Everybody who can decide on proposals gets a **bell icon in the navbar** with the number of open ones; it opens `/swimmers/proposals/`, which lists exactly the proposals they may decide on (current value next to the proposed one, accept/reject in place). Admins see all, trainers those of the active members of their groups. The e-mail address keeps its own verified change flow; account things (password, language, avatar, bio) stay directly editable. Name and phone on the account form are read-only for everybody who may not edit their own person record directly.
- **Persons seen by trainers**: name + age and the group pills for all; contact data, notes and attendance statistics only for members of the trainer's own groups. The person page of someone outside their groups stays at basic info + swim-time statistics. The search field only matches names – e-mail, phone and group names are only searched within people the viewer may see in full.

### Tests – and how to keep them useful

`accounts/test_permissions.py` calls **every endpoint once per role** (anonymous, swimmer, assistant, trainer of the group, trainer of another group, trainer without group, admin). A request counts as denied for 403, a redirect to the login page, or a "no permission" message – and for writes the action's effect must exist *exactly* for the allowed roles. A guard test lists all URL names and **fails when an endpoint is not classified**, so a new route cannot ship without a permission decision. `accounts/test_permissions_behaviour.py` covers what each role sees (modal, person page, lists, search), the rules around memberships, swim times, exceptions, proposals, locked account fields and the WebSocket.

When you add or change something:

1. Put the rule into `accounts/permissions.py` (never inline in a view).
2. Add the endpoint to `rows()` in `accounts/test_permissions.py` – or to `PUBLIC_ENDPOINTS` if it is public by design.
3. Add a positive **and** a negative test for the new rule.

```bash
python manage.py test accounts            # permission tests only
python manage.py test                     # everything
```

---

## Security

LaneKit is reachable from the public internet without a VPN, so the following is in place — and worth knowing about if you deploy it yourself:

- **Transport** — TLS 1.2/1.3 only, HSTS (`includeSubDomains; preload`), and the usual hardening headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`) are set in `docker/nginx/templates/app.conf.template`.
- **Rate limiting** — `/accounts/login/` and `/accounts/register/` are rate-limited per client IP at the nginx layer (`limit_req_zone`), since both can be abused to brute-force or to spam e-mails.
- **Sessions & CSRF** — Session cookies are `SameSite=Lax` and, outside `DEBUG`, `Secure`; `CSRF_TRUSTED_ORIGINS` is derived from `DOMAIN`. Sessions live ~6 months with sliding expiry, by design, so the installed PWA stays logged in.
- **Self-excuse tokens** — `/excuse/<uuid>/` uses a random UUIDv4 per token (122 bits), single-use, and scoped to one `(swimmer, session, date)` triple — not practically guessable.
- **WebSocket authorization** — `SessionConsumer` only accepts connections of staff of that session's group (assistant, trainer, admin) and re-evaluates the user's level on **every** message, so withdrawn rights take effect immediately; assistants cannot structure the plan, and photo broadcasts are re-read from the database instead of relaying client data. Attendance writes are restricted to swimmers who are either active members of that group *or* already have an attendance row for this exact session — the latter covers guests added on the fly via "add swimmer" who aren't group members at all.
- **Calendar API** — `/training/events/` is intentionally public/read-only (see *How It Works* below) but rejects date ranges over 366 days to prevent a single request from forcing an expensive, unbounded query.
- **Uploaded photos** — training-plan photos are verified to be decodable images (Pillow) before being stored, not just trusted by filename/content-type.
- **Scraper honeypot** (`antibot` app) — a link invisible to real visitors (off-screen, `aria-hidden`, not tab-reachable) sits in `base.html`, and its path is disallowed in `/robots.txt`. Anything that requests it anyway — a scraper ignoring `robots.txt`, or one blindly following every raw `<a href>` — gets its IP blocked for 24h by `HoneypotBlockMiddleware`, applied to every route. Blocked IPs are visible/removable under **Admin → Bot-Schutz → Blocked IPs**, in case a shared IP (NAT, corporate proxy) ever trips it.
- **Secrets** — `.env` is git- and docker-ignored; `DB_PASSWORD`, `SECRET_KEY`, SMTP and superuser credentials only ever reach the containers as environment variables, never baked into the image.
- **Known, accepted trade-offs** — the Django admin stays at the default `/admin/` path (protected by normal Django auth, not by obscurity, though it's also listed in `robots.txt`'s `Disallow`); registration e-mail confirms whether an address is already registered (minor enumeration, acceptable for a club-internal tool); the honeypot is one layer, not a general bot defense — a scraper that renders the page with full CSS and only follows visibly-clickable links won't trip it.

If you find a vulnerability, please report it privately to the maintainer rather than opening a public issue.

---

## How It Works

**Calendar** — `/training/events/` iterates the date range, applies exceptions (shown in red), checks for instances (full opacity) vs planned slots (slightly transparent), and returns FullCalendar-compatible JSON. Logged-out users see everything read-only; logged-in users can toggle "My Sessions" to filter to their groups.

**Session Modal** — Clicking a calendar event loads the modal via an AJAX GET. If no instance exists yet, trainers see a "Start Session" button that POSTs to create the instance and pre-populate an attendance row for each group member.

**WebSocket Live Sync** — `SessionConsumer` verifies the connecting user is a trainer of that group, then joins a per-session channel group. Every action (attendance toggle, plan entry CRUD, drag-reorder, notes autosave) is saved to the database and broadcast to every connected client. The coloured dot in the modal corner shows the connection state.

**Statistics** — `training/stats.py` aggregates `Attendance` rows per person or per group with a handful of queries, restricted to profile trainers/admins (see [Statistics](#statistics)). Optional sessions are filtered out unless requested; lane counts are materialised on each `SessionInstance`, so per-lane figures stay correct even if a slot's lane count changes later.

**Excuse Tokens** — A trainer generates a shareable one-time URL via `POST /training/excuse/generate/`. The swimmer visits the link, confirms, and their attendance is automatically set to "excused" — no login required.

**TLS Renewal** — Certbot runs `certbot renew` in a loop inside its own container. nginx picks up new certificates every 12 hours via an internal cron that runs `nginx -s reload`.
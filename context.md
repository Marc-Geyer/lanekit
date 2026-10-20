# LaneKit – Developer Context
> Paste this file at the start of a new Claude session to resume without re-explaining the project.
> Keep it up to date after major changes (`git diff` → Claude → update this file).

---

## Project snapshot

| Item | Value |
|---|---|
| **Name** | LaneKit |
| **Repo** | https://github.com/Marc-Geyer/lanekit |
| **Purpose** | Self-hosted Django app for managing swimming groups, training sessions, live attendance, and club members |
| **License** | GPL-3.0 |
| **Django version** | 6.0 (ASGI via Daphne + Django Channels 4) |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0, Django Channels 4 |
| ASGI server | Daphne 4 |
| WebSockets | channels-redis 4 + **redis-py 4.x** (pinned `<5.0`) |
| Database | PostgreSQL 16 |
| Cache / Channel layer | Redis 7 |
| Reverse proxy (prod) | Nginx 1.27 + Certbot |
| Frontend | Bootstrap 5.3 (RTL for Arabic), FullCalendar 6, SortableJS |
| Fonts | Syne (headings), DM Sans (body), Noto Sans Arabic (Arabic only) |
| Container runtime | Docker + Docker Compose |

---

## Django apps

```
accounts/    UserProfile extends auth.User; roles: admin / trainer / swimmer
swimmers/    Swimmer model (can exist without a User account)
groups/      Group + GroupMembership (role: swimmer / trainer)
training/    RecurringSession, SessionException, SessionInstance,
             TrainingPlanEntry, Attendance, ExcuseToken
             └── consumers.py  SessionConsumer (WebSocket)
             └── routing.py    WebSocket URL patterns
antibot/     Scraper honeypot — BlockedIP model, HoneypotBlockMiddleware,
             trap view linked only via a hidden link in base.html + robots.txt
translations/ Custom i18n package (NOT Django gettext – see below)
```

### Key models
- `UserProfile` — `OneToOneField(User)`, role, phone, bio, avatar
- `Swimmer` — person record, optional `OneToOneField(User)`
- `GroupMembership` — `(group, swimmer, role, active)`
- `RecurringSession` — weekly slot `(group, day_of_week, start_time, end_time, location, valid_from, valid_until)`
- `SessionException` — cancels sessions on a date (affects all or specific sessions)
- `SessionInstance` — created when a trainer first opens a planned session; triggers attendance pre-population
- `TrainingPlanEntry` — ordered exercise blocks with category (warmup/main/cooldown)
- `ExcuseToken` — UUID-based one-time URL for self-excuse without login
- `Attendance` — per-swimmer per-session status (present/absent/excused/unknown)

---

## Translation system (`translations/`)

**Not Django gettext** — a custom lightweight system.

```
translations/
  __init__.py    public API
  registry.py    ← register a new language here (one import + one tuple)
  helpers.py     tr(request, 'msg_key', name=value) for Python views
  en.py          English strings
  de.py          German strings (default)
  uk.py          Ukrainian strings
  ar.py          Arabic strings (RTL)
```

**In templates:** `{{ t.some_key }}` — no {% load %} needed.  
**In views:** `from translations.helpers import tr` → `tr(request, 'msg_profile_updated')`  
**Language switching:** `GET /set-language/?lang=uk&next=/current/path/`  
**Missing key behaviour:** `TranslationDict.__missing__` logs a WARNING and shows `⚠ [key_name]` in DEBUG rather than crashing.  
**Adding a language:** create `translations/xx.py`, add one line to `registry.py`.  
**Context processor** (`swimmingclub/context_processors.py`) injects `t`, `lang`, `is_rtl`, `LANGUAGES` into every template.

---

## Docker setup

| File | Purpose |
|---|---|
| `docker-compose.yml` | **Dev** — bind-mount, Daphne on :8000 direct, no nginx |
| `docker-compose.prod.yml` | **Prod** — nginx + certbot + redis + postgres, HTTPS |
| `docker/app/entrypoint.sh` | Waits for DB+Redis, runs migrate, creates superuser once |
| `docker/nginx/` | Nginx container (Dockerfile + entrypoint + templates) |
| `docker/certbot/init-letsencrypt.sh` | First-time TLS certificate acquisition script |
| `.env.example` | Template for all environment variables |

**Critical .dockerignore rule:** exclude `docker/nginx/` and `docker/certbot/` but **NOT** `docker/app/` — the entrypoint.sh lives there and must be reachable by the Dockerfile `COPY` instruction.

---

## URL map

| URL | View / Purpose |
|---|---|
| `/` | Calendar main page |
| `/training/events/` | FullCalendar JSON feed — public/read-only, capped at 366-day range |
| `/training/session/<id>/<date>/` | Session modal — returns JSON `{html, instance_id, is_trainer}` |
| `/training/session/<id>/state/` | Polling fallback — returns current attendance + plan state |
| `/training/session/<id>/attendance/` | REST attendance update (polling fallback for WS writes) |
| `/training/session/<id>/add-swimmer/` | Trainer: add a swimmer to the live session |
| `/training/session/<id>/plan-entry/photo-create/` | Trainer: new plan entry from a photo |
| `/training/plan-entry/<id>/photo/` | Trainer: upload/remove a plan entry's photo |
| `/training/recurring/new/<group_id>/`, `/training/recurring/<id>/edit/` | Trainer: manage recurring sessions |
| `/training/exception/new/` | Trainer: create a session exception |
| `/training/trainer/report/` | Trainer: quarterly attendance report (time-reporting export) |
| `/training/excuse/generate/` | Trainer: generate a self-excuse link |
| `/ws/session/<instance_id>/` | WebSocket endpoint |
| `/set-language/?lang=xx` | Switch UI language (stored in session) |
| `/groups/` | Group list |
| `/swimmers/` | People search/list |
| `/accounts/login/` | Login (nginx rate-limited) |
| `/accounts/register/` | Self-registration, only for known `Swimmer` e-mails (nginx rate-limited) |
| `/accounts/activate/<uidb64>/<token>/` | Account activation link |
| `/accounts/verify-email/<token>/` | E-mail change confirmation (signed token) |
| `/accounts/profile/`, `/accounts/users/`, `/accounts/users/<id>/` | Own profile / admin user management |
| `/excuse/<uuid>/` | Self-excuse (no login required, single-use UUIDv4) |
| `/manifest.webmanifest`, `/sw.js`, `/offline/` | PWA assets |
| `/robots.txt` | Disallows `/admin/` and `/system/` (the honeypot prefix) |
| `/system/data-export/` | Honeypot trap (antibot app) — not a real endpoint, do not link to it |
| `/admin/` | Django admin |

---

## WebSocket + fallback

1. `calendar.js` fetches session modal → view returns **JSON** `{html, instance_id, is_trainer}` (not bare HTML — `innerHTML` never executes script tags)
2. If `instance_id` and `is_trainer` → `initSessionWebSocket(instanceId)` in `session.js`
3. WS connection: `ws[s]://host/ws/session/<id>/` → `SessionConsumer`
4. **Reconnect:** up to 3 retries with 2 s / 5 s / 10 s backoff
5. **Polling fallback:** after 3 failures → polls `/training/session/<id>/state/` every 5 s; attendance writes use direct `POST /training/session/<id>/attendance/`
6. Status dot: `connected` (green) / `connecting` (yellow pulse) / `polling` (blue pulse) / `error` (red)

---

## Known bugs fixed (do not reintroduce)

| Bug | Root cause | Fix |
|---|---|---|
| `TemplateSyntaxError` on calendar.html | `{{ user.is_authenticated and … }}` — `and` is invalid in `{{ }}` | Use `{% if %}` block to set `IS_TRAINER` JS var |
| WebSocket connects then immediately drops | `innerHTML` silently drops `<script>` tags (browser security) | session_modal_view returns JSON; calendar.js reads instance_id from JSON |
| `redis.exceptions.TimeoutError` on WS | redis-py 5.x uses RESP3 protocol; channels-redis 4.x incompatible | Pin `redis<5.0` in requirements.txt |
| Static files return `text/html` (MIME block) | Daphne doesn't auto-serve `/static/` like runserver does | `staticfiles_urlpatterns()` in urls.py (DEBUG only) |
| `VariableDoesNotExist` for missing translation key | Key absent from language files; plain dict raises on missing key | `TranslationDict.__missing__` fallback; key added to all language files |
| Docker build: entrypoint.sh not found | `.dockerignore` excluded entire `docker/` directory | Changed to exclude only `docker/nginx/` and `docker/certbot/` |

---

## Branding & configuration

```python
# swimmingclub/settings.py
APP_NAME          = 'LaneKit'
ORGANISATION_NAME = os.environ.get('ORGANISATION_NAME', 'My Swimming Club')
DEFAULT_LANGUAGE  = os.environ.get('DEFAULT_LANGUAGE', 'de')
```

Navbar shows `OrgName [LaneKit]` when `ORGANISATION_NAME` is set, else just `LaneKit`.

---

## How to resume this project in a new Claude session

1. Paste this file into the chat
2. Describe what you want to change
3. For code changes you've made: `git diff HEAD~1` or `git diff <hash> <hash>` → paste output

**Do not upload a full zip** — a diff is 50× more token-efficient.

---

## Open / TODO

- [ ] Form field labels are hardcoded in the form classes (not translated) — full translation would require Django's gettext on model verbose_names
- [ ] Consider validating uploaded training-plan photos for size/dimensions too (currently only checked for being a decodable image, no explicit max-resolution guard beyond nginx's 20M body limit)
- [ ] Consider whether `/accounts/register/`'s "e-mail already in use" message (and the equivalent in `UserProfileForm`) should be worded less specifically to reduce account enumeration — accepted as a low-severity trade-off for now in a club-internal tool

## Security review (Oct 2026)

A pass over `swimmingclub/settings.py`, nginx config, `SessionConsumer`, the excuse-token flow, and account/registration views found and fixed:
- `accounts/views.py::check_trainer_status` — `==` instead of `=` meant trainer role promotion on login silently never happened
- `training/views.py::calendar_events_api` — unbounded `start`/`end` date range on a public endpoint could force an expensive query; capped at 366 days
- `training/consumers.py::db_update_attendance` — a trainer could write an attendance row for a `swimmer_id` outside their session's group; now scoped to swimmers who are either group members **or** already have an attendance row for this session (covers non-member guests added via "add swimmer" — first fix was too strict and broke that case, corrected same day)
- `training/views.py` photo upload views — files were saved to the `ImageField` without validation (direct model assignment skips Django's form-level Pillow check); added `_validate_photo()`
- nginx — `/accounts/register/` had no rate limit (only `/accounts/login/` did), despite sending e-mail; added a `register` zone
- Added a scraper honeypot: new `antibot` app (`BlockedIP` model + `HoneypotBlockMiddleware`), a hidden trap link in `base.html`, and `/robots.txt` disallowing the trap path and `/admin/`. 24h IP block on a hit, visible/removable in Django admin under "Bot-Schutz".

See the README's new **Security** section for what's already in place. Nothing above was found to be currently exploitable from outside without a trainer/admin account, except the calendar DoS vector and the registration spam vector, both unauthenticated.
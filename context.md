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
| **Django version** | 4.2 (ASGI via Daphne + Django Channels 4) |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Django 4.2, Django Channels 4 |
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
| `/training/events/` | FullCalendar JSON feed |
| `/training/session/<id>/<date>/` | Session modal — returns JSON `{html, instance_id, is_trainer}` |
| `/training/session/<id>/state/` | Polling fallback — returns current attendance + plan state |
| `/training/session/<id>/attendance/` | REST attendance update (polling fallback for WS writes) |
| `/ws/session/<instance_id>/` | WebSocket endpoint |
| `/set-language/?lang=xx` | Switch UI language (stored in session) |
| `/groups/` | Group list |
| `/swimmers/` | People search/list |
| `/accounts/login/` | Login |
| `/excuse/<uuid>/` | Self-excuse (no login required) |
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

- [ ] Push source code to github.com/Marc-Geyer/lanekit
- [ ] Document account security additions (login requirements on persons/calendar — added locally, not yet in context)
- [ ] Form field labels are hardcoded in the form classes (not translated) — full translation would require Django's gettext on model verbose_names
- [ ] Production deployment not yet tested end-to-end
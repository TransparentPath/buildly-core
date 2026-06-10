# CLAUDE.md — buildly-core

## Workflow Rules (MUST FOLLOW)

1. **Always use the Django Developer agent** - Use `@agent/django-developer.md` for all work in this repository.
2. **Plan first** - Always plan changes before implementing anything. Enter plan mode to analyze the codebase and design the approach. Save the plan in `./.claude/plans` folder.
3. **Verify before implementing** - Present the plan to the user and wait for explicit approval before making any changes.
4. **Explicit permission required** - Only make code changes when the user explicitly asks to proceed with implementation. Do not modify files without clear permission.
5. **File creation restricted to .claude folder** - All files created by Claude must be placed in the `./.claude` folder only, unless the user explicitly specifies a different location.
6. **Task tracking required** - Always create tasks when executing an approved plan. Update the task status as you work on each item.
7. **Update documentation after every change** - After any codebase change, always update `.claude/CLAUDE.md` before finishing. This is mandatory. Update the Last Updated date, reflect any new files, fonts, patterns, or architecture decisions, move resolved issues to the Resolved section, and add any new open issues. Never end a session without documentation being current.

---

## Project Overview

buildly-core is a **component-based API gateway** for cloud-native microservice architectures. It handles:

- Centralized authentication (OAuth2 + JWT) for all downstream services
- Transparent HTTP proxying to registered microservices ("Logic Modules")
- Cross-service data joining via **DataMesh** (a graph of relationships between remote model endpoints)
- Multi-tenant organization and user management
- Workflow hierarchy management (WorkflowLevel1 / WorkflowLevel2 projects)

It is purpose-built for the TransparentPath supply-chain tracking platform but is a generic gateway framework.

---

## Tech Stack

| Component | Version / Package |
|-----------|------------------|
| Python | 3.11 (alpine Docker image) |
| Django | 5.0.x |
| Django REST Framework | 3.15.x |
| Auth | `django-oauth-toolkit` 3.0.1 + `djangorestframework-simplejwt` 5.4.x + `PyJWT` 2.8+ |
| Database | PostgreSQL 15 (psycopg2-binary) |
| Async HTTP | `aiohttp` 3.10.x |
| Swagger/OpenAPI | `drf-yasg` 1.21.7, `bravado-core` 5.13.1, `pyswagger` 0.8.39 |
| CORS | `django-cors-headers` 4.3.1 |
| Filters | `django-filter` 23.5 |
| LDAP (optional) | `django-auth-ldap` |
| Production server | `gunicorn` 22.x |
| Testing | `pytest-django`, `factory_boy` 3.3, `httpretty`, `pytest-asyncio`, `coverage` |
| Linting | `flake8` (max line length 120), `bandit` |

---

## Directory Structure

```
buildly-core/
├── buildly/               # Django project package (settings, wsgi, management commands)
│   ├── settings/
│   │   ├── base.py        # Core settings; all env vars consumed here
│   │   ├── authentication.py  # OAuth2, JWT, LDAP config
│   │   ├── email.py       # Email backend config
│   │   └── production.py  # Composes base + auth + email; adds CORS, ALLOWED_HOSTS
│   ├── management/commands/
│   │   └── loadinitialdata.py  # Seeds Groups, default Org, superuser
│   └── wsgi.py
├── core/                  # User/org management, auth endpoints, permissions
│   ├── models.py          # CoreUser, Organization, CoreGroup, LogicModule, Consortium, etc.
│   ├── views/             # ViewSets split by domain (coreuser, coregroup, oauth, organization, …)
│   ├── serializers.py
│   ├── permissions.py     # IsSuperUser, AllowOnlyOrgAdmin, IsOrgMember, etc.
│   ├── middleware.py      # DisableCsrfCheck, ExceptionMiddleware
│   ├── jwt_utils.py       # JWT payload enricher, invitation tokens
│   ├── utils.py           # generate_access_tokens (OAuth2 bearer + JWT)
│   ├── auth_pipeline.py   # Social-auth / OAuth domain whitelisting logic
│   └── email_utils.py
├── gateway/               # API gateway: proxies requests to Logic Modules
│   ├── views.py           # APIGatewayView, APIAsyncGatewayView
│   ├── request.py         # GatewayRequest (sync), AsyncGatewayRequest
│   ├── clients.py         # SwaggerClient, AsyncSwaggerClient (Bravado-based)
│   ├── aggregator.py      # SwaggerAggregator — merges specs from multiple services
│   ├── permissions.py     # AllowLogicModuleGroup (CRUD bitmask check)
│   ├── urls.py            # Gateway catch-all regex routes + Swagger UI
│   └── __init__.py        # API_GATEWAY_RESERVED_NAMES list
├── datamesh/              # Cross-service data joining
│   ├── models.py          # LogicModuleModel, Relationship, JoinRecord
│   ├── services.py        # DataMesh class — orchestrates join expansion
│   └── views.py / urls.py
├── workflow/              # Workflow hierarchy (projects / tasks)
│   ├── models.py          # WorkflowLevel1, WorkflowLevel2, WorkflowTeam, etc.
│   └── views.py / urls.py
├── factories/             # factory_boy factories for all apps (used in tests only)
├── scripts/               # Shell helpers for Docker / CI
├── requirements/
│   ├── base.txt
│   ├── production.txt     # base + gunicorn
│   ├── ci.txt             # base + test tooling (no ipython)
│   ├── test.txt           # ci + ipython/ipdb for local dev
│   └── dev.txt            # base + flake8/bandit
├── templates/             # Django HTML templates (email, index, unauthorized)
├── static/                # Static assets
├── conftest.py            # Pytest session fixtures (APIRequestFactory, WSGIRequest factory)
├── setup.cfg              # pytest config + flake8 config
└── .coveragerc            # Coverage omit rules
```

---

## Django Apps

| App | Purpose |
|-----|---------|
| `core` | Custom user model (`CoreUser`), organizations, groups, logic module registry, OAuth/JWT auth endpoints |
| `gateway` | Transparent reverse proxy: routes `/service/model/[pk]/` to registered microservices |
| `datamesh` | Cross-service relationship graph; join records for expanding response payloads across services |
| `workflow` | WorkflowLevel1 (programs/projects) and WorkflowLevel2 (sub-tasks/items), status, type, team membership |
| `buildly` | Project config package; also houses the `loadinitialdata` management command |

`ROOT_URLCONF = 'core.urls'` — `core/urls.py` is the single URL entry point.

---

## Key Models

### core
- **`CoreUser`** — Extends `AbstractUser`. FKs to `Organization`; M2M to `CoreGroup`. Has `is_org_admin` / `is_global_admin` computed properties.
- **`Organization`** — UUID PK. Has `oauth_domains` ArrayField for SSO domain mapping, sensor-threshold defaults, reseller flag, and `organization_type` FK.
- **`CoreGroup`** — Org-scoped or global permission group. `permissions` is a 4-bit integer (CRUD bitmask, 0–15). Auto-created (Admins + Users groups) when an Org is saved.
- **`LogicModule`** — Registry entry for each downstream microservice. Stores `endpoint`, `endpoint_name`, `api_specification` (cached Swagger JSON), and M2M to `CoreGroup`.
- **`EmailTemplate`** — Per-org templates for password reset and invitation emails.
- **`PasswordResetCode`** — Stores a 6-digit cryptographically secure reset code per user. Fields: `user` (FK to CoreUser), `code` (6-char), `created_at`, `expires_at` (15 min TTL, hardcoded), `is_used` (bool). Old unused codes are marked `is_used=True` (never deleted) when a new request is made. Used by the `reset_password` flow.
- **`Consortium`** — Groups multiple organizations together (used for custody/shipment data sharing).

### datamesh
- **`LogicModuleModel`** — Maps a service endpoint name + model endpoint path to a lookup field.
- **`Relationship`** — Directed edge between two `LogicModuleModel` nodes. Reverse relationship is prevented by validation.
- **`JoinRecord`** — Instance-level join: links a record (by int ID or UUID) in one service to a record in another, scoped to an Organization.

### workflow
- **`WorkflowLevel1`** — Top-level program/project, owned by an Organization.
- **`WorkflowLevel2`** — Child item under a WL1. Has `type`, `status`, `parent_workflowlevel2` (self-reference via int), `created_by`.
- **`WorkflowTeam`** — User-to-WL1 membership with a Django `Group` role.

---

## API Structure

### URL Routing

```
/                          → IndexView (template)
/admin/                    → Django admin
/health_check/             → django-health-check
/docs/                     → Swagger UI (drf-yasg)

# Core router endpoints (SimpleRouter)
/coreuser/
/coregroups/
/organization/
/logicmodule/
/consortium/
/organization_type/
/oauth/accesstokens/
/oauth/applications/
/oauth/refreshtokens/

# Auth
/oauth/login/              → POST: username+password+client_id → access_token + JWT
/oauth/refresh/            → POST: refresh_token+client_id → new access_token + JWT

# Workflow
/workflowlevel1/ … /workflowlevelstatus/   (SimpleRouter)

# DataMesh
/datamesh/joinrecords/ … /datamesh/relationships/

# API Gateway catch-all (LAST, order matters)
/<service>/<model>/[pk]/   → APIGatewayView (sync)
/async/<service>/<model>/[pk]/  → APIAsyncGatewayView
```

`API_GATEWAY_RESERVED_NAMES` in `gateway/__init__.py` lists prefixes excluded from the catch-all regex.

### Authentication Flow

1. Client POSTs credentials to `/oauth/login/` with `client_id`.
2. Server authenticates, creates an OAuth2 `BearerToken` (via `django-oauth-toolkit`), then generates an additional `access_token_jwt` (HS256, enriched with `core_user_uuid` and `organization_uuid`).
3. Response contains both `access_token` (opaque DOT token) and `access_token_jwt`.
4. The JWT payload is enriched by `core.jwt_utils.payload_enricher`.
5. Refresh via `/oauth/refresh/` accepts a `refresh_token` and regenerates both tokens.

Default auth classes (base settings): `SessionAuthentication`, `TokenAuthentication`.
Production adds: `OAuth2Authentication`.

### Gateway Proxying

When a request hits `/<service>/<model>/[pk]/`:
1. `AllowLogicModuleGroup` permission checks the user's `CoreGroup` CRUD bitmask against the `LogicModule`'s associated groups.
2. `GatewayRequest.perform()` fetches the Swagger spec for the service (from DB cache or live endpoint), validates the operation, then issues a `requests` HTTP call to the service.
3. If `?join` query param is present on a GET, `DataMesh.extend_data()` fetches related records from other services and injects them into the response payload.
4. Async variant (`/async/…`) uses `aiohttp` and `asyncio.run()`.

---

## Settings & Configuration

Settings follow a **composition** pattern (not file-based profiles):

```
buildly/settings/
  base.py           ← always loaded; reads DATABASE_*, SECRET_KEY, etc.
  authentication.py ← OAuth2, JWT RSA keys, LDAP; extends base
  email.py          ← SMTP or locmem backend; extends base
  production.py     ← imports base + authentication + email; adds CORS, ALLOWED_HOSTS, logging
```

`DJANGO_SETTINGS_MODULE` defaults to `buildly.settings.production` in docker-compose; set as needed locally.

### Required Environment Variables

| Variable | Notes |
|----------|-------|
| `SECRET_KEY` | Django secret key |
| `DATABASE_ENGINE` | e.g. `postgresql` |
| `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` | DB credentials |
| `DATABASE_HOST`, `DATABASE_PORT` | DB connection |
| `ALLOWED_HOSTS` | Comma-separated |
| `CORS_ORIGIN_WHITELIST` | Comma-separated URLs |
| `JWT_PRIVATE_KEY_RSA_BUILDLY` | RSA private key (newlines as `\n`) |
| `JWT_PUBLIC_KEY_RSA_BUILDLY` | RSA public key |
| `JWT_ISSUER` | JWT `iss` claim value |
| `OAUTH_CLIENT_ID` | Default OAuth application client ID |
| `OAUTH_CLIENT_SECRET` | Default OAuth application client secret |
| `ACCESS_TOKEN_EXPIRE_SECONDS` | OAuth token TTL (default 36000) |
| `DEFAULT_ORG` | Name of the auto-created default organization |
| `FRONTEND_URL` | Used in invitation/password-reset links |

Optional: `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_HOST_USER/PASSWORD`, `LDAP_ENABLE` + related LDAP vars, `SUPER_USER_PASSWORD`, `TP_SHIPMENT_URL`, `SUPPORT_EMAIL_ADDRESS`.

---

## Development Workflow

### Docker Compose (recommended)

```bash
docker compose up         # starts postgres_buildly + buildly on :8080
docker compose down
```

The `buildly` container runs `scripts/run-standalone-dev.sh`, which:
- Waits for Postgres
- Runs `makemigrations` + `migrate`
- Runs `loadinitialdata` (creates default org, groups, superuser)
- Starts gunicorn with `--reload` on port 8080

### Local (without Docker)

```bash
pip install -r requirements/test.txt
export DJANGO_SETTINGS_MODULE=buildly.settings.production
export SECRET_KEY=... DATABASE_ENGINE=postgresql ...  # (see docker-compose.yml for a full example set)
python manage.py migrate
python manage.py loadinitialdata
python manage.py runserver 8080
```

### Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

The CI test script also verifies no pending migrations with `makemigrations --check --dry-run`.

---

## Testing

Framework: **pytest-django** (`setup.cfg` drives discovery).

```bash
# Full test suite with coverage
pytest

# Keep the test DB between runs (faster local iteration)
pytest --reuse-db

# Via the helper script (Alpine/Docker context)
bash scripts/run-tests.sh
bash scripts/run-tests.sh --keepdb
bash scripts/run-tests.sh --ci     # also runs flake8 + coverage report
```

Tests live in `<app>/tests/test_*.py`. Factories live in `factories/` (not per-app).

Coverage config: `/.coveragerc` omits migrations, settings, test files, wsgi.

The CI workflow (`.github/workflows/unit_test.yml`) runs tests via `docker compose run` on every PR.

---

## Deployment

- **Container**: `python:3.11-alpine`, exposes port 8080, version label set in `Dockerfile` (`2.0.0`).
- **Production entrypoint**: `scripts/docker-entrypoint.sh` — migrates, collects static, starts gunicorn (no `--reload`, no `loadinitialdata`).
- **CI/CD**: GitHub Actions in `.github/workflows/`
  - `unit_test.yml` — runs on every PR.
  - `dev-build.yml` / `demo-build.yml` / `prod-build.yml` — push to `dev` / `demo` / `prod` branches triggers build + push to Google Artifact Registry (`us-docker.pkg.dev/spry-bricolage-298920/gcr.io/`).
  - `prod-build.yml` also auto-tags via Dockerfile label, creates a GitHub release, and patches `TransparentPath/ops` Kubernetes manifest.
- **Pre-commit**: `.pre-commit-config.yaml` blocks direct commits to `prod`, `demo`, `dev` branches.

---

## Code Conventions

- **Views**: ViewSets split into per-domain files under `core/views/` (not a single `views.py`). `core/views/__init__.py` re-exports all ViewSet classes.
- **Serializers**: Action-specific serializers controlled via `SERIALIZERS_MAP` dict inside ViewSets.
- **Permissions**: 4-bit CRUD bitmask (`permissions` int on `CoreGroup`). Helper functions `merge_permissions` / `has_permission` in `core/permissions.py`.
- **Factories**: All `factory_boy` factories live in `factories/` at project root; imported directly in test files.
- **Flake8**: Excludes `settings`, `manage.py`, `wsgi.py`, `migrations`, `models.py`, `tests`. Max line length 120.
- **Type hints**: Used selectively in gateway/datamesh service layer, not enforced project-wide.
- **Async**: `AsyncGatewayRequest` uses `asyncio.run()` inside a sync Django view (WSGI). Not ASGI — there is no `asgi.py`.

---

## Gotchas / Non-Obvious Things

1. **CSRF is globally disabled** via `core.middleware.DisableCsrfCheck`. All API endpoints are CSRF-exempt; security relies entirely on OAuth2/JWT bearer tokens.

2. **Two tokens on login**: `/oauth/login/` returns both an opaque OAuth2 `access_token` and a signed `access_token_jwt`. Downstream services should validate the JWT. The `payload_enricher` in `core/jwt_utils.py` injects `core_user_uuid` and `organization_uuid` into the JWT payload.

3. **`makemigrations` runs at container startup** (`run-standalone-dev.sh`). In production (`docker-entrypoint.sh`), only `migrate` runs — new migration files must be committed.

4. **LogicModule.api_specification caching**: The first gateway request to a service fetches and caches the Swagger spec in `LogicModule.api_specification` (DB column). If a service's API changes, the cached spec must be cleared (set to `null`) via admin or shell.

5. **Gateway reserved names**: Prefixes in `gateway.API_GATEWAY_RESERVED_NAMES` are excluded from the catch-all proxy regex. Adding a new top-level URL prefix requires adding it to this list.

6. **Permission bitmask encoding**: `CoreGroup.permissions` is an integer 0–15 representing 4 CRUD bits. `display_permissions` property returns the 4-character binary string. `0 = no access`, `4 = view only (0100)`, `14 = no delete (1110)`, `15 = full (1111)`.

7. **Organization auto-creates CoreGroups**: `Organization.save()` calls `_create_initial_groups()` on creation, always producing an "Admins" group (permissions=15) and a "Users" group (permissions=4, is_default=True). New `CoreUser` instances automatically inherit default groups.

8. **`loadinitialdata` idempotent**: Safe to run multiple times; uses `get_or_create` throughout. Creates superuser only if none exists.

9. **DataMesh join requires `?join` query param**: The gateway only triggers cross-service data aggregation when `join` appears in query params on a GET returning 200. Without it, the response is a plain proxy of the upstream service.

10. **`feat/2.0-changes` branch context**: The `RefreshView` (`/oauth/refresh/`) and `RefreshTokenViewSet` were recently added on this branch. `generate_access_tokens` in `core/utils.py` handles both the OAuth2 bearer token and JWT generation in one call; it now respects `ACCESS_TOKEN_EXPIRE_SECONDS` from settings (previously oauthlib defaulted to 3600s regardless of config).

11. **`docker-compose.yml` contains example secrets** (RSA keys, SMTP password, OAuth credentials). These are for local dev only — never commit real production secrets.

12. **`reset_password` uses 6-digit code, not uid/token link**: As of 2026-06-10, `POST /coreuser/reset_password/` generates a `PasswordResetCode` (DB-backed, 15-min TTL) and emails it via `templates/email/coreuser/password_reset.{html,txt}` (template context var: `{{ reset_password_code }}`). The serializer looks up users by `username` field (not `email`), even though the payload key is still `email`. The email is sent to `user.email` (the on-record address) — not back to the payload value. The `EmailTemplate` org-override branch was dropped; file-based templates only. Subject is `'Forgot Password'`. Response: `{"detail": "The reset password code was sent successfully.", "count": <N>}`. Verified working via Postman against `docker compose up` on 2026-06-10.

13. **`reset_password_check` always returns HTTP 200**: As of 2026-06-10, `POST /coreuser/reset_password_check/` accepts `{email, code}` and **always returns HTTP 200**. The outcome is signalled by an `is_valid` boolean in the body, not by the status code. Valid → `{"message": "Reset code verified and found valid", "is_valid": true}`. Any failure (no user, wrong code, expired, already-used) → `{"message": "Invalid code or code has expired. Please resend code and try again.", "is_valid": false}` — uniform body for all failures (enumeration-safe). Verification is read-only: the code is **not** marked `is_used=True` here (that happens in `reset_password_confirm` once it's rewritten). Missing/malformed fields still return DRF's default 400. View logic lives in `core/views/coreuser.py`; serializer (`CoreUserResetPasswordCheckSerializer`) is field-shape only. Verified working by user on 2026-06-10.

14. **`reset_password_confirm` uses 6-digit code (uid/token retired)**: As of 2026-06-10, `POST /coreuser/reset_password_confirm/` accepts `{email, code, new_password1, new_password2}` and follows proper HTTP semantics (200 on actual password change, 400 on any failure). Response key is `message` (matching `reset_password_check`). Success → `{"message": "The password was changed successfully."}`. Uniform failure body for unknown email / **inactive user** / wrong code / expired / already-used: `{"message": "Invalid code or code has expired. Please resend code and try again."}` (enumeration-safe). Password mismatch and weak-password errors return their own specific messages (weak password returns only `exc.messages[0]` — the first Django validator message). User lookup is `CoreUser.objects.filter(username=email, is_active=True)` — inactive users are blocked. On success the view atomically (via `transaction.atomic()`) sets the new password AND flips `PasswordResetCode.is_used=True` to prevent replay. All uid/token / `default_token_generator` / `urlsafe_base64_*` code is gone from `core/serializers.py` and `core/tests/fixtures.py`; the old `reset_password_request` fixture was deleted.

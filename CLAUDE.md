# CLAUDE.md — buildly-core

## Workflow Rules (MUST FOLLOW)

1. **Always use the Django Developer agent** - Use `@agent/django-developer.md` for all work in this repository.
2. **Plan first** - Always plan changes before implementing anything. Enter plan mode to analyze the codebase and design the approach. Save the plan in `./.claude/plans` folder.
3. **Verify before implementing** - Present the plan to the user and wait for explicit approval before making any changes.
4. **Explicit permission required** - Only make code changes when the user explicitly asks to proceed with implementation. Do not modify files without clear permission.
5. **File creation restricted to .claude folder** - All files created by Claude must be placed in the `./.claude` folder only, unless the user explicitly specifies a different location.
6. **Task tracking required** - Always create tasks when executing an approved plan. Update the task status as you work on each item.
7. **Update documentation after every change** - After any codebase change, always update `.claude/CLAUDE.md` before finishing. This is mandatory. Update the Last Updated date, reflect any new files, fonts, patterns, or architecture decisions, move resolved issues to the Resolved section, and add any new open issues. Never end a session without documentation being current.
8. **Keep docs precise & within size caps (never bloat)** - These files have hard line limits; when an edit would exceed the cap, condense/consolidate existing content (summarize completed work, collapse per-item history, drop stale facts) rather than letting it grow:
   - `CLAUDE.md` ≤ 180 lines
   Write tersely; prefer summaries over blow-by-blow detail.

---

## Project Overview

buildly-core is a component-based **API gateway** for cloud-native microservices: centralized OAuth2+JWT auth, transparent HTTP proxying to registered "Logic Modules", cross-service data joining (DataMesh), multi-tenant org/user management, and workflow hierarchy (WorkflowLevel1/2). Purpose-built for the TransparentPath supply-chain platform.

## Tech Stack

Python 3.11 (alpine) · Django 5.0 · DRF 3.15 · PostgreSQL 15 · `django-oauth-toolkit` 3.0.1 + `djangorestframework-simplejwt` 5.4 + `PyJWT` 2.8+ · `drf-yasg` 1.21.7 (Swagger) · `bravado-core` 5.13.1 + `pyswagger` 0.8.39 · `aiohttp` 3.10 · `django-cors-headers` 4.3.1 · `django-filter` 23.5 · `django-auth-ldap` (optional) · `gunicorn` 22 · `pytest-django` + `factory_boy` 3.3 + `httpretty` + `pytest-asyncio` · `flake8` (max line 120) + `bandit`.

## Top-Level Layout

| Dir | Purpose |
|---|---|
| `buildly/` | Django project pkg: settings (`base.py` + `authentication.py` + `email.py` + `production.py`), management commands (`loadinitialdata`), `wsgi.py`. `ROOT_URLCONF = 'core.urls'`. No `asgi.py`. |
| `core/` | CoreUser/Organization/CoreGroup/LogicModule models, auth endpoints, permissions, JWT utils. ViewSets split per-domain in `core/views/` (re-exported via `__init__.py`). |
| `gateway/` | API gateway: `APIGatewayView` (sync) + `APIAsyncGatewayView`, `SwaggerClient`/`SwaggerAggregator`, `AllowLogicModuleGroup` permission, catch-all URL regex (excludes prefixes in `API_GATEWAY_RESERVED_NAMES`). |
| `datamesh/` | Cross-service joins: `LogicModuleModel`, `Relationship`, `JoinRecord`. `DataMesh.extend_data()` triggered by `?join` query param. |
| `workflow/` | `WorkflowLevel1` (programs), `WorkflowLevel2` (sub-items, self-referencing), `WorkflowTeam`. |
| `factories/` | All `factory_boy` factories (root, not per-app). |
| `requirements/` | `base.txt`, `production.txt`, `ci.txt`, `test.txt`, `dev.txt`. |
| `templates/`, `static/`, `scripts/`, `conftest.py`, `setup.cfg`, `.coveragerc` | Standard. |

## Key Models

- **`CoreUser`** (extends `AbstractUser`): FK→`Organization`, M2M→`CoreGroup`, `core_user_uuid`, alert-preferences JSON, `profile_pic` (base64 data URL TextField), `is_org_admin`/`is_global_admin` props.
- **`Organization`** (UUID PK): `oauth_domains` ArrayField, reseller flag, `organization_type` FK. `save()` auto-creates "Admins" (perms=15) + "Users" (perms=4, is_default=True) `CoreGroup`s.
- **`CoreGroup`**: Org-scoped or global. `permissions` int 0–15 = 4-bit CRUD bitmask. `display_permissions` returns 4-char binary string.
- **`LogicModule`**: Registry for each downstream microservice — `endpoint`, `endpoint_name`, cached `api_specification` (Swagger JSON), M2M→`CoreGroup`.
- **`PasswordResetCode`**: 6-digit code per user, 15-min TTL (hardcoded), `is_used` bool. Old unused codes marked is_used=True (never deleted) on new request.
- **`EmailTemplate`**, **`Consortium`**: per-org templates; cross-org grouping for custody data sharing.
- **datamesh**: `LogicModuleModel` (service+endpoint→lookup field) → `Relationship` (directed; reverse blocked by validation) → `JoinRecord` (instance-level join, org-scoped).
- **workflow**: WL1 (org-owned program) → WL2 (typed/status'd child, `created_by`, self-ref via int) + `WorkflowTeam` (user→WL1 role).

## API Structure

URLs (in order — gateway catch-all is LAST): `/admin/`, `/health_check/`, `/docs/` (Swagger UI), `/coreuser/`, `/coregroups/`, `/organization/`, `/logicmodule/`, `/consortium/`, `/organization_type/`, `/oauth/accesstokens/`, `/oauth/applications/`, `/oauth/refreshtokens/`, `/oauth/login/`, `/oauth/refresh/`, `/workflowlevel{1,2}/`, `/workflowleveltype/`, `/workflowlevelstatus/`, `/datamesh/joinrecords/…`, then `/<service>/<model>/[pk]/` → gateway proxy (and `/async/…` for the aiohttp variant).

**Auth flow:** POST creds + `client_id` to `/oauth/login/` → server creates OAuth2 `BearerToken` via DOT, then mints an extra HS256 `access_token_jwt` enriched by `core.jwt_utils.payload_enricher` with `core_user_uuid` + `organization_uuid`. Response carries BOTH `access_token` (opaque) and `access_token_jwt`. `/oauth/refresh/` regenerates both. Default auth in base = SessionAuth + TokenAuth; production adds OAuth2Authentication.

**Gateway proxy:** `AllowLogicModuleGroup` checks user CRUD bitmask against the LogicModule's groups → `GatewayRequest.perform()` fetches Swagger (DB cache or live) → forwards via `requests`. `?join` on a GET 200 triggers `DataMesh.extend_data()` to fold in related records. Async variant uses `asyncio.run()` inside the sync WSGI view.

## Settings & Env

Composition pattern under `buildly/settings/`: `base.py` → `authentication.py` + `email.py` → `production.py` (adds CORS, ALLOWED_HOSTS, logging). `DJANGO_SETTINGS_MODULE` defaults to `buildly.settings.production` in docker-compose.

Required env: `SECRET_KEY`, `DATABASE_{ENGINE,NAME,USER,PASSWORD,HOST,PORT}`, `ALLOWED_HOSTS`, `CORS_ORIGIN_WHITELIST`, `JWT_{PRIVATE,PUBLIC}_KEY_RSA_BUILDLY` (`\n`-escaped), `JWT_ISSUER`, `OAUTH_CLIENT_{ID,SECRET}`, `ACCESS_TOKEN_EXPIRE_SECONDS` (default 36000), `DEFAULT_ORG`, `FRONTEND_URL`. Optional: `EMAIL_*`, `LDAP_*`, `SUPER_USER_PASSWORD`, `TP_SHIPMENT_URL`, `SUPPORT_EMAIL_ADDRESS`.

**No file/media infra:** no `MEDIA_ROOT`/`MEDIA_URL`, no Pillow, no upload volumes. `STATIC_ROOT='/static/'` only. Profile pictures use base64-in-DB (see gotcha 12).

## Dev Workflow

`docker compose up` → starts `postgres_buildly` + `buildly` (gunicorn `--reload` on :8080) and runs `scripts/run-standalone-dev.sh` which waits for PG, `makemigrations`+`migrate`, `loadinitialdata`. Local: `pip install -r requirements/test.txt` + export env + `manage.py migrate` + `loadinitialdata` + `runserver 8080`.

## Testing

`pytest` (config in `setup.cfg`). Tests in `<app>/tests/test_*.py`. `pytest --reuse-db` keeps the test DB. `bash scripts/run-tests.sh [--keepdb|--ci]` for the Alpine/Docker context (`--ci` also runs flake8 + coverage). Coverage omits migrations/settings/tests/wsgi (`.coveragerc`). CI runs via `docker compose run` (`.github/workflows/unit_test.yml`). The script also asserts no pending migrations via `makemigrations --check --dry-run`.

## Deployment

Container: `python:3.11-alpine`, port 8080, version label in `Dockerfile`. Prod entrypoint `scripts/docker-entrypoint.sh` (migrate + collectstatic + gunicorn — NO `--reload`, NO `loadinitialdata`). GitHub Actions: `unit_test.yml` on every PR; `dev/demo/prod-build.yml` build+push to GAR (`us-docker.pkg.dev/spry-bricolage-298920/gcr.io/`); `prod-build.yml` also tags, releases, and patches the `TransparentPath/ops` k8s manifest. `.pre-commit-config.yaml` blocks direct commits to `prod`/`demo`/`dev`.

## Code Conventions

- ViewSets split per-domain under `core/views/`; action→serializer via `SERIALIZERS_MAP` dict.
- 4-bit CRUD bitmask permissions. Helpers `merge_permissions`/`has_permission` in `core/permissions.py`.
- All factories in `factories/` (project root). Imported directly in tests.
- Flake8: max 120; excludes `settings`, `manage.py`, `wsgi.py`, `migrations`, `models.py`, `tests`.
- Type hints used selectively in gateway/datamesh service layer; not enforced project-wide.

## Gotchas / Non-Obvious Things

1. **CSRF globally disabled** via `core.middleware.DisableCsrfCheck`. All APIs are CSRF-exempt; security is on OAuth2/JWT bearer tokens only.
2. **Two tokens on login:** `/oauth/login/` returns BOTH `access_token` (opaque DOT) and `access_token_jwt` (HS256, enriched). Downstream services should validate the JWT.
3. **`makemigrations` runs at container startup** (dev script only). Prod entrypoint runs `migrate` only — new migration files MUST be committed.
4. **LogicModule.api_specification is cached** in DB after the first gateway request. If a service's API changes, clear the cached spec to `null` via admin/shell.
5. **Gateway reserved names:** prefixes in `gateway.API_GATEWAY_RESERVED_NAMES` are excluded from the catch-all proxy regex. Adding a new top-level URL requires adding it here.
6. **Permission bitmask:** `CoreGroup.permissions` int 0–15. `0`=none, `4`=view only (`0100`), `14`=no delete (`1110`), `15`=full (`1111`).
7. **Organization auto-creates groups:** `Organization.save()` always creates "Admins" (15) + "Users" (4, is_default=True). New `CoreUser`s inherit default groups via `save()`.
8. **`loadinitialdata` idempotent:** safe to re-run; uses `get_or_create`. Creates superuser only if none exists.
9. **DataMesh requires `?join` query param** on a GET returning 200 to trigger cross-service aggregation. Without it the gateway is a plain proxy.
10. **`generate_access_tokens`** (`core/utils.py`) returns both OAuth2 bearer + JWT in one call and now respects `ACCESS_TOKEN_EXPIRE_SECONDS` (oauthlib previously defaulted to 3600s).
11. **`docker-compose.yml` contains example secrets** (RSA keys, SMTP, OAuth) — dev only; never commit real prod secrets.
12. **Password-reset flow uses a 6-digit code (not uid/token link)** — verified working 2026-06-10. Three endpoints, all looking up by `username=email` (payload key is still `email`):
    - `POST /coreuser/reset_password/` → generates a `PasswordResetCode` (15-min TTL), marks any prior codes `is_used=True`, emails the code via `templates/email/coreuser/password_reset.{html,txt}` (context var `{{ reset_password_code }}`). Subject `'Forgot Password'`. Email goes to `user.email` on record, NOT the payload value. No `EmailTemplate` override — file templates only. Response: `{"detail": "The reset password code was sent successfully.", "count": <N>}`.
    - `POST /coreuser/reset_password_check/` → **always 200**; outcome carried by `is_valid` boolean. Valid → `{"message": "Reset code verified and found valid", "is_valid": true}`. Any failure → `{"message": "Invalid code or code has expired. Please resend code and try again.", "is_valid": false}` (enumeration-safe). Read-only — does NOT flip `is_used`. Missing/malformed fields still return DRF's default 400.
    - `POST /coreuser/reset_password_confirm/` → proper HTTP 200/400 semantics. Body: `{email, code, new_password1, new_password2}`. Filters `username=email, is_active=True` (inactive users blocked). Uniform failure body (same string as above) for unknown email / inactive / wrong code / expired / used. Password-mismatch and weak-password errors return their specific messages (weak password = `exc.messages[0]` only). On success, `transaction.atomic()` sets the new password AND flips `PasswordResetCode.is_used=True` to prevent replay. Success: `{"message": "The password was changed successfully."}`. All `default_token_generator` / `urlsafe_base64_*` / uid+token code is GONE from `core/serializers.py` and `core/tests/fixtures.py`.
13. **`profile_pic` on `CoreUser` is base64 data URL in a `TextField`** (no `MEDIA_ROOT`, no Pillow, no file uploads — this repo has zero media infra). Format: `data:image/(png|jpeg|webp);base64,<payload>` — case-insensitive on the mime. Empty string / `null` clears the field. Decoded byte length must be ≤ 5 MB. Validator `validate_profile_pic_data_url` in `core/serializers.py` is the single source of truth. **Visible** in all read endpoints (list, retrieve, `/coreuser/me/`) AND in create/update responses. **Writable ONLY** via `PATCH /coreuser/<pk>/update_profile/` (uses `CoreUserProfileSerializer`). On `POST /coreuser/` and `PATCH /coreuser/<pk>/` the field is in `CoreUserSerializer.Meta.read_only_fields` (inherited by `CoreUserWritableSerializer`) — inbound `profile_pic` is silently ignored by DRF. Field is always optional; `update_profile` is the only path that validates. Sample payload: `{"profile_pic": "data:image/png;base64,iVBORw0KGgo..."}` with `Content-Type: application/json`. Implemented 2026-06-24; tests in `core/tests/test_coreuserview.py:TestUpdateProfilePic` — **not yet executed** (no python env at implementation time; verify via `docker compose up` + Postman).

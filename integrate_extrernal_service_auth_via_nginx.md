# Integration & Auth Implementation Guide

> Companion to **`nginx-deployment-guide.md`**. That file explains nginx concepts and configs; this one holds the
> **implementation side**: backend code, auth-service endpoints, design choices, and step-by-step patterns for
> integrating external services (APIs and iframes).
>
> Section numbers in parentheses such as (9.6.1), (9.9), (15.3), (16) refer to `nginx-deployment-guide.md`.

## Contents

1. Central identity, local permissions (roles)
2. Backend side of the trust boundary
3. Auth-service endpoints: verify, login, refresh, logout
4. Where authentication belongs — design discussion
5. Integrating with external services — options
6. External services in practice — token injection, path mapping, iframes
7. Cookies and the browser
8. Tokens, secrets and backends — architecture options

---

## 1. Central identity, local permissions (roles)

| Kind | Example | Lives in |
|---|---|---|
| **Identity-level roles** — company-wide facts | LDAP groups: "in QA team", "is admin" | auth service → passed as `X-Roles` |
| **App-specific permissions** | "may delete *this* test session", "owns *this* board" | **each app's own DB**, keyed by the username/ID from `X-User` |

So service 8001 does **not** need the auth DB. It keeps a small permissions table that references users by name. **Central identity, local permissions** — that split is the whole design.

```python
# FastAPI backend behind the gateway
from fastapi import Depends, FastAPI, Header, HTTPException

app = FastAPI()

def current_user(x_user: str = Header(...), x_roles: str = Header("")):
    return {"name": x_user, "roles": set(filter(None, x_roles.split(",")))}

@app.delete("/sessions/{sid}")
def delete_session(sid: int, user=Depends(current_user)):
    session = db_get_session(sid)                                   # app's own DB
    if session.owner != user["name"] and "admin" not in user["roles"]:
        raise HTTPException(403)                                    # authorization = app logic
    db_delete_session(sid)
    return {"deleted": sid}
```


---

## 2. Backend side of the trust boundary

nginx-side rules (backends unreachable except via the gateway, blanking client-supplied identity headers) are in (15.6). On top of that, a backend can refuse anything that didn't come through the gateway, by checking a secret header that only nginx adds (`proxy_set_header X-Gateway-Token "<long random>";`).

```python
import os
from fastapi import Header, HTTPException

GATEWAY_TOKEN = os.environ["GATEWAY_TOKEN"]

def from_gateway(x_gateway_token: str = Header(None)):
    if x_gateway_token != GATEWAY_TOKEN:
        raise HTTPException(401, "Requests must come through the gateway")
```


---

## 3. Auth-service endpoints: verify, login, refresh, logout

Login, refresh and logout are **ordinary, non-internal endpoints** that the browser calls directly through nginx. They are *not* behind `auth_request` (you can't require login to log in). The internal verify endpoint only verifies.

```nginx
# Public — the browser calls these directly; their Set-Cookie reaches the browser normally
location /auth/ {
    proxy_pass http://127.0.0.1:9000;
    proxy_set_header Host $host;
}

# Internal — only answers yes/no
location = /__auth {
    internal;
    proxy_pass http://127.0.0.1:9000/auth/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
}

# Protected
location /api/ {
    auth_request /__auth;
    auth_request_set $user $upstream_http_x_user;
    proxy_set_header X-User $user;
    proxy_pass http://127.0.0.1:8001;
}
```

```
1. POST /auth/login {user, password}  → auth service checks LDAP → 200 + Set-Cookie: session=abc
   (normal proxied request → the browser stores the cookie)
2. GET /api/devices   Cookie: session=abc
   → auth_request → /__auth → verify(session=abc) → 204 X-User: ahazra → proxied to 8001
3. Session nearly expired → frontend calls POST /auth/refresh → new Set-Cookie (normal request again)
4. POST /auth/logout → auth service deletes the session → Set-Cookie with expiry in the past
```

Notes: the verify endpoint returns only 2xx / 401 / 403 (anything else becomes a 500 for the user, see 14.5); session cookies should be `HttpOnly` (section 7).

**Example verify endpoint (FastAPI)** — the backend side of `location = /__whoami` (14.6–14.8):

```python
from fastapi import FastAPI, Request, Response, HTTPException

app = FastAPI()

def verify_session(token: str | None):
    # look up the session / decode the JWT; return a user object or None
    ...

@app.get("/api/auth/whoami")
def whoami(request: Request):
    user = verify_session(request.cookies.get("session"))
    if user is None:
        raise HTTPException(status_code=401)          # nginx → deny
    # 2xx → nginx allows; the header is captured by auth_request_set
    return Response(status_code=204, headers={"X-User": user.username})

@app.get("/api/devices/")
def devices(request: Request):
    user = request.headers.get("X-User")              # identity injected by nginx
    return {"user": user, "devices": [...]}
```

---

## 4. Where authentication belongs — design discussion

| Situation | Where authentication belongs |
|---|---|
| One UI + one backend that are one product | **In the app.** Gateway does only TLS + routing. |
| A product shipped to many customers / infrastructures | **In the app**, with an optional "trust proxy header" mode |
| One company, many internal tools for the same employees (the architecture-diagram case) | **Gateway / central identity provider** for "is this a logged-in employee?"; each app keeps its own permissions |
| External systems calling your API | **Standard tokens or API keys** validated by your app — never gateway headers |

**One product (UI + backend):** keep auth in the app. The recommended pattern for a same-origin web app is **BFF (Backend-for-Frontend)**: the browser holds only an `HttpOnly` session cookie; the server keeps the session (and any LDAP/OIDC tokens) on its side. Access + refresh tokens in the browser add little here; they earn their place with mobile apps, third-party API clients, cross-domain setups and stateless microservices. The UI being a separately **built** SPA (like server 85's React `dist/`) is fine — what matters is same origin + same session, so UI and backend behave as one application.

**Product for many customers:** don't make it depend on one company's gateway. Mature products ship full built-in auth **plus** an optional proxy-auth mode. Grafana is the textbook example:

```ini
# grafana.ini — only enabled when a customer has an SSO gateway in front
[auth.proxy]
enabled = true
header_name = X-WEBAUTH-USER
header_property = username
auto_sign_up = true
whitelist = 127.0.0.1        ; only trust the header from the gateway's address
```

**Defense in depth is common:** the gateway does the coarse check (TLS, rate limiting, "must be an authenticated employee") *and* each app still validates and authorizes. Not wasteful — cautious.


---

## 5. Integrating with external services — options

**Rule:** gateway-injected headers (`X-User`, `X-Roles`) are an **internal contract inside one trust boundary** (one company, one deployment, one gateway). They must never become your external API contract — an external team should not have to "accept certain headers" to work with you.

An external service usually expects **its own** credentials (API key, OAuth token, username/password, its own session). `auth_request` cannot log your users into someone else's system. Three options:

**(a) nginx injects a static service credential** — possible, limited:

```nginx
location /ext/jira/ {
    auth_request /__auth;                                   # our user must be logged in with US
    proxy_pass https://jira.example.com/;                   # trailing / → strips /ext/jira/ (9.6)
    proxy_set_header Host jira.example.com;                 # the EXTERNAL name — NOT $host (9.9)
    proxy_ssl_server_name on;                               # send SNI to the external HTTPS server
    proxy_set_header Authorization "Bearer <service-token>";
    proxy_set_header Cookie "";                             # never leak our users' cookies to a third party
    proxy_set_header X-User "";
}
```

Pitfalls: the external service sees **every** request as one service account (no per-user identity); the secret sits in `/etc/nginx` (restrict file permissions); no error handling, retries, or response transformation; every external API change becomes an nginx change.

**(b) Your backend's integration layer — usually the right choice:**

```
Browser → nginx → my backend /api/integrations/... → (server-side call with token) → external service
```

```python
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/integrations")
JIRA_URL = os.environ["JIRA_URL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]          # secret stays in the backend, never in the browser

@router.get("/jira/issues/{key}")
async def jira_issue(key: str, user=Depends(current_user)):   # my app's own auth
    if not can_use_jira(user):                                # my app's own permissions
        raise HTTPException(403)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{JIRA_URL}/rest/api/2/issue/{key}",
                             headers={"Authorization": f"Bearer {JIRA_TOKEN}"})
    if r.status_code == 404:
        raise HTTPException(404, "Issue not found")
    r.raise_for_status()
    data = r.json()
    return {"key": data["key"], "summary": data["fields"]["summary"]}   # reshape for my UI
```

Why it's better: per-user permission checks, secrets in one place, error handling and retries, response shaping, logging/audit — and the external service only needs its normal, standard auth. Nothing about it depends on nginx.

**(c) Per-user delegation** — when the external system must know *which* user acts: OAuth2 (the user grants your app access; you store their token server-side) or token exchange via a shared identity provider.

**Other teams calling *your* API:** issue them an API key or OAuth2 client-credentials token, sent as a standard `Authorization: Bearer ...` header, validated by your app.


---

## 6. External services in practice — token injection, path mapping, iframes

Scenario: our app (UI + backend) plus other teams' services on **other servers** (e.g. `10.1.1.1:8000` QA dashboard, `10.1.1.2:9000` AI API), each expecting **its own API key**. We want to show their UI in an iframe and call their APIs.

### The one concept that untangles it: who sends the request?

> nginx can only touch requests whose URL points at **our** nginx. The browser sends requests wherever the URL says.

| What the UI uses | Browser sends it to | Can our nginx inject an API key? |
|---|---|---|
| `<iframe src="https://qadash.other.com/">` | their server, directly | **No** — our nginx never sees it |
| `<iframe src="/integrations/qadash/">` | our nginx | **Yes** |
| `fetch("https://ai.other.com/v1/chat")` | their server, directly | **No** — and the key would have to live in the browser (bad) |
| `fetch("/integrations/ai/v1/chat")` | our nginx | **Yes** |

Requests that go directly to their site can't be touched by us — their site must handle login itself. To inject keys, the URL must point at our nginx.

### Token injection: get the key, then forward — in ONE browser request

Idea: user is logged in with us → hits `/integrations/qadash/` → our backend checks our session/JWT and roles and hands back their token → `proxy_pass` forwards to `10.1.1.1:8000` with that token.

This is a real pattern. It happens in **one** browser request, thanks to the phases (15.3):

- **Access phase:** nginx calls our backend's verify endpoint internally; the backend checks the user and returns the key in a response header.
- **Content phase:** `proxy_pass` forwards to their server with the key injected.

The browser does **not** make two calls (one to an auth URL, then one to the service). The `auth_request` subrequest *is* the first call, made by nginx.

```nginx
location /integrations/qadash/ {
    auth_request /__auth_qadash;
    auth_request_set $user      $upstream_http_x_user;
    auth_request_set $ext_token $upstream_http_x_ext_token;   # key/token returned by OUR backend

    proxy_pass http://10.1.1.1:8000/;                  # path "/" strips /integrations/qadash/ (9.6.1)
    proxy_set_header Host          10.1.1.1;           # THEIR name, not $host (9.9)
    proxy_set_header Authorization "Bearer $ext_token";
    proxy_set_header X-User        $user;              # only if they agreed to read it
    proxy_set_header Cookie        "";                 # don't leak our session cookie to another system
}

location = /__auth_qadash {
    internal;
    proxy_pass http://127.0.0.1:8000/api/auth/verify;  # OUR FastAPI backend → receives /api/auth/verify (9.6.1)
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Target qadash;                  # tells our backend which service is wanted
}
```

Our backend's verify endpoint:

```python
import os
from fastapi import FastAPI, Request, Response

app = FastAPI()
EXT_KEYS = {"qadash": os.environ["QADASH_API_KEY"], "ai": os.environ["AI_API_KEY"]}
NEEDED_ROLE = {"qadash": "qa", "ai": "ai-user"}

@app.get("/api/auth/verify")
def verify(request: Request):
    user = verify_session(request.cookies.get("session"))     # our JWT/session check
    if user is None:
        return Response(status_code=401)

    headers = {"X-User": user.name, "X-Roles": ",".join(user.roles)}
    target = request.headers.get("X-Target")
    if target:
        if NEEDED_ROLE[target] not in user.roles:
            return Response(status_code=403)                  # logged in, but not allowed
        headers["X-Ext-Token"] = EXT_KEYS[target]             # or fetch/cache a per-user token from their server
    return Response(status_code=204, headers=headers)
```

The key never reaches the browser; it exists only between our backend, nginx, and their server.

**Simpler variant** for one fixed key per service: `/__auth` checks only the user, and nginx hard-codes the key with `proxy_set_header X-API-Key "...";`. Works too — the secret then lives in `/etc/nginx` (restrict file permissions) instead of the backend's environment.

### "Does their server have that route?"

nginx doesn't register routes; it only translates the prefix (9.6.1) and forwards. Their server decides whether the path exists:

| Browser requests | With `location /integrations/ai/` + `proxy_pass http://10.1.1.2:9000/;` | Their server receives |
|---|---|---|
| `/integrations/ai/v1/chat` | prefix replaced by `/` | `/v1/chat` |
| `/integrations/ai/models` | | `/models` |

So our UI calls `/integrations/ai/<their path>`; their API must have `<their path>`.

### API integrations — two valid options

| | **A. nginx pass-through with key injection** (above) | **B. Backend integration layer** (section 5) |
|---|---|---|
| Flow | browser → nginx (auth + key) → their API | browser → nginx → our FastAPI → (httpx with key) → their API |
| Response | their API's response, unchanged | whatever our backend shapes it into |
| Good when | the UI can use their API as-is | per-user logic, combining calls, reshaping, retries, audit |
| Widely used? | yes — API-gateway pattern | yes — BFF / integration pattern |

Many teams use A for simple pass-through and B wherever logic is needed.

### Embedding their UI in an iframe — three approaches

**Approach 1 — direct iframe + embed token (most common for dashboards).** Our backend creates or fetches a short-lived token; the iframe points directly at their server with it. Metabase, Grafana, Looker and Power BI embedding work this way.

```python
import os
import time
import jwt  # PyJWT
from fastapi import APIRouter, Depends

router = APIRouter()

@router.get("/api/integrations/qadash/embed-url")
def embed_url(user=Depends(current_user)):
    token = jwt.encode(
        {"sub": user.name, "roles": list(user.roles), "exp": int(time.time()) + 300},
        os.environ["QADASH_EMBED_SECRET"],        # secret agreed with THEIR team
        algorithm="HS256",
    )
    return {"url": f"https://qadash.other.com/embed?token={token}"}
```

```javascript
const { url } = await fetch('/api/integrations/qadash/embed-url').then(r => r.json());
setIframeSrc(url);   // <iframe src={iframeSrc} />
```

Their server validates the token and starts its own session (alternatively, our backend asks their API for an embed token). Requirements: their app supports token/embed login; they allow framing by our domain (`Content-Security-Policy: frame-ancestors https://ourapp...`). Pitfall: browsers increasingly block cookies inside **cross-site** iframes → login loops. Subdomains of the same parent domain (e.g. `*.example.com`) count as same-site and avoid it.

**Approach 2 — shared SSO.** Both apps log in through the same company identity provider (Keycloak, Azure AD, ...). The iframe loads their site → they redirect to the identity provider → the user is already logged in there → back silently. Cleanest when their app supports SSO; same framing/cookie caveats as approach 1.

**Approach 3 — proxy their UI through our nginx** (token injection applied to the whole UI):

```nginx
server {
    listen 443 ssl;
    server_name qadash.ourapp.example.com;    # a SUBDOMAIN, not a sub-path (see 9.6.1, iframe table)
    include snippets/auth.conf;

    location / {
        auth_request /__auth;
        auth_request_set $user $upstream_http_x_user;
        proxy_pass http://10.1.1.1:8000;      # no path: paths identical on both sides
        proxy_set_header Host       10.1.1.1;
        proxy_set_header X-API-Key  "qadash-key";
        proxy_set_header X-User     $user;
    }
}
```

`<iframe src="https://qadash.ourapp.example.com/">` now goes through our nginx; **every** request inside the iframe (HTML, JS, CSS, XHR) passes auth and gets the key. Our session cookie must have `Domain=.ourapp.example.com` so it reaches this subdomain (section 7). Pitfalls:
- **Sub-paths break UIs** (absolute asset paths — table in 9.6.1). Use a subdomain, or the app's base-path setting (e.g. Grafana's `serve_from_sub_path`).
- **Their app must accept our injected auth** (API key or trusted `X-User`) — needs their cooperation, and they should accept those headers only from our gateway's IP.
- **Framing headers** — `X-Frame-Options: DENY` from their app stops the iframe from rendering.

### What fits which need

| Need | Recommended |
|---|---|
| Show their dashboard in our UI | Approach 1 (embed token), or approach 2 (SSO) if supported |
| Their UI only accepts an API key and can't change | Approach 3 (subdomain proxy + key injection) |
| Their APIs, used as-is | Option A (nginx injection) — one browser call |
| Their APIs, with our logic | Option B (backend integration layer) |

Common principle in every row: **secrets stay server-side; the browser only ever holds our own session cookie.**

---

## 7. Cookies and the browser

**Doubt:** "If the auth service sets a cookie, won't the browser distrust it because it came from a different server/port?"

No. **The browser only ever talks to nginx.** It has no idea a service on port 9000 exists. From the browser's point of view, the `Set-Cookie` came from the host in the URL bar (e.g. `10.63.68.173`), so it stores it for that host and sends it back on every later request to that host. The hops behind nginx are invisible.

Cookie rules worth knowing:
- Cookies are scoped by **domain + path, NOT by port** (unlike origins, which include the port).
- No `Domain` attribute → "host-only": sent only to the exact host that set it.
- `Domain=.example.com` → sent to **every** `*.example.com` — the way to share one login across `tool1-dev`, `tool2-dev`, ...
- `HttpOnly` → JavaScript can't read it (protects against XSS stealing the session). Use it for session cookies.
- `Secure` → only sent over HTTPS. **Pitfall on server 85:** it's plain `http://`, so browsers refuse to store `Secure` cookies there.
- `SameSite=Lax` (browser default) → not sent on most cross-site requests.
- **Cross-origin fetch with cookies** (server 14 style, frontend and API on different domains) needs `fetch(url, {credentials: 'include'})` **and** the API to answer `Access-Control-Allow-Credentials: true` with a **specific** origin — `Access-Control-Allow-Origin: *` is **not allowed** together with credentials. Server 14's `*` configs therefore only work for token-in-header auth, not cookies.

Also: the browser's `Cookie` header is forwarded by nginx to **both** the auth subrequest and the real backend (default behaviour). The backend sees the cookie too — it just doesn't need to understand it.

---

## 8. Tokens, secrets and backends — architecture options

**Doubt:** "The backend doesn't know how to decrypt the access token, so every service needs the JWT secret, a shared user DB, refresh tokens... isn't that getting out of hand?"

In the gateway pattern: **no.** That's the point of it. Backends never touch tokens:

```
Auth service (9000):  LDAP, user DB, JWT secret, refresh tokens, sessions   ← ALL of it, in ONE place
Backends (8001/8002): see only "X-User: ahazra", "X-Roles: qa,admin"        ← trust it, nothing else
```

The three models, compared:

| Model | Backend does | Needs secret? | Needs user DB? | Network call per request |
|---|---|---|---|---|
| **Gateway trust** (`auth_request` + identity headers) | reads `X-User` | no | no | 1 subrequest nginx → auth service |
| **Asymmetric JWT** (OIDC: Keycloak, Azure AD, Okta) | verifies signature itself with the **public** key (JWKS URL) | no — public key only | no | none (keys cached) |
| **Opaque token + introspection** | asks the auth server "is token X valid?" | no | no | 1 call per request — exactly what `auth_request` does once on behalf of all backends |

A **shared symmetric JWT secret** across services is the version that gets out of hand — and the industry answer is asymmetric signing (private key signs, public key verifies), not sharing secrets or databases. **Refresh tokens only ever live with the auth service / identity provider**; services never see them.

Caching auth verdicts in nginx: (15.5).

6. Deployment theory — the three architectures you described
Option A — single nginx server block, path-based routing (what you have; the right one):

server {
    listen 443 ssl;
    location /            { root /var/www/ui; try_files $uri /index.html; }  # SPA
    location /api/v1/codegen/   { proxy_pass http://10.71.10.21:9090; proxy_read_timeout 300s; }
    location /api/v1/log-agent/ { proxy_pass http://10.71.10.21:9090; }
    location /api/              { proxy_pass http://localhost:8000; }         # your FastAPI
    location /sessions/         { proxy_pass http://localhost:9000; }
}

The browser only ever talks to one origin. nginx fans out to N backends by path — exactly what Vite's dev proxy does, so dev and prod behave identically.

Why this wins (your debate ammo):

No CORS at all. Same origin = the browser never sends preflights, no backend needs Access-Control-Allow-Origin. This is a security advantage, not a workaround: no backend is tempted to ship Allow-Origin: *, there's no CORS misconfiguration surface, and the backends don't need to be reachable from user machines at all.
Backends stay private. 10.71.10.21:9090 can sit on an internal network; only nginx needs a route to it. Direct-call architecture forces every backend onto a user-reachable network.
One TLS cert, one auth/logging/rate-limit chokepoint, per-route timeouts (codegen needs the long proxy_read_timeout; this is where your earlier HTML-502 error came from).
Runtime flexibility: moving a backend = edit nginx conf + reload. Zero frontend rebuild.
Option B — multiple server blocks (vhosts), browser calls each host directly: every backend needs CORS config, its own cert/DNS, public reachability; URLs baked into the bundle; preflight latency on every request. More surface, more config drift. Only justified when a service must be a separate public product.

Option C — hybrid (proxy for some, direct for others): worst of both — two behavior classes to debug. Avoid.

One honest caveat for arguments: a reverse proxy doesn't add authentication by itself — same-origin means cookies flow to all proxied paths, so backend auth is still mandatory. The win is eliminating CORS complexity and hiding backend topology, not replacing auth.

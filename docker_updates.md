# Docker Networking — `0.0.0.0`, Port Publishing, nginx in Front

> Companion to `nginx-deployment-guide.md` (Section 13 there is the one-line summary). Section numbers in parentheses refer to that file.

## 1. The chain when the backend runs in Docker

```
Internet / internal network
        │
        ▼
   ┌─────────────────────────────────┐
   │  Host machine (Ubuntu)          │
   │                                 │
   │  nginx (port 80)                │  ← systemd-managed, pre-installed
   │    │  proxy_pass to             │
   │    │  127.0.0.1:<host port>     │
   │    ▼                            │
   │  Docker published port          │  ← e.g. -p 9090:8080 in docker run
   │    │  forwards to               │
   │    ▼                            │
   │  ┌─────────────────────────┐    │
   │  │ Container (172.17.0.3)  │    │
   │  │ FastAPI on 0.0.0.0:8080 │    │
   │  └─────────────────────────┘    │
   └─────────────────────────────────┘
```

1. Request arrives at host port 80 → nginx.
2. nginx matches `location /api/` → `proxy_pass http://127.0.0.1:9090` (the **published host port**).
3. Docker forwards host `9090` → container IP `172.17.0.3` port `8080`.
4. uvicorn inside the container, bound to `0.0.0.0:8080`, accepts it.
5. Response travels back: container → Docker → nginx → browser.

`-p HOST:CONTAINER` → `-p 9090:8080` means "host port 9090 → container port 8080". **nginx's `proxy_pass` uses the HOST port**, never the container port.

## 2. Why the container app MUST bind `0.0.0.0`

In bridge mode a container has its **own network namespace** with (at least) two interfaces:

- `lo` — `127.0.0.1`, reachable only from inside the container
- `eth0` — e.g. `172.17.0.3`, how Docker's port forwarding reaches it

Docker forwards traffic to the **container's IP (`eth0`)**, not its loopback.

- App binds `127.0.0.1:8080` → listens only on the container's loopback → forwarded traffic arrives on `eth0` → nobody listening → **connection refused**. App looks "up" but is unreachable.
- App binds `0.0.0.0:8080` → listens on `lo` **and** `eth0` → forwarded traffic accepted ✅

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`localhost` only makes sense for something that must **never** be reached from outside its own machine/namespace (e.g. a helper daemon).

## 3. Security: `0.0.0.0` inside the container is normal and safe

What's actually reachable depends on:
- (a) the Docker **port mapping** (only published ports are exposed),
- (b) the **host firewall**,
- (c) **nginx** in front.

⚠️ `-p 9090:8080` publishes on the host's `0.0.0.0:9090` — reachable from the network **directly, bypassing nginx** (and Docker's iptables rules can bypass `ufw`). To force all traffic through nginx, bind the published port to the host loopback:

```bash
docker run -p 127.0.0.1:9090:8080 my-fastapi-image
```

```yaml
# docker-compose.yml
ports:
  - "127.0.0.1:9090:8080"
```

Now only nginx (on the same host) can reach it.

## 4. Without Docker (uvicorn directly on the host)

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Here `127.0.0.1` is actually the *better* choice: nginx is on the same machine, so it can reach loopback, and nobody else can bypass nginx. (In a container the rule flips, because "same machine" for the container means "inside the container".)

## 5. Who manages what

| Thing | Managed by | My responsibility? |
|---|---|---|
| nginx install + unit file | platform/provisioning, systemd | no |
| nginx site config (`sites-enabled/boardfarm`) | me (with sudo) | yes |
| Docker container / uvicorn | me | yes |
| Port alignment (`proxy_pass` ↔ published port) | me | yes |
| `--host 0.0.0.0` in container | me | yes |

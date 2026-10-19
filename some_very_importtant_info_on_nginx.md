# Nginx, Linux & Deployment — The Complete Picture

> **What this is:** everything from our discussion, organised from the ground up.
> Every example uses the *real* output from my two servers:
>
> | Server | IP | Nginx package | What runs there |
> |---|---|---|---|
> | `nl-itc-l-ubun00014` (**server 14**) | `10.63.69.36` | **nginx.org** package | Several Django apps (cpetools, mv3tools, snmpapi, cnrlogs) via uwsgi, each on its own domain |
> | `nl-itc-l-ubun00085` (**server 85**) | `10.63.68.173` | **Ubuntu/Debian** package | My boardfarm app: React frontend + FastAPI backend, path-based routing |
>
> If I ever feel "I don't know anything about this" — read this top to bottom and I'm back.

---

## Table of Contents

1. [The Big Picture in One Diagram](#1-the-big-picture-in-one-diagram)
2. [Linux Foundations You Need First](#2-linux-foundations-you-need-first)
3. [How Nginx Got onto the Machine — Packages](#3-how-nginx-got-onto-the-machine--packages)
4. [systemd — Who Starts Nginx and How](#4-systemd--who-starts-nginx-and-how)
5. [Master and Worker Processes](#5-master-and-worker-processes)
6. [The Main Config File — `nginx.conf`](#6-the-main-config-file--nginxconf)
7. [`include` — It's Copy-Paste](#7-include--its-copy-paste)
8. [Virtual Hosting — Many Sites, One Nginx, One IP](#8-virtual-hosting--many-sites-one-nginx-one-ip)
9. [Inside a `server {}` Block — `location`, `root`, `proxy_pass`](#9-inside-a-server--block--location-root-proxy_pass)
10. [Server 14 Walkthrough — Every Config File Explained](#10-server-14-walkthrough--every-config-file-explained)
11. [Server 85 Walkthrough — My Boardfarm Config](#11-server-85-walkthrough--my-boardfarm-config)
12. [The Browser Flow — Frontend Download, Then API Calls](#12-the-browser-flow--frontend-download-then-api-calls)
13. [Docker, `0.0.0.0` vs `localhost`, Port Publishing](#13-docker-0000-vs-localhost-port-publishing)
14. [Advanced — `internal`, `auth_request`, `location = /__whoami`](#14-advanced--internal-auth_request-location--__whoami)
15. [Command Cheat Sheet](#15-command-cheat-sheet)
16. [Troubleshooting — Error → Cause](#16-troubleshooting--error--cause)
17. [FAQ — Every Question I Asked, Answered](#17-faq--every-question-i-asked-answered)

---

## 1. The Big Picture in One Diagram

Before any detail, here is the whole story. Everything else in this document zooms into one box of this picture.

```
 ┌──────────────┐
 │   Browser    │   user types http://10.63.68.173/  or  https://mv3tools-dev.upclabs.com/
 └──────┬───────┘
        │ (1) DNS: "what IP is mv3tools-dev.upclabs.com?"  → 10.63.69.36
        │ (2) TCP connect to IP:port (80 for http, 443 for https)
        │ (3) HTTP request with a "Host:" header + a path (/api/devices/)
        ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │  HOST MACHINE (Ubuntu)                                                │
 │                                                                       │
 │  systemd (PID 1) ──starts at boot──► nginx MASTER (root)             │
 │                                        │ forks                        │
 │                                        ▼                              │
 │                              nginx WORKERS (www-data / nginx user)    │
 │                                        │                              │
 │       (4) worker picks a server{} block by matching Host → server_name│
 │       (5) inside that block, picks a location{} by matching the path  │
 │                                        │                              │
 │          ┌─────────────────────────────┼─────────────────────────┐    │
 │          ▼                             ▼                         ▼    │
 │   serve static file          proxy_pass http://127.0.0.1:8000   uwsgi_pass unix:/run/uwsgi/x.sock
 │   from disk (React dist/)    (FastAPI — on host or in Docker)   (Django via uwsgi)
 │                                                                       │
 └───────────────────────────────────────────────────────────────────────┘
        │
        ▼ (6) response travels back the same way to the browser
```

**The one-sentence version:** systemd starts nginx at boot → nginx master forks workers → a worker receives each request → nginx picks the *site* by the `Host` header and the *handler* by the URL path → it either serves a file from disk or forwards the request to a backend app → the response goes back.

---

## 2. Linux Foundations You Need First

A lot of the confusion came from Linux concepts, not nginx. These are the building blocks.

### 2.1 Processes, PIDs, and parents

Every running program is a **process**. Every process has:

- a **PID** (process ID) — unique number
- a **PPID** (parent process ID) — the process that created it
- an **owner** (UID / username) — whose permissions it runs with

Processes form a tree. The root of the tree is **PID 1**, which on Ubuntu is **systemd**.

### 2.2 `fork()` — how processes create processes

`fork()` is the Linux system call that makes a copy of the current process. The copy (child) gets a new PID, and its PPID points to the creator. This is exactly how the nginx master creates its workers.

### 2.3 Daemons

A **daemon** is a background process with no terminal attached (that's why `ps` shows `?` in the TTY column). Services like nginx, sshd, docker are daemons. The classic way to become a daemon: start → fork → parent exits → child keeps running in the background.

### 2.4 Reading `ps -ef` output (column by column)

```
UID        PID   PPID  C STIME TTY    TIME     CMD
root       1436  1     0 Oct03 ?      00:00:00 nginx: master process /usr/sbin/nginx -c /etc/nginx/nginx.conf
nginx      1437  1436  0 Oct03 ?      00:00:08 nginx: worker process
```

| Column | Meaning | In this example |
|---|---|---|
| `UID` | **username** owning the process | `root` (master), `nginx` (worker) |
| `PID` | this process's ID | 1436 / 1437 |
| `PPID` | parent's ID | master's parent is `1` (systemd); worker's parent is `1436` (master) |
| `C` | CPU usage | 0 |
| `STIME` | start time | `Oct03` → running since boot on Oct 3 |
| `TTY` | terminal | `?` = no terminal = daemon |
| `TIME` | total CPU time used | 8 seconds |
| `CMD` | the command line | what was executed |

### 2.5 The `grep nginx` gotcha (why I saw uwsgi/celery lines)

```bash
ps -ef | grep nginx
```

`grep` matches the text **anywhere in the line** — including the **UID column**. On server 14, many Django processes run as the Linux user named `nginx`:

```
nginx       1619       1  0 Oct03 ?  00:00:29 uwsgi --ini /etc/cnrlogs_api_autodeploy/uwsgi.ini ...
nginx       1622       1  0 Oct03 ?  00:07:20 python /opt/cpetools_api_autodeploy/active_deployment/src/manage.py tftpserver
nginx       1793       1  0 Oct03 ?  00:11:19 /opt/snmpapi/.venv/bin/python3 -m celery -A django_root worker ...
```

These are **not nginx**. They are separate apps (cnrlogs_api, cpetools_api, mv3tools, snmpapi — uwsgi web servers, celery workers, celery beat schedulers, a tftp server) that the admin chose to run under the `nginx` service account. They match only because of the username.

Also notice your own `grep` shows up:

```
ahazra   2532349 2531829  0 18:38 pts/0    00:00:00 grep --color=auto nginx
```

**Ways to see only real nginx processes:**

```bash
pgrep -a nginx                 # matches process NAME, not user
ps -C nginx -f                 # processes whose command name is nginx
ps -ef | grep "[n]ginx:"       # the [n] trick stops grep from matching itself
systemctl status nginx         # shows the service's own process tree (CGroup)
```

### 2.6 Users and service accounts

Linux has normal users (`ahazra`) and **service accounts** — users that exist only so a daemon can run with limited permissions. Nginx workers run as one:

- Debian/Ubuntu package → user **`www-data`**
- nginx.org package → user **`nginx`**

Different packagers created different accounts for the same purpose (more in Section 3).

### 2.7 Privileged ports (< 1024)

Only **root** can bind (listen on) ports below 1024 — like **80** (HTTP) and **443** (HTTPS). That's why the nginx master starts as root. Ports ≥ 1024 (like 8000, 8080, 9090) can be used by any user, which is why app servers use them.

### 2.8 Signals

Signals are tiny messages the kernel delivers to a process. Nginx reacts to them:

| Signal | Nginx's reaction |
|---|---|
| `HUP` | **reload** config (zero downtime) |
| `QUIT` | **graceful** stop — finish current requests, then exit |
| `TERM` / `INT` | **fast** stop |
| `KILL` | cannot be caught — kernel kills immediately |

You'll see these in both unit files (Section 4).

### 2.9 PID files

A daemon writes its PID into a file (e.g. `/run/nginx.pid`) so other tools know which process to signal. `cat /run/nginx.pid` → `1436` on server 14. (`/var/run` is a symlink to `/run`, so server 14's `pid /var/run/nginx.pid;` is the same location.)

### 2.10 Network interfaces, loopback, and `0.0.0.0`

A machine has several network **interfaces**, each with an address:

| Address | Means | Who can reach an app bound to it |
|---|---|---|
| `127.0.0.1` / `localhost` | the **loopback** interface only | only processes on the **same machine** (or same network namespace / container) |
| `10.63.68.173` (example) | the machine's real network card | anyone on the network who can route to it |
| `0.0.0.0` | **all interfaces** (loopback + real IPs + any others) | anyone who can reach *any* of the machine's IPs |

`0.0.0.0` is **not an address you connect to** — it's a wildcard meaning "bind to everything." After binding to `0.0.0.0:8080`, the app answers on `127.0.0.1:8080` **and** on `10.x.x.x:8080`.

```bash
ip addr        # list interfaces and their IPs
ss -tlnp       # list listening TCP sockets: which address:port, which process
```

Example `ss -tlnp` lines and what they mean:

```
LISTEN 0 511   0.0.0.0:80        ...  nginx       ← reachable from network
LISTEN 0 2048  127.0.0.1:8000    ...  uvicorn     ← only reachable from this machine (nginx can reach it, outsiders can't)
```

### 2.11 Sockets: TCP vs Unix domain sockets

Two ways processes talk:

- **TCP socket** — `127.0.0.1:8000`. Goes through the network stack (even if local).
- **Unix domain socket** — a special **file**, e.g. `/run/uwsgi/mv3tools_autodeploy.sock`. Only works on the same machine, slightly faster, and access is controlled by **file permissions** (that's one reason the Django apps on server 14 run as the `nginx` user — nginx can read/write their socket file).

### 2.12 Symlinks

A symbolic link is a pointer to another file. Debian's `sites-enabled/` directory normally contains symlinks pointing into `sites-available/`:

```bash
ls -l /etc/nginx/sites-enabled/
# boardfarm -> /etc/nginx/sites-available/boardfarm
```

Delete the symlink → site disabled, original config still kept. (It can also be a plain file — nginx doesn't care.)

### 2.13 File permissions matter for nginx

Workers run as `www-data`/`nginx`, **not as you**. To serve a file, that user needs:
- **read** permission on the file, and
- **execute (`x`)** permission on **every parent directory** in the path.

Server 85 serves from `/home_ldap/ahazra/workspace/boardfarm_frontend/dist` — so `www-data` must be able to traverse `/home_ldap`, `/home_ldap/ahazra`, `workspace`, ... If not → **403 Forbidden**. Check with:

```bash
namei -l /home_ldap/ahazra/workspace/boardfarm_frontend/dist/index.html
sudo -u www-data cat /home_ldap/ahazra/workspace/boardfarm_frontend/dist/index.html
```

---

## 3. How Nginx Got onto the Machine — Packages

### 3.1 Nginx is just one executable file

Nginx is a compiled C program at **`/usr/sbin/nginx`**. When run, it reads a config file and starts listening on the ports the config says (usually 80 and 443). It can:
- **serve static files** directly from disk, or
- act as a **reverse proxy** — receive requests and forward them to another application (FastAPI, Django, ...).

The binary is the same program everywhere. The differences I saw between servers are about **packaging**, not the program.

### 3.2 What a package is

On Ubuntu/Debian, software is installed as **packages** (`.deb` files) using `apt`. A package contains:

- the binary → `/usr/sbin/nginx`
- default config → `/etc/nginx/nginx.conf` (+ `mime.types`, etc.)
- the systemd unit file → `/usr/lib/systemd/system/nginx.service`
- a service user account → `www-data` or `nginx`
- man pages, log-rotation config, install scripts

`apt install nginx` downloads the `.deb`, unpacks all of these, registers and enables the service.

### 3.3 There are TWO sources of nginx packages

| | **Source A: Ubuntu/Debian repo** | **Source B: nginx.org repo** |
|---|---|---|
| Who builds it | Debian/Ubuntu maintainers | The nginx team |
| How you get it | `apt install nginx` on a stock Ubuntu | first add nginx.org's repo, then `apt install nginx` |
| Unit file style | `-g 'daemon on; master_process on;'`, `ExecStartPre` test, `start-stop-daemon` | `-c ${CONFFILE}`, raw `kill -s HUP/TERM` |
| Worker user | `www-data` | `nginx` |
| Site config dirs | `conf.d/` **and** `sites-available/` + `sites-enabled/` | only `conf.d/` |
| Modules | separate packages via `modules-enabled/` | compiled in |
| Example server | **server 85** | **server 14** |

Both install the same program, load `/etc/nginx/nginx.conf`, and produce master + workers. The **surrounding files** differ because different people wrote them. Like two car makers both building a sedan but putting the ignition button in different places.

### 3.4 Who installed it? (Not me.)

On corporate/shared infrastructure, machines are provisioned from a **base image** or by **configuration management** (Ansible, Puppet, Chef, or a shell script). The platform team's recipe says "install nginx, drop this config, enable the service." Every machine built from that recipe already has nginx installed and running. One recipe used Ubuntu's repo, another used nginx.org's — decided at provisioning time, possibly years ago.

**My job:** deploy my app and make sure nginx's `proxy_pass` target matches the port my app listens on. **Not my job:** the nginx unit file — it's part of the base platform.

### 3.5 How to prove which package a server has

```bash
nginx -v                         # version; Ubuntu builds usually show "(Ubuntu)"
nginx -V 2>&1 | tr ' ' '\n'      # full build flags, incl. --conf-path=/etc/nginx/nginx.conf
apt-cache policy nginx           # shows which repo it came from (nginx.org/packages/... vs ubuntu archive)
dpkg -S /usr/lib/systemd/system/nginx.service   # which package owns the unit file
dpkg -l | grep nginx             # Debian splits into nginx, nginx-common, libnginx-mod-*
```

`--conf-path=/etc/nginx/nginx.conf` in `nginx -V` is the **compiled-in default** config path — the file nginx loads when no `-c` is given.

---

## 4. systemd — Who Starts Nginx and How

### 4.1 What systemd is

When Linux boots, the kernel starts exactly one user-space process: **systemd (PID 1)**, the **init system**. Its job is to start and manage every other service, using **unit files** — plain-text descriptions of services.

- Package-provided units live in **`/usr/lib/systemd/system/`**
- Admin overrides go in **`/etc/systemd/system/`** (these win)

```bash
systemctl cat nginx    # shows the unit file actually in effect, including overrides
```

### 4.2 Server 85's unit file (Debian/Ubuntu package) — annotated

```ini
# Stop dance for nginx
# ExecStop sends SIGQUIT (graceful stop) to the nginx process.
# If, after 5s (--retry QUIT/5) nginx is still running, systemd takes control
# and sends SIGTERM (fast shutdown) to the main process.
# After another 5s (TimeoutStopSec=5), and if nginx is alive, systemd sends
# SIGKILL to all the remaining processes in the process group (KillMode=mixed).

[Unit]
Description=A high performance web server and a reverse proxy server
Documentation=man:nginx(8)
After=network-online.target remote-fs.target nss-lookup.target   # start only after network/DNS are up
Wants=network-online.target
ConditionFileIsExecutable=/usr/sbin/nginx                        # skip if the binary is missing

[Service]
Type=forking                       # nginx will daemonize (fork into background)
PIDFile=/run/nginx.pid             # systemd reads the master's PID from here
ExecStartPre=/usr/sbin/nginx -t -q -g 'daemon on; master_process on;'   # TEST config first; abort start if broken
ExecStart=/usr/sbin/nginx -g 'daemon on; master_process on;'            # the real start command
ExecReload=/usr/sbin/nginx -g 'daemon on; master_process on;' -s reload # reload = send HUP via nginx itself
ExecStop=-/sbin/start-stop-daemon --quiet --stop --retry QUIT/5 --pidfile /run/nginx.pid
TimeoutStopSec=5
KillMode=mixed                     # TERM to main process; leftover processes get KILL after timeout

[Install]
WantedBy=multi-user.target         # "enabled" = start during normal boot
```

Flags explained:

| Flag | Meaning |
|---|---|
| `-g '...'` | set **global directives on the command line** (here: run as daemon, use master process) |
| `-t` | **test** the config and exit (syntax check) |
| `-q` | quiet — only print errors during the test |
| `-s reload` | send a signal to the running master (`reload`, `quit`, `stop`, `reopen`) |
| *(no `-c`)* | use the compiled-in default config: `/etc/nginx/nginx.conf` |
| `-` before a command (`ExecStop=-...`) | systemd ignores a failure exit code from that command |

### 4.3 Server 14's unit file (nginx.org package) — annotated

```ini
[Unit]
Description=nginx - high performance web server
Documentation=https://nginx.org/en/docs/
After=network-online.target remote-fs.target nss-lookup.target
Wants=network-online.target

[Service]
Type=forking
PIDFile=/run/nginx.pid
Environment="CONFFILE=/etc/nginx/nginx.conf"     # variable used below
Environment="cmdopts="                           # empty extra options
EnvironmentFile=-/etc/default/nginx              # optional file that can override those vars ("-" = ignore if missing)
ExecStart=/usr/sbin/nginx -c ${CONFFILE} $cmdopts   # -c = explicit config path
ExecReload=/bin/sh -c "/bin/kill -s HUP $(/bin/cat /run/nginx.pid)"   # reload = HUP signal to master
ExecStop=/bin/sh -c "/bin/kill -s TERM $(/bin/cat /run/nginx.pid)"    # stop  = TERM signal to master

[Install]
WantedBy=multi-user.target
```

This is where `-c /etc/nginx/nginx.conf` in server 14's `ps` output comes from — the `ExecStart` line expands `${CONFFILE}`.

### 4.4 Side by side — what's actually different

| | Server 85 (Debian) | Server 14 (nginx.org) |
|---|---|---|
| `ps` shows | `nginx: master process /usr/sbin/nginx -g daemon on; master_process on;` | `nginx: master process /usr/sbin/nginx -c /etc/nginx/nginx.conf` |
| Config path | **implicit** (compiled-in default) | **explicit** (`-c`) |
| Config file loaded | `/etc/nginx/nginx.conf` | `/etc/nginx/nginx.conf` |
| Pre-start test | yes (`ExecStartPre ... -t`) | no |
| Reload | `nginx -s reload` | `kill -s HUP` |
| Stop | graceful QUIT, then TERM, then KILL | TERM |

**Same file, same behaviour.** Only style differs.

### 4.5 The boot sequence step by step (`Type=forking`)

1. Machine boots; kernel starts systemd (PID 1).
2. systemd reaches `multi-user.target`; nginx is `enabled`, so systemd starts it (after the network is up).
3. (Server 85 only) systemd runs `ExecStartPre` → `nginx -t` checks the config. Error → start aborted.
4. systemd runs `ExecStart` — it literally forks and executes that command, as if typed in a terminal.
5. Nginx reads its config and **binds port 80/443** (it's root at this point, so it may).
6. Nginx **forks**: the original process exits ("I'm done starting"), the child continues as the **master**.
7. The master writes its PID to `/run/nginx.pid`.
8. systemd reads the PID file → now monitors that process. If it dies, systemd knows the service crashed.
9. The master forks **worker processes** (Section 5).

### 4.6 Reading `systemctl status nginx`

```
● nginx.service - A high performance web server and a reverse proxy server
     Loaded: loaded (/usr/lib/systemd/system/nginx.service; enabled; preset: enabled)
     Active: active (running) since Tue 2026-10-06 14:36:51 CEST; 2 days ago
   Main PID: 431185 (nginx)
      Tasks: 9 (limit: 19063)
     CGroup: /system.slice/nginx.service
             ├─431185 "nginx: master process /usr/sbin/nginx -g daemon on; master_process on;"
             ├─431186 "nginx: worker process"
             ... (8 workers total)
```

| Line | Meaning |
|---|---|
| `Loaded: ... nginx.service` | which unit file is used |
| `enabled` | will auto-start at boot |
| `Active: active (running) since ...` | when it was started (≈ last boot/restart) |
| `Main PID` | the master process |
| `Tasks: 9` | 1 master + 8 workers |
| `CGroup` | the exact processes belonging to the service — **only real nginx**, unlike `grep` |

`Warning: some journal files were not opened due to insufficient permissions.` → just means I'm not root, so I can't read all logs. Use `sudo journalctl -u nginx` to see them.

---

## 5. Master and Worker Processes

### 5.1 Who creates the workers?

The **master** does. Chain: **systemd starts the master → master reads config → master calls `fork()` N times → N workers.**

### 5.2 How many? — `worker_processes auto;`

I never said "create 8 workers." This line in `/etc/nginx/nginx.conf` did (it's in **both** servers' configs):

```nginx
worker_processes auto;
```

`auto` = ask the OS how many CPU cores there are, create one worker per core.

| Server | Workers seen | Reason |
|---|---|---|
| 85 | 8 (PIDs 431186–431193) | 8 CPU cores |
| 14 | 4 (PIDs 1437–1440) | 4 CPU cores |

Verify:

```bash
nproc                                       # number of CPU cores
grep worker_processes /etc/nginx/nginx.conf # the directive
pgrep -c -f "nginx: worker"                 # count workers
```

You could hard-code `worker_processes 4;` — but `auto` is the sensible default.

### 5.3 Why one worker per core?

Each nginx worker is a **single-threaded event loop**. One worker handles **thousands of connections at once** using `epoll` (a Linux system call): "are any of my sockets ready to read/write? yes → handle it; no → wait." No threads, no context switching between them → very efficient.

But one single-threaded process uses **one core at a time**. 8 cores + 1 worker = 7 idle cores. 8 workers = the kernel spreads them across all 8 cores. 16 workers on 8 cores = extra context switching, slower. So `auto` = maximum use without oversubscribing.

### 5.4 `worker_connections` — capacity per worker

```nginx
events {
    worker_connections 768;    # server 85 (Debian default)
}
events {
    worker_connections 1024;   # server 14 (nginx.org default)
}
```

Max simultaneous connections **per worker**. Rough total = workers × worker_connections (server 85: 8 × 768 = 6144; server 14: 4 × 1024 = 4096). A proxied request uses **two** connections (client↔nginx and nginx↔backend), so real client capacity is about half.

### 5.5 Who does what — the restaurant analogy

**Master (runs as root) = restaurant manager.** Never serves customers. It:
- opens the restaurant (binds port 80/443 — needs root),
- hires waiters (forks workers),
- hands out the rulebook (config),
- manages staff (restarts a crashed worker; on "reload the menu", swaps workers).

**Workers (run as `www-data` / `nginx`) = waiters.** They do all the real work: accept connections, read HTTP requests, serve files, forward to backends (`proxy_pass`), send responses. They work independently; the OS distributes incoming connections among them.

### 5.6 Why workers drop root privileges

The master needs root for **one thing only**: binding ports < 1024. After that, workers are started under the `user` from the config (`user www-data;` / `user nginx;`). If someone exploits a bug in the HTTP-handling code (which runs in a worker), they get `www-data` permissions, **not root**. The master never touches untrusted HTTP traffic.

```
root   1436  ← master (root: binds port 80)
 ├─ nginx  1437  ← worker (low-privilege user)
 ├─ nginx  1438
 ├─ nginx  1439
 └─ nginx  1440
```

### 5.7 Zero-downtime reload

`sudo systemctl reload nginx` (or `sudo nginx -s reload`):

1. Signal reaches the **master**.
2. Master reads and **validates** the new config. (Invalid → keeps running with the old one, logs an error.)
3. Master starts **new workers** with the new config.
4. Master tells **old workers**: stop accepting new connections, finish current ones, exit.
5. Old workers drain and die; new workers handle everything.

The master **never stops** — its PID stays the same. At no moment are there zero workers. Old and new overlap briefly.

**Always test before reloading:**

```bash
sudo nginx -t && sudo systemctl reload nginx
```

`reload` vs `restart`: reload = graceful, keeps master; restart = full stop + start (drops connections briefly).

---

## 6. The Main Config File — `nginx.conf`

### 6.1 Config structure: contexts (nesting)

```nginx
# ── main context (global) ────────────────────────────
user  www-data;
worker_processes auto;

events {                       # ── connection handling ──
    worker_connections 768;
}

http {                         # ── everything HTTP ──
    # settings here apply to all sites below

    server {                   # ── one virtual host (one site) ──
        listen 80;
        server_name example.com;

        location /api/ {       # ── rule for a URL path ──
            proxy_pass http://127.0.0.1:8000;
        }
    }
}
```

Settings inherit **downward**: something set in `http {}` applies to every `server {}` unless overridden inside it.

### 6.2 Server 85's `nginx.conf` (Debian) — annotated

```nginx
user www-data;                                   # workers run as www-data (Debian's web user)
worker_processes auto;                           # one worker per CPU core
pid /run/nginx.pid;
error_log /var/log/nginx/error.log;
include /etc/nginx/modules-enabled/*.conf;       # Debian-only: load optional modules

events {
        worker_connections 768;
}

http {
        sendfile on;                             # kernel copies files directly to socket (fast static files)
        tcp_nopush on;
        types_hash_max_size 2048;

        include /etc/nginx/mime.types;           # maps .js → application/javascript, .css → text/css ...
        default_type application/octet-stream;   # unknown extensions

        ssl_protocols TLSv1 TLSv1.1 TLSv1.2 TLSv1.3;
        ssl_prefer_server_ciphers on;

        access_log /var/log/nginx/access.log;
        gzip on;                                 # compress responses

        include /etc/nginx/conf.d/*.conf;        # site configs (style 1)
        include /etc/nginx/sites-enabled/*;      # Debian-only: site configs (style 2) ← my boardfarm lives here
}
```

### 6.3 Server 14's `nginx.conf` (nginx.org) — annotated

```nginx
user  nginx;                                     # workers run as "nginx" user
worker_processes  auto;

error_log  /var/log/nginx/error.log notice;
pid        /var/run/nginx.pid;                   # /var/run → /run (same place)

events {
    worker_connections  1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';
    access_log  /var/log/nginx/access.log  main;  # uses the "main" format above

    sendfile        on;
    keepalive_timeout  65;                        # keep idle client connections open 65s
    server_tokens off;                            # hide nginx version in errors/headers (admin added)

    include /etc/nginx/conf.d/*.conf;             # ONLY conf.d — no sites-enabled
}
```

### 6.4 Differences table — all packaging (plus small admin tweaks)

| Setting | Server 85 (Debian) | Server 14 (nginx.org) | Why |
|---|---|---|---|
| `user` | `www-data` | `nginx` | each packager created its own account |
| `modules-enabled` include | yes | no | Debian splits modules into packages |
| `sites-enabled` include | yes | no | Debian convention (symlink enable/disable) |
| `worker_connections` | 768 | 1024 | different defaults |
| `gzip` | on | off (commented) | different defaults |
| `log_format main` | no | yes | nginx.org default |
| `server_tokens off` | no (commented) | yes | security tweak by admin |

**Important:** this main file is only global settings. The parts that matter for my app — which ports, which domains, where to proxy — live in the **included** files (`conf.d/*.conf`, `sites-enabled/*`).

The `user nginx;` line also explains server 14's `ps` output: the `nginx` account exists because of this package, and the admin reused it to run the Django apps.

---

## 7. `include` — It's Copy-Paste

### 7.1 Yes, it works like C's `#include`

When nginx reads `/etc/nginx/nginx.conf` and hits an `include` line, it **replaces that line with the full contents of the matching file(s)** — before processing anything. A glob like `*.conf` is expanded and the files are pasted in **alphabetical order**.

Server 14's main config:

```nginx
http {
    ...
    include /etc/nginx/conf.d/*.conf;
}
```

Directory contents:

```
boardfarm-upload.conf
cnrlogs-api-def.conf
cpetools-api-dev.conf
cpetools-dev.conf
default.conf
mv3tools-dev.conf
snmpapi-dev.conf
```

What nginx effectively sees in memory:

```nginx
http {
    ...everything from nginx.conf above the include...

    ...entire contents of boardfarm-upload.conf...
    ...entire contents of cnrlogs-api-def.conf...
    ...entire contents of cpetools-api-dev.conf...
    ...entire contents of cpetools-dev.conf...
    ...entire contents of default.conf...
    ...entire contents of mv3tools-dev.conf...
    ...entire contents of snmpapi-dev.conf...
}
```

Server 85 has two includes, so both directories are pasted into the same `http {}` block:

```nginx
include /etc/nginx/conf.d/*.conf;
include /etc/nginx/sites-enabled/*;     # ← boardfarm
```

### 7.2 Why split into files at all?

Purely for **humans** — one file per app is easier to manage, add, remove, and review than one giant file. To nginx it's all one config.

### 7.3 Consequences of "it's one config"

- A syntax error in **any** included file breaks the **whole** config → `nginx -t` fails → reload refused.
- Two files defining the same `server_name` on the same port → nginx warns `conflicting server name ... ignored`.
- An `upstream` name defined in one file is visible to all others (they share one namespace).
- Files must be pasted where the directive is allowed — `files contain `server {}`/`upstream {}` blocks because they're included **inside `http {}`**.

### 7.4 See the fully expanded config with your own eyes

```bash
sudo nginx -T              # test + DUMP the entire config, every included file, in order
sudo nginx -T | grep -n "server_name"      # all virtual hosts at a glance
sudo nginx -T | grep "# configuration file"  # which files got included
```

`nginx -T` is the proof that include = copy-paste: it prints the main file plus each included file with a `# configuration file /etc/nginx/conf.d/xyz.conf:` marker.

---

## 8. Virtual Hosting — Many Sites, One Nginx, One IP

This is the big concept behind most of my confusion.

### 8.1 The problem it solves

Server 14 has **one IP** (`10.63.69.36`) and runs **many different apps**. All of them want port **443** (HTTPS). We can't give each a separate IP, and we can't separate them by port. So how does nginx know which app a request is for?

**Answer: by the domain name the browser asked for.**

### 8.2 The `Hostheader

Every HTTP request carries the domain name in a `Host` header. Real requests on the wire:

```http
GET /some/page HTTP/1.1
Host: cpetools-dev.upclabs.com
Accept: text/html
```

```http
GET /some/page HTTP/1.1
Host: mv3tools-dev.upclabs.com
Accept: text/html
```

Same IP, same port, same nginx process. **Only the `Host` header differs.** The browser fills it from the URL you typed.

### 8.3 `server_name` — matching the Host header to a `server {}` block

1. Request arrives on port 443.
2. Nginx rea `Host: mv3tools-dev.upclabs.com`.
3. Nginx looks at all `server {}` blocks that `listen` on 443.
4. Finds `server_name mv3tools-dev.upclabs.com;` (in `mv3tools-dev.conf`).
5. Handles the request with **that block's** rules only.
6. A request with `Host: cpetools-dev.upclabs.com` goes to `cpetools-dev.conf` instead.

**Selection order:** first by `listen` (IP:port), then by `server_name` among those. Exact name → wildcard (`*.example.com`) → regex (`~...`) → `default_server`.

### 8.4 `default_server` catch-all

If no `server_name` matches, nginx uses the block marked `default_server` for that port. Server 14's `default.conf`:

```nginx
server {
    listen                  80 default_server;
    server_name             ~. "";          # regex "any char" + empty Host
    return                  308 https://$host$request_uri;   # force HTTPS
}

server {
    listen       443 ssl default_server;
    server_name ~. "";
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.upclabs.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.upclabs.com.key;
    return 404;                              # unknown domain → 404
}
```

So hitting `https://10.63.69.36/` directly (Host = the IP, which no block names) → **404**. If no block is marked `default_server`, the **first** block for that port (in include order) becomes the default — a common source of "why am I seeing the wrong site?".

### 8.5 DNS — why all the names give the same IP

```
$ ping mv3tools-des.com
PING mv3tools-dev.upclabs.com (10.63.69.36) ...
$ ping cpetools-dev.upclabs.com
PING cpetools-dev.upclabs.com (10.63.69.36) ...
```

DNS is just a **phone book**: name → IP. Somewhere in the company DNS there are records like:

```
cpetools-dev.upclabs.com       A    10.63.69.36
cpetools-api-dev.upclabs.com   A    10.63.69.36
mv3tools-dev.upclabs.com       A    10.63.69.36
snmpapi-dev.upclabs.com        A    10.63.69.36
```

DNS knows nothing about nginx. It gets the browser to the right **machine**nginx picks the right **app** with `server_name`.

Bonus observation: the ping time was `0.04 ms` with `ttl=64` because I pinged **from server 14 itself** — `10.63.69.36` *is* server 14. (`ip addr` confirms.)

```bash
getent hosts mv3tools-dev.upclabs.com   # resolve like apps do (includes /etc/hosts)
dig +short mv3tools-dev.upclabs.com     # ask DNS directly
```

### 8.6 HTTPS: SNI and the wildcard certificate

With HTTPS, encryption is negotiated **before** the HTTP request (and its Host header) is sentSo how does nginx know which certificate to present? **SNI (Server Name Indication):** during the TLS handshake the browser sends the domain name in plain text. Nginx uses it to pick the `server {}` block/certificate.

On server 14, every block uses the **same wildcard certificate** `*.upclabs.com` (`Public_Certificate_wildcard.upclabs.com.cert`). One cert valid for every `xyz.upclabs.com` → one file shared by all sites.

### 8.7 Full flow for one request (server 14)

```
Browser wants: https://cpetools-api-dev.upclabs.com/api/something

Step 1 — DNS lookup
   Browser: "What IP is cpetools-api-dev.upclabs.com?"
   DNS:     10.63.69.36

Step 2 — TCP connection
   Browser connects to 10.63.69.36 port 443

Step 3 — TLS handshake
   Browser sends SNI = cpetools-api-dev.upclabs.com
   nginx presents the *.upclabs.com certificate; encryption established

Step 4 — HTTP request
   GET /api/something HTTP/1.1
   Host: cpetools-api-dev.upclabs.com

Step 5 — nginx routing
   Host matches serverpetools-api-dev.conf
   location / → uwsgi_pass to the cpetools Django app (unix socket)

Step 6 — Response goes back the same way
```

### 8.8 Test virtual hosts without a browser

```bash
# Send a request to the IP but pretend to be a given domain (sets Host + SNI correctly)
curl -v --resolve mv3tools-dev.upclabs.com:443:10.63.69.36 https://mv3tools-dev.upclabs.com/

# Just override the Host header (SNI will be the IP, so add -k to skip cert check)
curl -vk -H "Host: mv3tools-dev.upclabs.com" https://3.69.36/

# Plain HTTP on server 85
curl -v http://10.63.68.173/api/
```

---

## 9. Inside a `server {}` Block — `location`, `root`, `proxy_pass`

### 9.1 Each `server {}` is an isolated world — no `location /` conflict

Several blocks all have `location /` — that's fine. `location` only means something **within** its `server {}` block.

**Analogy:** server blocks are separate buildings on the same street. Same street address (IP), different name on the door (`server_name`). Each building has a lobbyation /`), maybe an office (`location /api/`), a storeroom (`location /static`). Two buildings both having a lobby is no conflict — you're inside one building at a time.

Nginx picks exactly **one** server block per request (by Host), then matches the path against **that block's** locations only:

```
Host: cpetools-dev.upclabs.com      Path: /  → cpetools-dev.conf      → location / → static files from disk
Host: mv3tools-dev.upclabs.com      Path: /  → mv3tools-dev.conf      → location / → uwols Django
Host: cpetools-api-dev.upclabs.com  Path: /  → cpetools-api-dev.conf  → location / → uwsgi_pass cpetools API Django
```

### 9.2 How nginx picks a `location` (the matching rules)

| Syntax | Type | Example |
|---|---|---|
| `location = /path` | **exact** match only | `location = /__whoami` |
| `location ^~ /path` | prefix; if it's the longest prefix, **skip regex checks** | `location ^~ /static/` |
| `location ~ regex` | regex, case-sensitive | `location ~ \.php$` |
| `location ~* regex` |  case-insensitive | `location ~* \.(png|jpg)$` |
| `location /path` | plain prefix | `location /api/` |
| `location @name` | **named** — only for internal redirects | `location @login` |

**Algorithm:**
1. If an `=` exact match exists → use it, stop.
2. Find the **longest matching prefix** and remember it.
3. If that prefix has `^~` → use it, stop.
4. Check regex locations **in the order they appear**; first match wins.
5. No regex matched → use the remembered longest prefix.

Example with server 85g:

| Request path | Matching locations | Winner |
|---|---|---|
| `/` | `/` | `location /` → React |
| `/devices/5` | `/` | `location /` → React (SPA route) |
| `/api/devices/` | `/`, `/api/` | `location /api/` (longer) → FastAPI |
| `/docs` | `/`, `/docs` | `location /docs` → FastAPI |
| `/openapi.json` | `/`, `/openapi.json` | `location /openapi.json` → FastAPI |
| `/assets/main-abc123.js` | `/` | `location /` → static file |

`location /` matches **everything** (every path starts with `/`) âback.

Note: plain prefix `location /docs` also matches `/docs/oauth2-redirect` and even `/docsXYZ`. Use `/docs/` or `= /docs` when you need to be strict.

### 9.3 `root` vs `alias` (serving files from disk)

```nginx
# root: path = root + full URI
location / {
    root /var/www/app/dist;          # /assets/a.js → /var/www/app/dist/assets/a.js
}

# alias: path = alias + URI with the location prefix removed
location /static {
    alias /opt/mv3tools_autodeploy/active_deployment/collected_static;
    # /stic/css/x.css → /opt/.../collected_static/css/x.css
}
```

Server 14 uses `alias` for Django's `/static` (collected static files) so nginx serves CSS/JS directly without bothering Django. `expires 10;` adds caching headers (10 seconds; `expires 10m;` = 10 minutes).

### 9.4 `try_files` — the SPA fallback

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

Try in order:
1. `$uri` — a real file? (`/assets/main.js` → `dist/assets/main.js`) → serve it.
2. `$uri/` — a directory? → sx`.
3. otherwise → **internally redirect** to `/index.html`.

Why: React Router handles URLs like `/devices/5` **in the browser**. There's no file `dist/devices/5` on disk. Without the fallback, refreshing that page gives **404**. With it, nginx returns `index.html`, React loads, reads the URL, and shows the right page.

### 9.5 `proxy_pass` — forwarding to a backend

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;                                   # passginal Host to backend
    proxy_set_header X-Real-IP $remote_addr;                       # real client IP (backend would otherwise see 127.0.0.1)
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;   # chain of client/proxy IPs
}
```

Nginx opens a **new HTTP connection** to `127.0.0.1:8000`, sends the request, gets the response, sends it to the client. Nginx doesn't understand or run Python — it's a middleman.

Useful extra: `proxy_set_header X-Forwarded-Proto $scheme;` tells the backend wheer the client used http or https.

### 9.6 ⚠️ The trailing slash rule in `proxy_pass` (very common bug)

| Config | Client requests | Backend receives |
|---|---|---|
| `location /api/ { proxy_pass http://127.0.0.1:8000; }` (no URI part) | `/api/devices/` | `/api/devices/` (full path kept) |
| `location /api/ { proxy_pass http://127.0.0.1:8000/; }` (with `/`) | `/api/devices/` | `/devices/` (`/api/` replaced by `/`) |

Server 85 uses the first form → **FastAPI receives `/api/devices/`, so FastAPI routt include the `/api` prefix** (e.g. `APIRouter(prefix="/api")`).

### 9.7 `upstream` and `uwsgi_pass` (server 14's Django apps)

```nginx
upstream mv3tools {                                  # a named group of backends
    server unix:///run/uwsgi/mv3tools_autodeploy.sock;   # a Unix domain socket file
}

server {
    ...
    location / {
        uwsgi_pass mv3tools;          # forward using the uwsgi binary protocol
        uwsgi_read_timeout 600s;      # wait up to 10 min for slow responses
        include uwsgi_params;         # standard variables uwsgi needs (REQUEST_METHOD, PATH_INFO ...)
    }
}
```

- `upstream` gives a name to one or more backend servers (can list several for load balancing).
- `uwsgi_pass` is like `proxy_pass` but speaks the **uwsgi protocol** (what the uwsgi app server expects) instead of HTTP.
- The backend is a **socket file**, not a port. This matches the `ps` output: `uwsgi --ini /etc/mv3tools_autodeploy/uwsgi.ini` creates that socket.

| | Server 85 (FastAPI) | Server 14 (Django) |
|---|---|---|
| App server | uvicorn | uwsgi |
| Directive | `proxy_pass` | `uwsgi_pass` |
| Protocol | HTTP | uwsgi |
| Address | `127.0.0.1:8000` (TCP) | `unix:///run/uwsgi/x.sock` (socket file) |

### 9.8 Other directives seen in the configs

| Directive | Meaning |
|---|---|
| `listen 443 ssl;` | listen on 443 with TLS |
| `ssl_certificate` / `ssl_certificate_key` | the cert and private key files |
| `charset utf-8;` | adds charset to Content-Type |
| `client_max_body_size 1M;` | max upload/request body; bigger → **413 Request Entity Too Large** |
| `return 307 https://$host$request_uri;` | redirect to HTTPS (307/308 keep the method, e.g. POST stays POST) |
| `add_header ... always;` | add response header even on error responses |
| `index index.html;` | file served for a directory request |

---

## 10. Server 14 Walkthrough — Every Config File Explained

Style: **one domain per app**, every app on `10.63.69.36`, HTTPS everywhere, Django apps via uwsgi sockets.

```
cpetools-dev.upclabs.com     tatic frontend (HTML/CSS/JS files from disk)
cpetools-api-dev.upclabs.com  → cpetools Django API (uwsgi socket)
mv3tools-dev.upclabs.com      → mv3tools Django app (uwsgi socket)
snmpapi-dev.upclabs.com       → snmpapi Django app (uwsgi socket)
cnrlogs-api-...upclabs.com    → cnrlogs Django API (uwsgi socket)
anything else                 → default.conf → 404
```

### 10.1 `default.conf` — catch-all
Covered in 8.4: port 80 → redirect to HTTPS (308); port 443 with unknown Host → 404.

### 12 `cpetools-dev.conf` — a pure static frontend

```nginx
server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.upclabs.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.upclabs.com.key;

    server_name cpetools-dev.upclabs.com;
    root /opt/cpetools_autodeploy/active_deployment/dist;   # built frontend (npm run build output)
    index index.html;

    charset     utf-8;
    client_max_body_size 1M;

    location / {
      expires 10m;          # browser may cache files for 10 minutes
    }
}
```

No backend at all — nginx just serves files. The JS in those files calls the **API domain** (`cpetools-api-dev.upclabs.com`).

`active_deployment` is almost certainly a **symlink** to the current release folder (deploy tool switches the link to release new versions) — check with `ls -l /opt/cpetools_autodeploy/`.

### 10.3 `cpetools-api-dev.conf` — API backend with CORS

```nginx
upstream cpetools_api_autodeploy {
    serve:///run/uwsgi/cpetools_api_autodeploy.sock;
}

# redirect http to https
server {
  server_name             cpetools-api-dev.upclabs.com;
  listen                  80;
  return                  307 https://$host$request_uri;
}

server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.upclabs.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.upclabs.com.key;

    server_name cpetools-api-dev.upclabs.com;
    charset     utf-8;
    client_max_body_size 1M;

    location /static {                      # Django admin/DRF static files served by nginx directly
        alias /opt/cpetools_api_autodeploy/active_deployment/collected_static;
        expires 10;
    }

    location / {
        # Simple requests
        if ($request_method ~* "(GET|POST|DELETE)") {
            add_header "Access-Control-Allow-Origin" * always;
        }
        # Preflighted requests
        if ($request_method = OPTIONS ) {
            add_header "Access-Control-Allow-Origin" * always;
            add_header "Access-Control-Allow-Methods" "GET, POST, DELETE, OPTIONS, HEAD";
            add_header "Access-Control-Allow-Headers" "Authorization, Origin, X-Requested-With, Content-Type, Accept";
            return 200;                     # answer the preflight directly, never reaches Django
        }
        uwsgi_pass cpetools_api_autodeploy;
        uwsgi_read_timeout 600s;
        include uwsgi_params;
    }
}
```

Why the CORS headers: the frontend lives on `cpetools-dev.upclabs.com`, the API on `cpetools-api-dev.upclabs.com` → **different origins** → the browser blocks the JS from reading API responses unless the API says it's allowed (Section 12.4).

(Note: `if` inside `location` is officially discouraged in nginx because it behaves surprisingly in some cases; using it only for `add_header`/`return` like here is the generally-safe use.)

### 10.4 `mv3tools-dev.conf` — same pattern, slightly different CORS

```nginx
upstream mv3tools {
    server unix://wsgi/mv3tools_autodeploy.sock;
}

server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.upclabs.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.upclabs.com.key;

    server_name mv3tools-dev.upclabs.com;
    charset     utf-8;
    client_max_body_size 1M;

    location /static {
        alias /opt/mv3tools_autodeploy/active_deployment/collected_static;
        expires 10;
    }

    location / {
        if ($request_method ~* "(GET|POST|DELETE)") {
            add_header "Access-Control-Allow-Origin" '*' always;
            add_header "Access-Control-Allow-Methods" "GET, POST, OPTIONS, HEAD, DELETE";
        }
        if ($request_method = OPTIONS ) {
            add_header "Access-Control-Allow-Origin"  $http_origin always;   # echoes the caller's origin
            add_header "Access-Control-Allow-Methods" "GET, POST, OPTIONS, HEAD, DELETE";
            add_header "Access-Control-Allow-Headers" "Authorization, Origin, X-Requested-With, Content-Type, Accept";
            return 204;                                                      # 204 No Content
        }
        uwsgi_pass mv3tools;
        uwsgi_read_timeout 600s;
        include uwsgi_params;
    }
}
```

No port-80 block here → plain `http://mv3tools-dev...` falls to `default.conf`, which redirects to HTTPS anyway.

### 10.5 How the `ps` output maps to these configs

| `ps` process (user `nginx`) | What it is | Reached via |
|---|---|---|
| `uwsgi --ini /etc/mv3tls_autodeploy/uwsgi.ini` | mv3tools web app | `/run/uwsgi/mv3tools_autodeploy.sock` ← `mv3tools-dev.conf` |
| `uwsgi --ini /etc/cpetools_api_autodeploy/uwsgi.ini` | cpetools API | `/run/uwsgi/cpetools_api_autodeploy.sock` ← `cpetools-api-dev.conf` |
| `uwsgi --ini /etc/snmpapi/uwsgi.ini` | snmpapi | ← `snmpapi-dev.conf` |
| `uwsgi --ini /etc/cnrlogs_api_autodeploy/uwsgi.ini` | cnrlogs API | ← `cnrlogs-api-def.conf` |
| `celery ... worker` | background task workers | not via nginx (talk to a queue) |ry ... beat` | scheduled-task trigger | not via nginx |
| `manage.py tftpserver` | TFTP server | not via nginx (own UDP port) |

Several uwsgi lines with the same `--ini` = one uwsgi master plus its own worker children (same master/worker idea as nginx, see the PPID column).

---

## 11. Server 85 Walkthrough — My Boardfarm Config

Style: **one server block, path-based routing**, plain HTTP on the IP.

`/etc/nginx/sites-enabled/boardfarm`:

```nginx
server {
    listen 80;
    server_name 10.63.68.173;        # matches requests whose Host is the IP

    # React frontend — everything not matched below
    root /home_ldap/ahazra/workspace/boardfarm_frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;    # SPA fallback
    }

    # FastAPI — all API routes
    location /api/ {
        proxy_pass http://127.0.0.1:8000;    # no trailing slash → FastAPI receives /api/...
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Swagger docs and OpenAPI schema
    location /docs {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /redoc {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /openapi.json {                 # Swagger UI at /docs fetches this
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

```
http://10.63.68.173/               → React (static files from dist/)
http://10.63.68.173/devices/5      → React (try_files → index.html)
http://10.63.68.173/api/...        → FastAPI on 127.0.0.1:8000
http://10.63.68.173/docs           → FastAPI Swagger UI
http://10.63.68.173/redoc          → FastAPI ReDoc
http://10.63.68.173/openapi.json   → FastAPI schema
```

Notes:
- `server_name` can be an **IP**. If someone uses a hostname instead (e.g. `nl-itc-l-ubun00085`), the Host won't match → nginx falls back to the `default_server` (Debian ships `sites-enabled/default` with `listen 80 default_server;` showing the "Welcome to nginx" page). Check `ls -l /etc/nginx/sites-enabled/`.
- `www-data` needs traverse permission on `/home_ldap/ahazra/...` (see 2.13).
- `127.0.0.1:8000` must be where the backend is actually reachable **on the host**: uvicorn running directly on the host, or a Docker container published to host port 8000 (`-p 127.0.0.1:8000:8080`). An earlier session mentioned port 9090 — whichever it is, `proxy_ps` must point to the **host-side** port. Verify with `ss -tlnp | grep -E '8000|9090'`.

### 11.1 Server 14 vs Server 85 — two deployment styles

| | Server 14 | Server 85 |
|---|---|---|
| Routing by | **domain name** (`server_name`) | **URL path** (`location`) |
| Frontend URL | `https://cpetools-dev.upclabs.com/` | `http://10.63.68.173/` |
| API URL | `https://cpetools-api-dev.upclabs.com/...` | `http://10.63.68.173/api/...` |
| `server {}` blocks per app | separate for frontend and API | one for both | Same-origin? | **No** → CORS headers needed | **Yes** → no CORS needed |
| DNS entries needed | one per app | none (uses IP) |
| HTTPS | yes (wildcard cert) | no (plain HTTP) |

Both are valid and use exactly the same nginx mechanisms. The choice is organizational, not a technical necessity.

---

## 12. The Browser Flow — Frontend Download, Then API Calls

### 12.1 Step 1 — browser downloads `index.html`

User types `http://10.63.68.173/`:

```
Browser → nginx:   GET / HTTP/1.1
                 .63.68.173

nginx: server_name 10.63.68.173 matches
       location / → try_files $uri $uri/ /index.html
       "/" is not a file → falls to /index.html
       reads .../boardfarm_frontend/dist/index.html from disk, sends it
```

`index.html` is a small skeleton:

```html
<!DOCTYPE html>
<html>
<head>
  <script src="/assets/main-abc123.js"></script>
  <link rel="stylesheet" href="/assets/style-def456.css">
</head>
<body>
  <div id="root"></div>
</body>
</html>
```

### 12.2 Step 2 — browser downloads  CSS

The browser sees the tags and makes **more requests**:

```
GET /assets/main-abc123.js     → location / → try_files finds dist/assets/main-abc123.js → sent
GET /assets/style-def456.css   → same → sent
```

Now the **entire React app is loaded and running in the browser**. Nginx's frontend job is done — it only served files. (The hash in the filename, `abc123`, changes every build so browsers never use a stale cached copy.)

### 12.3 Step 3 — the React app calls the API (separate requestspt
// inside a React component
useEffect(() => {
  fetch('/api/devices/')
    .then(res => res.json())
    .then(data => setDevices(data));
}, []);
```

`fetch('/api/devices/')` triggers a **new, separate HTTP request**. A relative URL is completed by the browser using the current page's origin → `http://10.63.68.173/api/devices/`:

```
Browser → nginx:   GET /api/devices/ HTTP/1.1
                   Host: 10.63.68.173

nginx: location /api/ → proxy_pass http://127.0.0.1:8000
       FastAPI handles /aices/, returns JSON
       nginx relays JSON back → React renders the device list
```

**So yes:** the browser downloads the whole frontend first (HTML + JS + CSS), then the JavaScript running in the browser makes separate fetch/XHR requests. Every request carries its path (and Host), and nginx uses them to decide: static file or backend?

```
Time ─────────────────────────────────────────────────────/                     → index.html        (nginx, from disk)
 GET /assets/main.js       → JS bundle         (nginx, from disk)
 GET /assets/style.css     → CSS               (nginx, from disk)
        [React starts running in the browser]
 GET /api/devices/         → JSON              (nginx → FastAPI)
 POST /api/devices/5/reset → JSON              (nginx → FastAPI)
 ... more API calls as the user clicks ...
```

### 12.4 Server 14: separate domains → cross-origin → CORS

There the frontenis on `cpetools-dev.upclabs.com` and the code calls a **full URL** on another domain:

```javascript
fetch('https://cpetools-api-dev.upclabs.com/api/devices/')
```

Browser does a DNS lookup → same IP `10.63.69.36` → same nginx → different `Host` → API server block.

**Origin = scheme + host + port.** `https://cpetools-dev.upclabs.com` ≠ `https://cpetools-api-dev.upclabs.com` → **cross-origin**. Browsers enforce **CORS**: JS may only read the response if the server returns `Access-Control-Allow-itting it.

For "non-simple" requests (e.g. with an `Authorization` header or `Content-Type: application/json`), the browser first sends a **preflight**:

```http
OPTIONS /api/devices/ HTTP/1.1
Host: cpetools-api-dev.upclabs.com
Origin: https://cpetools-dev.upclabs.com
Access-Control-Request-Method: POST
Access-Control-Request-Headers: authorization, content-type
```

The nginx `if ($request_method = OPTIONS)` block answers it directly:

```http
HTTP/1.1 200 OK            (or 204 on mv3tools)
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS, HEAD
Access-Control-Allow-Headers: Authorization, Origin, X-Requested-With, Content-Type, Accept
```

Only then does the browser send the real POST. CORS is enforced **by the browser** only — `curl` ignores it.

**Server 85:** page and API are both `http://10.63.68.173` → **same origin** → no CORS needed. That's a big advantage of path-based routing.

---

## 13. Docker, `0.0.0.0` vs `localhost`, Port Publishing

### 13.1 The chen the backend runs in Docker

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
   │  Docker rt          │  ← e.g. -p 9090:8080 in docker run
   │    │  forwards to               │
   │    ▼                            │
   │  ┌─────────────────────────┐    │
   │  │ Container (172.17.0.3)  │    │
   │  │ FastAPI on 0.0.0.0:8080 │    │
   │  └─────────────────────────┘    │
   └─────────────────────────┘
```

1. Request arrives at host port 80 → nginx.
2. nginx matches `location /api/` → `proxy_pass http://127.0.0.1:9090` (the **published host port**).
3. Docker forwards host `9090` → container IP `172.17.0.3` port `8080`.
4. uvicorn inside the container, bound to `0.0.0.0:8080`, accepts it.
5. Response travels back: container → Docker → nginx → browser.

`-p HOST:CONTAINER` → `-p 9090:8080` means "host port 9090 → container port 8080". **nginx's `proxy_pass` uses the HOST port**, never e container port.

### 13.2 Why the container app MUST bind `0.0.0.0`

In bridge mode a container has its **own network namespace** with (at least) two interfaces:

- `lo` — `127.0.0.1`, reachable only from inside the container
- `eth0` — e.g. `172.17.0.3`, how Docker's port forwarding reaches it

Docker forwards traffic to the **container's IP (`eth0`)**, not its loopback.

- App binds `127.0.0.1:8080` → listens only on the container's loopback → forwarded traffic arrives on `eth0` → nobody listeonnection refused**. App looks "up" but is unreachable.
- App binds `0.0.0.0:8080` → listens on `lo` **and** `eth0` → forwarded traffic accepted ✅

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`localhost` only makes sense for something that must **never** be reached from outside its own machine/namespace (e.g. a helper daemon).

### 13.3 Security: `0.0.0.0` inside the container is normal and safe

What's actually reachable depends on:
- (a) the Docker **poring** (only published ports are exposed),
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

Now only nginx (on the same hon reach it.

### 13.4 Without Docker (uvicorn directly on the host)

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Here `127.0.0.1` is actually the *better* choice: nginx is on the same machine, so it can reach loopback, and nobody else can bypass nginx. (In a container the rule flips, because "same machine" for the container means "inside the container".)

### 13.5 Who manages what

| Thing | Managed by | My responsibility? |
|---|---|---|
| nginx install + unit file | platform/provisioning, systemd | no |
| nginx site config (`sites-enabled/boardfarm`) | me (with sudo) | yes |
| Docker container / uvicorn | me | yes |
| Port alignment (`proxy_pass` ↔ published port) | me | yes |
| `--host 0.0.0.0` in container | me | yes |

---

## 14. Advanced — `internal`, `auth_request`, `location = /__whoami`

So far every request came **from a client**. But nginx can also make requests **to itself** — internal redirects and subrequests. That's what `internal`, `auth_request`, `@named` locations a_whoami` are about.

### 14.1 External vs internal requests

| | External request | Internal request |
|---|---|---|
| Who starts it | the browser / curl | nginx itself |
| Visible to client? | yes | no — happens inside nginx |
| Examples | `GET /api/devices/` | `try_files` fallback to `/index.html`, `error_page`, `auth_request` subrequest, `X-Accel-Redirect` |

I've already used one without knowing: `try_files $uri $uri/ /index.html;` — the jump to `/index.html` is an **internal redirect**. The browsered for `/devices/5` and never learns nginx actually served `/index.html`.

### 14.2 `internal` — a location clients can't reach

```nginx
location /protected_files/ {
    internal;                 # only internal redirects/subrequests may use this location
    alias /srv/files/;
}
```

- Browser requests `GET /protected_files/report.pdf` directly → **404**.
- nginx itself (via `auth_request`, `error_page`, `X-Accel-Redirect`, `try_files`, `rewrite`) → allowed.

Think of it as a staff-only door inside ilding: customers can't open it, staff can.

### 14.3 Named locations `@name` — always internal

```nginx
location @login {
    return 302 /login?next=$request_uri;
}
```

A named location can't be addressed by any URL at all; it's only a target for `try_files`, `error_page`, etc. Example:

```nginx
location / {
    try_files $uri @backend;      # file not found → hand off to the backend
}
location @backend {
    proxy_pass http://127.0.0.1:8000;
}
```

### 14.4 `error_page` — internal redirect on an code

```nginx
error_page 404 /404.html;          # show a custom page (internal redirect, client still sees 404)
error_page 401 = @login;           # "=" → response code comes from @login (here: 302 redirect)
error_page 502 503 504 /maintenance.html;
```

### 14.5 `auth_request` — nginx asks "is this user allowed?" before every request

**The problem:** I want `/api/` (or the whole site) protected by login, but I don't want every backend/static location to implement auth itself.

**The idea:** before hing a request, nginx makes an **internal subrequest** to an auth endpoint. The auth endpoint's **status code** decides:

| Subrequest returns | nginx does |
|---|---|
| **2xx** (200, 204) | ✅ allow — continue with the original request |
| **401** or **403** | ❌ deny — returns that code to the client (can be caught with `error_page`) |
| anything else | 💥 500 Internal Server Error |

The auth endpoint's **body is ignored**; only status (and optionally headers) matter.

### 14.6 `location = /__whoaauth endpoint

```nginx
location = /__whoami {
    internal;                                     # browsers can't call it directly
    proxy_pass http://127.0.0.1:8000/auth/whoami; # FastAPI checks the session/token
    proxy_pass_request_body off;                  # don't send the original body (e.g. big uploads)
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI    $request_uri;     # tell auth which URL was requested
    proxy_set_header X-Original-Method $request_method;
}
```

Why it's written this way:
- **`=`** → exact match, highest priority; nothing else can shadow it, and it's the fastest match.
- **`/__whoami`** with double underscore → a naming convention so it can't collide with a real app or React route (no one builds a page called `/__whoami`).
- **`internal`** → clients can't probe it; only `auth_request` uses it.
- The original request's headers (including **Cookie** and **Authorization**) are passed to the subrequest by default — that's how the backend sees ton.
- `proxy_pass` here **has a URI part** (`/auth/whoami`), so the backend receives `/auth/whoami`, not `/__whoami` (trailing-URI rule, 9.6).

### 14.7 Full working example (server 85 style)

```nginx
server {
    listen 80;
    server_name 10.63.68.173;

    root /home_ldap/ahazra/workspace/boardfarm_frontend/dist;
    index index.html;

    # ── Public: the login page and auth API must NOT require login ──
    location /api/auth/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_headehost;
    }

    # ── Protected API ──
    location /api/ {
        auth_request /__whoami;                          # 1. ask first
        auth_request_set $auth_user $upstream_http_x_user;   # 2. capture X-User header from the auth response
        proxy_set_header X-User $auth_user;              # 3. pass identity to the real backend

        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwardedoxy_add_x_forwarded_for;
    }

    # ── The internal auth check ──
    location = /__whoami {
        internal;
        proxy_pass http://127.0.0.1:8000/api/auth/whoami;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
    }

    # ── Frontend (left public here so the login page can load) ──
    location / {
        try_files $uri $uri/ /index.html;
    }

    # ── Unauthenticated → JSON 401 for the 
    error_page 401 = @unauthorized;
    location @unauthorized {
        default_type application/json;
        return 401 '{"detail":"Not authenticated"}';
    }
}
```

For a classic server-rendered site you'd instead redirect to a login page:

```nginx
error_page 401 = @login;
location @login {
    return 302 /login?next=$request_uri;
}
```

### 14.8 The matching FastAPI endpoint

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
    user = requeeaders.get("X-User")              # identity injected by nginx
    return {"user": user, "devices": [...]}
```

### 14.9 Flow of one protected request

```
Browser:  GET /api/devices/   Cookie: session=abc
   │
   ▼
nginx: location /api/ matched → sees auth_request /__whoami
   │
   ├──► INTERNAL subrequest: GET /__whoami  (Cookie: session=abc copied along)
   │        location = /__whoami → proxy_pass → FastAPI /api/auth/whoami
   │        FastAPI: session valid → 204, X-User: aha─── 204
   │
   │  2xx → allowed. auth_request_set: $auth_user = "ahazra"
   │
   ├──► proxy_pass → FastAPI /api/devices/   (X-User: ahazra)
   │◄──── 200 JSON
   ▼
Browser receives JSON.  (It never saw /__whoami.)

If the session is invalid:
   /__whoami → 401 → nginx stops → error_page 401 → @unauthorized → client gets 401 JSON
   /api/devices/ backend is never even called.
```

Every protected request costs one extra subrequest. For heavy traffic you can cache auth results (`proxy_cache` keyed on the cookie) — usually unnecessary on an internal tool.

Check that the module is present (both packages normally include it):

```bash
nginx -V 2>&1 | grep -o with-http_auth_request_module
```

### 14.10 The other common `/__whoami` pattern — a public "who am I" for the frontend

Sometimes `/__whoami` is **not** internal — it's a small endpoint the React app calls on startup to learn the logged-in user:

```nginx
location = /__whoami {
    proxy_pass http://127:8000/api/auth/whoami;
    proxy_set_header Host $host;
}
```

```javascript
const me = await fetch('/__whoami').then(r => r.ok ? r.json() : null);
if (!me) window.location = '/login';
```

How to tell which pattern a config uses: **`internal;` present** → it's an auth_request target; **absent** → the browser is meant to call it.

### 14.11 `X-Accel-Redirect` — backend decides, nginx delivers the file

Another use of `internal`: protected downloads. The backend checks permissions, then tells nginx "seis file" without streaming it through Python.

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
}

location /protected_files/ {
    internal;
    alias /srv/boardfarm/logs/;
}
```

```python
@app.get("/api/logs/{name}")
def get_log(name: str, request: Request):
    if not user_can_read(request, name):
        raise HTTPException(403)
    return Response(headers={"X-Accel-Redirect": f"/protected_files/{name}"})
```

nginx sees the `X-Accel-Redirect` header in the backend's response → internay redirects to `/protected_files/<name>` → serves the file from disk efficiently. Clients can't hit `/protected_files/` directly because it's `internal`.

### 14.12 Summary of internal machinery

| Feature | Starts an internal request when... | Typical use |
|---|---|---|
| `try_files ... /index.html` | file not found | SPA routing |
| `error_page CODE target` | a response has that code | custom error pages, login redirect |
| `auth_request /x` | before every request in that location | central authenticatn |
| `X-Accel-Redirect` header | backend sends that header | protected downloads |
| `internal;` | — (marks a location as internal-only) | hide auth endpoints/files |
| `@name` | — (always internal) | fallback handlers |

---

## 15. Command Cheat Sheet

### Processes & service

```bash
systemctl status nginx              # is it running, since when, master + workers (CGroup)
systemctl cat nginx                 # unit file in effect (incl. overrides)
cat /usr/lib/systemd/system/nginx.service
systemctl nabled nginx          # starts at boot?
sudo systemctl reload nginx         # graceful config reload (master stays)
sudo systemctl restart nginx        # full stop + start
sudo journalctl -u nginx -n 50      # service logs
pgrep -a nginx                      # real nginx processes only
ps -ef | grep "[n]ginx:"            # same, without matching the grep itself
ps -ef --forest | less              # process tree (see PPIDs)
cat /run/nginx.pid                  # master PID
nproc                               # CPU cores → number of workers with "auto"
```

### Config

```bash
sudo nginx -t                       # test config syntax
sudo nginx -T                       # test + dump the FULL expanded config (proof of include = paste)
sudo nginx -T | grep -n server_name # list all virtual hosts
sudo nginx -t && sudo systemctl reload nginx   # safe reload
ls -l /etc/nginx/conf.d/ /etc/nginx/sites-enabled/
grep -E "worker_processes|^user" /etc/nginx/nginx.conf
```

### Package / build

```bash
nginx -v ; nginx -V &1 | tr ' ' '\n'
apt-cache policy nginx
dpkg -S /usr/lib/systemd/system/nginx.service
```

### Network

```bash
ip addr                             # my interfaces and IPs
ss -tlnp                            # who listens on which address:port
sudo ss -tlnp | grep nginx
getent hosts mv3tools-dev.upclabs.com
dig +short mv3tools-dev.upclabs.com
curl -v http://10.63.68.173/api/
curl -v --resolve mv3tools-dev.upclabs.com:443:10.63.69.36 https://mv3tools-dev.upclabs.com/
curl -vk -H "Host: mv3tools-dev.upclabs.com" https://10.63.69.36/
curl -v http://127.0.0.1:8000/api/  # hit the backend directly, skipping nginx
```

### Logs

```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log      # FIRST place to look for 502/403/404 causes
```

### Docker

```bash
docker ps                                  # see PORTS column, e.g. 127.0.0.1:9090->8080/tcp
docker port <container>
docker logs -f <container>
```

### Permissions

```bash
namei -l /home_ldap/ahazra/workspace/boardfarm_frontend/dist/index.html
sudo -u www-data cat /home_ldap/ahazra/workspace/boardfarm_frontend/dist/index.html
```

---

## 16. Troubleshooting — Error → Cause

| Symptom | Likely cause | Check |
|---|---|---|
| **502 Bad Gateway** | backend not running / wrong port in `proxy_pass` / app bound to `127.0.0.1` inside container | `error.log` ("connect() failed ... Connection refused"), `ss -tlnp`, `curl 127.0.0.1:PORT` |
| **504 Gateway Timeout** | backend too slow | raise `proxy_read_timeout` / `uwsgi_read_timeout` |
|03 Forbidden** on static files | `www-data` can't traverse a parent dir / read the file | `namei -l <path>`, `error.log` "Permission denied" |
| **404 on refresh** of a React route | missing `try_files ... /index.html` | config |
| **404 from FastAPI** for `/api/...` | `proxy_pass` trailing-slash mismatch vs FastAPI route prefix | 9.6, `curl 127.0.0.1:8000/api/...` |
| **Wrong site / "Welcome to nginx"** | Host didn't match any `server_name` → default server used | `nginx -T | grep -n server_name`, `sitesnabled/default` |
| **413 Request Entity Too Large** | upload larger than `client_max_body_size` | raise it in that server block |
| **CORS error in browser console** | cross-origin call without `Access-Control-Allow-*` headers | 12.4; or switch to same-origin path routing |
| **Config change has no effect** | not reloaded, or reload failed due to syntax error | `sudo nginx -t`, then reload |
| **Backend reachable from network, bypassing nginx** | Docker published on `0.0.0.0` | publish as `127.0.0.1:HOST:CONTAINER` |
| **500 on every protected request** | auth_request endpoint returned something other than 2xx/401/403 (e.g. 404 because the path is wrong) | `error.log`, `curl` the auth endpoint directly |

---

## 17. FAQ — Every Question I Asked, Answered

**Q: Why do my two servers run nginx two different ways? I didn't change anything.**
Different **packages**: server 85 has Ubuntu/Debian's nginx package, server 14 has nginx.org's. Each package ships its own unit file, default config, and service user. Csen when the machine was provisioned. Same program, same behaviour. (Sections 3–4)

**Q: Server 14 shows `-c /etc/nginx/nginx.conf`, server 85 doesn't. Different config files?**
No. Both load `/etc/nginx/nginx.conf`. Server 14's unit passes it explicitly with `-c ${CONFFILE}`; server 85 relies on the compiled-in default (`--conf-path` in `nginx -V`). (4.4)

**Q: What's `-g 'daemon on; master_process on;'`?**
Global directives given on the command line instead of in the file: run in background, use master/rker model. (4.2)

**Q: Did I install or start nginx?**
No. It's an OS service installed by the platform/provisioning, managed by systemd, auto-started at boot (`enabled`). Root master + persistent workers since the boot date is the signature of a systemd daemon. (3.4, 4.5)

**Q: Why did `ps -ef | grep nginx` on server 14 show uwsgi, celery, python?**
They run as the Linux **user** named `nginx`; grep matched the username column. They're separate Django apps, not the web server. (2.5, 10.5)

**Q: Who creates the worker processes, and why 8 here and 4 there?**
The master forks them. `worker_processes auto;` = one per CPU core: server 85 has 8 cores, server 14 has 4. (5.1–5.3)

**Q: Why does the master run as root and workers as `www-data`/`nginx`?**
Root is only needed to bind ports 80/443. Workers handle untrusted traffic, so they run as a low-privilege user for security. (5.6)

**Q: How does reload work without downtime?**
Master validates new config, starts new workers, old workers finish and exit; masterever stops. (5.7)

**Q: Why do the `nginx.conf` files differ (`www-data` vs `nginx`, `sites-enabled`, `modules-enabled`)?**
Packaging again — Debian vs nginx.org defaults. The site-specific parts live in included files. (6.4)

**Q: Is `include` like C's `#include` — copies everything into one config before starting?**
Yes. Files are pasted in place (glob expanded alphabetically), then nginx parses one big config. `sudo nginx -T` shows the result. (7)

**Q: One nginx, many `server {}` blocks with differeames — different IPs or ports?**
Neither. Same IP, same port. They're distinguished by the **`Host` header** (domain name) matched against `server_name`. That's virtual hosting. (8)

**Q: All the `*.upclabs.com` names resolve to the same IP — so what's different?**
Only the name. DNS maps every name to `10.63.69.36`; the browser puts the name in `Host` (and SNI for TLS); nginx routes by it. (8.5–8.7)

**Q: Why can several files all have `location /`?**
`location` is scoped to its own `server {}` blockx enters exactly one block per request, then matches locations only inside it. (9.1)

**Q: How does nginx pick a location?**
Exact `=` → longest prefix (`^~` stops) → regex in order → longest prefix. (9.2)

**Q: Does the browser download everything and then make separate calls with the full URL?**
Yes. It downloads `index.html`, then the JS/CSS it references; the React app then runs in the browser and makes separate `fetch` requests. A relative URL like `/api/devices/` is completed with the current oron server 14 the code uses a full URL to the API domain. Nginx routes each request by Host + path. (12)

**Q: Why does server 14 have all those `Access-Control-Allow-*` headers but server 85 doesn't?**
Server 14's frontend and API are on different domains → cross-origin → browser requires CORS headers (and sends OPTIONS preflights). Server 85 serves both from one origin → no CORS. (12.4)

**Q: Why `--host 0.0.0.0` in the container and not `localhost`?**
Docker forwards traffic to the container's `eth0not its loopback. `127.0.0.1` inside the container = unreachable; `0.0.0.0` = listen on all interfaces including `eth0`. Safe, because exposure is controlled by port mapping, firewall, nginx. (13.2–13.3)

**Q: Which port goes in `proxy_pass` when using Docker?**
The **host-side** published port (left side of `-p HOST:CONTAINER`). (13.1)

**Q: What are `internal`, `auth_request`, `location = /__whoami`?**
`internal` = location only nginx itself may use. `auth_request` = before handling a request, nginx subquests an auth URL; 2xx allows, 401/403 denies. `location = /__whoami` = the conventional exact-match, internal auth endpoint that proxies to the backend's "who is this user" check. (14)

---

*End of guide. If something new confuses me: find the box in Section 1's diagram it belongs to, then jump to that section.*

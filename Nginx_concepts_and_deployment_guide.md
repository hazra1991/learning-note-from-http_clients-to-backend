# Nginx, Linux & Deployment — The Complete Picture

> **What this is:** everything from our discussion, organised from the ground up.
> Every example is based on *real* output captured from two servers (hostnames, domains and app names anonymised):
>
> | Server | IP | Nginx package | What runs there |
> |---|---|---|---|
> | `server14` (**server 14**) | `10.63.69.36` | **nginx.org** package | Several Django apps (tool1, tool2, tool3, tool4) via uwsgi, each on its own domain |
> | `server85` (**server 85**) | `10.63.68.173` | **Ubuntu/Debian** package | My boardfarm app: React frontend + FastAPI backend, path-based routing |
>
> If I ever feel "I don't know anything about this" — read this top to bottom and I'm back.
>
> **About the server-specific parts** (the unit files, `nginx.conf` files, site configs and `ps` output in Sections 2, 4, 6, 10 and 11): they are **snapshots from October 2026**. I may not have access to these machines later, and they may have changed since, so read them as **worked examples of real setups**, not as the current state. On any machine I *do* have access to, the live truth is one command away:
> `sudo nginx -T` (full expanded config), `systemctl cat nginx` (how it's started), `ls -l /etc/nginx/conf.d /etc/nginx/sites-enabled` (which sites exist).

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
13. [Docker and `0.0.0.0`](#13-docker-and-0000)
14. [Advanced — `internal`, `auth_request`, `location = /__whoami`](#14-advanced--internal-auth_request-location--__whoami)
15. [Authentication with nginx — The Full Picture](#15-authentication-with-nginx--the-full-picture)
16. [Request vs Response — Which Directive Changes Which Message](#16-request-vs-response--which-directive-changes-which-message)
17. [Command Cheat Sheet](#17-command-cheat-sheet)
18. [Troubleshooting — Error → Cause](#18-troubleshooting--error--cause)
19. [FAQ — Every Question I Asked, Answered](#19-faq--every-question-i-asked-answered)

---

## 1. The Big Picture in One Diagram

Before any detail, here is the whole story. Everything else in this document zooms into one box of this picture.

```
 ┌──────────────┐
 │   Browser    │   user types http://10.63.68.173/  or  https://tool2-dev.example.com/
 └──────┬───────┘
        │ (1) DNS: "what IP is tool2-dev.example.com?"  → 10.63.69.36
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
nginx       1619       1  0 Oct03 ?  00:00:29 uwsgi --ini /etc/tool4_api_autodeploy/uwsgi.ini ...
nginx       1622       1  0 Oct03 ?  00:07:20 python /opt/tool1_api_autodeploy/active_deployment/src/manage.py tftpserver
nginx       1793       1  0 Oct03 ?  00:11:19 /opt/tool3/.venv/bin/python3 -m celery -A django_root worker ...
```

These are **not nginx**. They are separate apps (tool4_api, tool1_api, tool2, tool3 — uwsgi web servers, celery workers, celery beat schedulers, a tftp server) that the admin chose to run under the `nginx` service account. They match only because of the username.

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

In Docker this matters: an app inside a container must bind `0.0.0.0`, because the container's `localhost` is its own (Section 13).

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
- **Unix domain socket** — a special **file**, e.g. `/run/uwsgi/tool2_autodeploy.sock`. Only works on the same machine, slightly faster, and access is controlled by **file permissions** (that's one reason the Django apps on server 14 run as the `nginx` user — nginx can read/write their socket file).

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
tool4-api-def.conf
tool1-api-dev.conf
tool1-dev.conf
default.conf
tool2-dev.conf
tool3-dev.conf
```

What nginx effectively sees in memory:

```nginx
http {
    ...everything from nginx.conf above the include...

    ...entire contents of boardfarm-upload.conf...
    ...entire contents of tool4-api-def.conf...
    ...entire contents of tool1-api-dev.conf...
    ...entire contents of tool1-dev.conf...
    ...entire contents of default.conf...
    ...entire contents of tool2-dev.conf...
    ...entire contents of tool3-dev.conf...
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
- Files must be pasted where the directive is allowed — `conf.d` files contain `server {}`/`upstream {}` blocks because they're included **inside `http {}`**.

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

### 8.2 The `Host` header

Every HTTP request carries the domain name in a `Host` header. Real requests on the wire:

```http
GET /some/page HTTP/1.1
Host: tool1-dev.example.com
Accept: text/html
```

```http
GET /some/page HTTP/1.1
Host: tool2-dev.example.com
Accept: text/html
```

Same IP, same port, same nginx process. **Only the `Host` header differs.** The browser fills it from the URL you typed.

### 8.3 `server_name` — matching the Host header to a `server {}` block

1. Request arrives on port 443.
2. Nginx reads `Host: tool2-dev.example.com`.
3. Nginx looks at all `server {}` blocks that `listen` on 443.
4. Finds `server_name tool2-dev.example.com;` (in `tool2-dev.conf`).
5. Handles the request with **that block's** rules only.
6. A request with `Host: tool1-dev.example.com` goes to `tool1-dev.conf` instead.

**Selection order:** first by `listen` (IP:port),hen by `server_name` among those. Exact name → wildcard (`*.example.com`) → regex (`~...`) → `default_server`.

### 8.4 `default_server` — the catch-all

If no `server_name` matches, nginx uses the block marked `default_server` for that port. Server 14's `default.conf`:

```nginx
server {
    listen                  80 default_server;
    server_name             ~. "";          # regex "any char" + empty Host
    return                  308 https://$host$request_uri;   # force HTTPS
}

server {
         443 ssl default_server;
    server_name ~. "";
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.example.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.example.com.key;
    return 404;                              # unknown domain → 404
}
```

So hitting `https://10.63.69.36/` directly (Host = the IP, which no block names) → **404**. If no block is marked `default_server`, the **first** block for that port (in include order) becomes theault — a common source of "why am I seeing the wrong site?".

### 8.5 DNS — why all the names give the same IP

DNS is a phone book (name → IP). The company DNS has records like:

```
tool1-dev.example.com   A   10.63.69.36
tool2-dev.example.com   A   10.63.69.36
```

so pinging either name shows `10.63.69.36`. DNS only gets the browser to the right **machine**; nginx picks the right **app** with `server_name`. Check a name with `getent hosts <name>` or `dig +short <name>`.

### 8.6 HTTPS: SNI and theard certificate

With HTTPS, encryption is negotiated **before** the HTTP request (and its Host header) is sent. So how does nginx know which certificate to present? **SNI (Server Name Indication):** during the TLS handshake the browser sends the domain name in plain text. Nginx uses it to pick the `server {}` block/certificate.

On server 14, every block uses the **same wildcard certificate** `*.example.com` (`Public_Certificate_wildcard.example.com.cert`). One cert valid for every `xyz.example.com` → onfile shared by all sites.

### 8.7 Full flow for one request (server 14)

```
Browser wants: https://tool1-api-dev.example.com/api/something

Step 1 — DNS lookup
   Browser: "What IP is tool1-api-dev.example.com?"
   DNS:     10.63.69.36

Step 2 — TCP connection
   Browser connects to 10.63.69.36 port 443

Step 3 — TLS handshake
   Browser sends SNI = tool1-api-dev.example.com
   nginx presents the *.example.com certificate; encryption established

Step 4 — HTTP request
   GET /api/something HTTP/1.t: tool1-api-dev.example.com

Step 5 — nginx routing
   Host matches server_name in tool1-api-dev.conf
   location / → uwsgi_pass to the tool1 Django app (unix socket)

Step 6 — Response goes back the same way
```

### 8.8 Test virtual hosts without a browser

```bash
# Send a request to the IP but pretend to be a given domain (sets Host + SNI correctly)
curl -v --resolve tool2-dev.example.com:443:10.63.69.36 https://tool2-dev.example.com/

# Just override the Host header (SNI will be the IP, so add -kip cert check)
curl -vk -H "Host: tool2-dev.example.com" https://10.63.69.36/

# Plain HTTP on server 85
curl -v http://10.63.68.173/api/
```

### 8.9 Who sets the `Host` header? The client — **not** nginx

The **browser writes the `Host` header** from the URL it opens; nginx only **reads** it. Type `http://10.63.68.173/` and the browser sends `Host: 10.63.68.173` — that's why `server_name 10.63.68.173;` works on server 85. Type the hostname `server85` instead and the Host is different, nothing matchesd nginx falls back to the default server.

Because the client controls it, it can be faked (`curl -H "Host: anything" http://10.63.69.36/`) — `server_name` is for routing, never for security.

**How nginx exposes it, as variables:**

| Variable | Value for `http://10.63.68.173:8080/x` | Notes |
|---|---|---|
| `$http_host` | `10.63.68.173:8080` | the Host header **exactly as sent**, including port |
| `$host` | `10.63.68.173` | Host lowercased, **port stripped**; falls back to `server_name` if the client nt no Host |
| `$server_name` | first name in the matched block's `server_name` | from config, not from the client |
| `$proxy_host` | `127.0.0.1:8000` | host:port from the `proxy_pass` URL (see 9.9) |

### 8.10 One request lands in exactly ONE server block

Another wrong mental model: "requests can go from any block to any block." They can't. For each request nginx picks exactly one `server {}` block, in two steps:

1. **By `listen`** — which IP and port did the connection arrive on? A specific IP (`list 10.63.68.173:80`) beats the wildcard (`listen 80`, which means `0.0.0.0:80`).
2. **By `server_name`** — among the blocks that passed step 1, match the Host header. No match → that port's `default_server`.

Once chosen, the request stays inside that block; its `location` rules handle the path. Blocks never hand requests to each other. If two blocks need the same behaviour, both point at the same backend/`upstream`, or both `include` the same snippet file.

A typical layout with an IP block, a domain bloand a catch-all on the same machine and port:

```nginx
server {
    listen 80;
    server_name 10.63.68.173;            # Host: 10.63.68.173  → this block
    location / { root /srv/boardfarm/dist; try_files $uri $uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
}

server {
    listen 80;
    server_name boardfarm.example.com;   # Host: boardfarm.example.com → this block
    location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $ho}
}

server {
    listen 80 default_server;            # anything else (unknown names, bots scanning IPs)
    server_name _;                       # "_" is just a name that never matches; default_server is what makes it catch-all
    return 444;                          # nginx-special: close the connection without a response
}
```

```
GET /            Host: 10.63.68.173           → block 1 → location /     → React files
GET /api/x       Host: 10.63.68.173           → block 1 → location /api/ → /api/x       Host: boardfarm.example.com  → block 2 → location /     → FastAPI
GET /            Host: something-else         → block 3 → connection closed
```

And yes — server blocks + locations are the core of essentially every real nginx deployment. Everything in Sections 10, 11 and 14 is built from exactly these two pieces.

---

## 9. Inside a `server {}` Block — `location`, `root`, `proxy_pass`

### 9.1 Each `server {}` is an isolated world — no `location /` conflict

Several blocks all have `location /` — that's fine. `location` only means something **within** its `server {}` block.

**Analogy:** server blocks are separate buildings on the same street. Same street address (IP), different name on the door (`server_name`). Each building has a lobby (`location /`), maybe an office (`location /api/`), a storeroom (`location /static`). Two buildings both having a lobby is no conflict — you're inside one building at a time.

Nginx picks exactly **one** server block per request (by Host),n matches the path against **that block's** locations only:

```
Host: tool1-dev.example.com      Path: /  → tool1-dev.conf      → location / → static files from disk
Host: tool2-dev.example.com      Path: /  → tool2-dev.conf      → location / → uwsgi_pass tool2 Django
Host: tool1-api-dev.example.com  Path: /  → tool1-api-dev.conf  → location / → uwsgi_pass tool1 API Django
```

### 9.2 How nginx picks a `location` (the matching rules)

| Syntax | Type | Example |
|---|---|---|
| `location /path` | **exact** match only | `location = /__whoami` |
| `location ^~ /path` | prefix; if it's the longest prefix, **skip regex checks** | `location ^~ /static/` |
| `location ~ regex` | regex, case-sensitive | `location ~ \.php$` |
| `location ~* regex` | regex, case-insensitive | `location ~* \.(png|jpg)$` |
| `location /path` | plain prefix | `location /api/` |
| `location @name` | **named** — only for internal redirects | `location @login` |

**Algorithm:**
1. If an `=` exact match exists → use itop.
2. Find the **longest matching prefix** and remember it.
3. If that prefix has `^~` → use it, stop.
4. Check regex locations **in the order they appear**; first match wins.
5. No regex matched → use the remembered longest prefix.

`location /` matches **everything** (every path starts with `/`) — it's the fallback.

Note: plain prefix `location /docs` also matches `/docs/oauth2-redirect` and even `/docsXYZ`. Use `/docs/` or `= /docs` when you need to be strict.

### 9.3 `root` vs `alias` (serving from disk)

```nginx
# root: path = root + full URI
location / {
    root /var/www/app/dist;          # /assets/a.js → /var/www/app/dist/assets/a.js
}

# alias: path = alias + URI with the location prefix removed
location /static {
    alias /opt/tool2_autodeploy/active_deployment/collected_static;
    # /static/css/x.css → /opt/.../collected_static/css/x.css
}
```

Server 14 uses `alias` for Django's `/static` (collected static files) so nginx serves CSS/JS directly without bothering Django. `expires  adds caching headers (10 seconds; `expires 10m;` = 10 minutes).

### 9.4 `try_files` — the SPA fallback

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

Try in order:
1. `$uri` — a real file? (`/assets/main.js` → `dist/assets/main.js`) → serve it.
2. `$uri/` — a directory? → serve its `index`.
3. otherwise → **internally redirect** to `/index.html`.

Why: React Router handles URLs like `/devices/5` **in the browser**. There's no file `dist/devices/5` on disk. Without the fahing that page gives **404**. With it, nginx returns `index.html`, React loads, reads the URL, and shows the right page.

### 9.5 `proxy_pass` — forwarding to a backend

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;                                   # pass original Host to backend
    proxy_set_header X-Real-IP $remote_addr;                       # real client IP (backend would otherwise see 127.0.0.1)
    proxy_set_header X-Forwarded-For $proxy_add_x_forrded_for;   # chain of client/proxy IPs
}
```

Nginx opens a **new HTTP connection** to `127.0.0.1:8000`, sends the request, gets the response, sends it to the client. Nginx doesn't understand or run Python — it's a middleman.

> Why the `Host` line matters and what the backend sees with and without it → **9.9**.

Useful extra: `proxy_set_header X-Forwarded-Proto $scheme;` tells the backend whether the client used http or https.

### 9.6 ⚠️ The trailing slash rule in `proxy_pass` (very common bug)

 | Client requests | Backend receives |
|---|---|---|
| `location /api/ { proxy_pass http://127.0.0.1:8000; }` (no URI part) | `/api/devices/` | `/api/devices/` (full path kept) |
| `location /api/ { proxy_pass http://127.0.0.1:8000/; }` (with `/`) | `/api/devices/` | `/devices/` (`/api/` replaced by `/`) |

Server 85 uses the first form → **FastAPI receives `/api/devices/`, so FastAPI routes must include the `/api` prefix** (e.g. `APIRouter(prefix="/api")`).

#### 9.6.1 The rule exactly — verified agaithe official nginx docs

Source: `proxy_pass` in the official docs, http://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass. In my own words, the docs say:

- **If `proxy_pass` contains a URI** (anything after `host:port`, even a lone `/`): the part of the request path that **matched the `location`** is **replaced** by the URI written in `proxy_pass`. The rest of the path stays as it is.
- **If `proxy_pass` contains no URI** (just `http://host:port`): the request path is passed **unchanged**, exactly as the client sent it.

> ⚠️ The name "trailing slash rule" is misleading. The real question is **"does `proxy_pass` have a path after host:port or not?"** A single `/` is simply the shortest possible path.

**As a formula:**

```
proxy_pass WITHOUT a path:   sent path = original path                                   (+ ?query)
proxy_pass WITH a path:      sent path = proxy_pass path + (original path minus the location prefix)   (+ ?query)
```

So it is **not** "replace the whole thing". Only theatched prefix** is swapped out; the **remainder is glued onto** the `proxy_pass` path. It's plain text replacement.

**Worked example, step by step** — `location /api/ { proxy_pass http://127.0.0.1:8000/; }`, client requests `/api/devices/5?full=1`:

```
1. original path                 /api/devices/5          query: full=1
2. part that matched location    /api/
3. remainder                     devices/5
4. proxy_pass path               /
5. sent path = (4) + (3)         /  + devices/5   =  /devices/5
6. ery appended unchanged      /devices/5?full=1
```

That's why `devices/5` still appears: only `/api/` was replaced, the remainder was kept and attached.

**The same request against different configs:**

Client requests `/api/devices/5`:

| # | location | proxy_pass | Backend receives | Why |
|---|---|---|---|---|
| 1 | `/api/` | `http://b:8000` | `/api/devices/5` | no path → unchanged |
| 2 | `/api/` | `http://b:8000/` | `/devices/5` | `/api/` → `/`, remainder `devices/5` |
| 3 | `/api/` | `http://b:800/` | `/v2/devices/5` | `/api/` → `/v2/` |
| 4 | `/api/` | `http://b:8000/v2` | `/v2devices/5` ⚠️ | `/api/` → `/v2` (no slash!) + `devices/5` |
| 5 | `/api` | `http://b:8000/` | `//devices/5` ⚠️ | `/api` → `/`, remainder is `/devices/5` |
| 6 | `/api` | `http://b:8000` | `/api/devices/5` | no path → unchanged |

Rows 4 and 5 are the classic bugs: the replacement is literal text, so the slashes on the location and in `proxy_pass` must "line up". **Rule of thumb:** if the location ends with `/`, make the `proxy_pass` path end with `/` too.

**Exact-match locations** (`location = ...`): the whole path matched, so the whole path is replaced and there is no remainder.

```nginx
location = /__auth_qadash {
    internal;
    proxy_pass http://127.0.0.1:8000/api/auth/verify;
}
```

```
original path (the subrequest)   /__auth_qadash
matched part                     /__auth_qadash   (entire path)
remainder                        (nothing)
sent path                        /api/auth/verify + (nothing) = /api/auth/verify
```

The backend receives **`/api/auth/verify`** — not `/api/auth/verify/__auth_qadash`. The name `/__auth_qadash` is only an internal label inside nginx; the backend never sees it. (If the backend needs to know what the user originally asked for, pass it explicitly: `proxy_set_header X-Original-URI $request_uri;`.)

**Proxying another team's service under our own prefix:**

```nginx
location /integrations/qadash/ {
    proxy_pass http://10.1.1.1:8000/;
}
```

| Browser requests (our nginx| Matched prefix | Remainder | Their server receives |
|---|---|---|---|
| `/integrations/qadash/` | `/integrations/qadash/` | *(empty)* | `/` |
| `/integrations/qadash/reports/5` | `/integrations/qadash/` | `reports/5` | `/reports/5` |
| `/integrations/qadash/api/runs?id=3` | `/integrations/qadash/` | `api/runs` | `/api/runs?id=3` |

Their server has **no `/integrations/...` routes, and it needs none**. `/integrations/qadash/` is **our** prefix, used only for routing inside our nginx; the `/` in `proxy_pass` strips it before forwarding.

If we had written it **without** a path:

```nginx
proxy_pass http://10.1.1.1:8000;    # no path
```

their server would receive `/integrations/qadash/reports/5` → **404**, because that route only exists in our naming scheme.

**Choosing the form:**

| Want | Use |
|---|---|
| backend has the **same** paths as the public URL (server 85: FastAPI routes start with `/api`) | `proxy_pass http://host:port;` (no path) |
| backend's paths **don't** include our prefix (another teas service, a versioned API) | `proxy_pass http://host:port/;` or `.../v2/` (with path) |

**The documented exceptions:**

| Situation | What happens |
|---|---|
| location is a **regex** (`~`, `~*`) or a **named** location (`@x`) | nginx can't know which part "matched", so `proxy_pass` **must not** have a path — `nginx -t` fails with an `[emerg]` error if it does |
| `rewrite ... break;` changed the URI inside the location | the path in `proxy_pass` is ignored; the full rewritten URI is sent |
| `proxy_pa` contains **variables** (e.g. `http://127.0.0.1$request_uri`) | the URI is sent exactly as written after variables are filled in — no replacement logic at all |

**Verify it yourself** — use a fake backend and look at the request line it receives:

```bash
nc -l 127.0.0.1 9999        # terminal 1
```

```nginx
location /api/ { proxy_pass http://127.0.0.1:9999/; }   # try with and without the final /
```

```bash
curl http://10.63.68.173/api/devices/5     # terminal 2 (after nginx -t && reload)
# termin shows:  GET /devices/5 HTTP/1.0   (with /)   or   GET /api/devices/5 HTTP/1.0   (without)
```

**What this means for an iframe** (`<iframe src="/integrations/qadash/">`): the first page loads fine, but every file *that page* loads is requested by the browser **from our nginx**, and what happens depends on how their HTML writes paths:

| Their HTML contains | Browser requests (our nginx) | Result |
|---|---|---|
| `src="static/app.js"` (relative) | `/integrations/qadash/static/app.js` | matches our qadash location → their server gets `/static/app.js` ✅ |
| `src="/static/app.js"` (absolute) | `/static/app.js` | does **not** match `/integrations/qadash/` → lands in **our** `location /` → our React app or 404 ❌ |

Most apps use absolute paths, so proxying a whole UI under a sub-path usually breaks. Fix: give it its own **subdomain** (`server_name qadash.ourapp...; location / { proxy_pass http://10.1.1.1:8000; }`) so paths are identical on both sides, or use the app's "base path / serve from sub-path" sit has one. More in 15.8.

### 9.7 `upstream` (backend groups / simple load balancing) and `uwsgi_pass` (server 14's Django apps)

```nginx
upstream tool2 {                                  # a named group of backends
    server unix:///run/uwsgi/tool2_autodeploy.sock;   # a Unix domain socket file
}

server {
    ...
    location / {
        uwsgi_pass tool2;          # forward using the uwsgi binary protocol
        uwsgi_read_timeout 600s;      # wait up to 10 min for slow responses
        include uwsgi_params;         # standard variables uwsgi needs (REQUEST_METHOD, PATH_INFO ...)
    }
}
```

- `upstream` gives a name to one or more backend servers (can list several for load balancing).
- `uwsgi_pass` is like `proxy_pass` but speaks the **uwsgi protocol** (what the uwsgi app server expects) instead of HTTP.
- The backend is a **socket file**, not a port. This matches the `ps` output: `uwsgi --ini /etc/tool2_autodeploy/uwsgi.ini` creates that socket.

| | Server 85 (FastAPI) | Server 14 (Django) |
|---|---|---|
| App server | uvicorn | uwsgi |
| Directive | `proxy_pass` | `uwsgi_pass` |
| Protocol | HTTP | uwsgi |
| Address | `127.0.0.1:8000` (TCP) | `unix:///run/uwsgi/x.sock` (socket file) |

**`upstream` as a simple load balancer:** list several servers and nginx spreads requests across them (round-robin by default):

```nginx
upstream api_pool {
    # least_conn;                 # optional: pick the server with the fewest active connections
    server 10.0.0.11:8000;
    server 10.0.0.12:8000;
    server 10.0.0.13:8000 backup; # only used when the others are down
}

location /api/ {
    proxy_pass http://api_pool;
}
```


### 9.8 Other directives seen in the configs

| Directive | Meaning |
|---|---|
| `listen 443 ssl;` | listen on 443 with TLS |
| `ssl_certificate` / `ssl_certificate_key` | the cert and private key files |
| `charset utf-8;` | adds charset to Content-Type |
| `client_max_body_size 1M;` | max upload/request body; bigger → **413 Request Entity Too Large** |
| `return 307 https://$host$ruest_uri;` | redirect to HTTPS (307/308 keep the method, e.g. POST stays POST) |
| `add_header ... always;` | add response header even on error responses |
| `index index.html;` | file served for a directory request |

### 9.9 `proxy_set_header Host $host` — what the backend actually sees

Proxying = **two separate HTTP conversations**. nginx receives the browser's request, then sends a **new** request to the backend. Client headers (Cookie, Authorization, User-Agent, …) are copied into it — except tw nginx sets itself by default:

```nginx
proxy_set_header Host       $proxy_host;   # host:port from proxy_pass → "127.0.0.1:8000"
proxy_set_header Connection close;
```

```
Without the line                        With  proxy_set_header Host $host;
GET /api/devices HTTP/1.0               GET /api/devices HTTP/1.0
Host: 127.0.0.1:8000                    Host: 10.63.68.173
Cookie: session=abc                     Cookie: session=abc
```

(`HTTP/1.0` is nginx's proxy default before version 1.29.7, which incles Ubuntu's builds; newer versions use 1.1. Set `proxy_http_version 1.1;` when you need keepalive or WebSockets.)

**What breaks when the backend sees `127.0.0.1:8000`:**
- redirects point to `http://127.0.0.1:8000/...`, so the browser tries its own machine and fails;
- absolute links the backend generates (`url_for`, pagination, OpenAPI) are wrong;
- Django rejects the request: 400 "Invalid HTTP_HOST header" (`ALLOWED_HOSTS`) or CSRF "Origin checking failed".

**The standard set for a backend behind nginx:**

```nginx
proxy_set_header Host              $host;                       # name the user typed
proxy_set_header X-Real-IP         $remote_addr;                # real client IP (else the backend sees 127.0.0.1)
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;  # client IP + any proxies before nginx
proxy_set_header X-Forwarded-Proto $scheme;                     # "https" when nginx terminated TLS
```

- Use `$http_host` instead of `$host` if nginx listens on a non-standard port and redirects must keep that port.
- Proxying to an **external** virtual-hosted service: send *its* name, not `$host` — `proxy_set_header Host partner.example.com;` (plus `proxy_ssl_server_name on;` for HTTPS).
- `uwsgi_pass` with `include uwsgi_params;` passes Host automatically, so server 14 needs no extra line.

**⚠️ Inheritance:** `proxy_set_header` and `add_header` are inherited from `http {}` / `server {}` into a location **only if that location defines none of its own**. Define one, and all inherited ones ear for that location — which is why each location on server 85 repeats them.

To see the raw request nginx sends, point a location at `nc -l 127.0.0.1 9999` (technique in 9.6.1).

---

## 10. Server 14 Walkthrough — Every Config File Explained

Style: **one domain per app**, every app on `10.63.69.36`, HTTPS everywhere, Django apps via uwsgi sockets.

```
tool1-dev.example.com      → static frontend (HTML/CSS/JS files from disk)
tool1-api-dev.example.com  → tool1 Django API (uwsgi socket)
tool2-dev.com      → tool2 Django app (uwsgi socket)
tool3-dev.example.com       → tool3 Django app (uwsgi socket)
tool4-api-...example.com    → tool4 Django API (uwsgi socket)
anything else                 → default.conf → 404
```

### 10.1 `default.conf` — catch-all
Covered in 8.4: port 80 → redirect to HTTPS (308); port 443 with unknown Host → 404.

### 10.2 `tool1-dev.conf` — a pure static frontend

```nginx
server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_ldcard.example.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.example.com.key;

    server_name tool1-dev.example.com;
    root /opt/tool1_autodeploy/active_deployment/dist;   # built frontend (npm run build output)
    index index.html;

    charset     utf-8;
    client_max_body_size 1M;

    location / {
        expires 10m;          # browser may cache files for 10 minutes
    }
}
```

No backend at all — nginx just serves files. The JS in those files callthe **API domain** (`tool1-api-dev.example.com`).

`active_deployment` is almost certainly a **symlink** to the current release folder (deploy tool switches the link to release new versions) — check with `ls -l /opt/tool1_autodeploy/`.

### 10.3 `tool1-api-dev.conf` — API backend with CORS

```nginx
upstream tool1_api_autodeploy {
    server unix:///run/uwsgi/tool1_api_autodeploy.sock;
}

# redirect http to https
server {
  server_name             tool1-api-dev.example.com;
  listen                  80;eturn                  307 https://$host$request_uri;
}

server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.example.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privateKey_nopass_Full_Certificate_wildcard.example.com.key;

    server_name tool1-api-dev.example.com;
    charset     utf-8;
    client_max_body_size 1M;

    location /static {                      # Django admin/DRF static files served by nginx directly
        alias /opt/tool1_api_autodeploy/active_deployment/collected_static;
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
        uwsgi_pass tool1_api_autodeploy;
        uwsgi_read_timeout 600s;
        include uwsgi_params;
    }
}
```

Why the CORS headers: the frontend lives on `tool1-dev.example.com`, the API on `tool1-api-dev.example.com` → **different origins** → the browser blocks the JS from reading API responses unless the API says it's allowed tion 12.3).

(Note: `if` inside `location` is officially discouraged in nginx because it behaves surprisingly in some cases; using it only for `add_header`/`return` like here is the generally-safe use.)

### 10.4 `tool2-dev.conf` — same pattern, slightly different CORS

```nginx
upstream tool2 {
    server unix:///run/uwsgi/tool2_autodeploy.sock;
}

server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/Public_Certificate_wildcard.example.com.cert;
    ssl_certificate_key /etc/nginx/ssl/privaKey_nopass_Full_Certificate_wildcard.example.com.key;

    server_name tool2-dev.example.com;
    charset     utf-8;
    client_max_body_size 1M;

    location /static {
        alias /opt/tool2_autodeploy/active_deployment/collected_static;
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
        uwsgi_pass tool2;
        uwsgi_read_timeout 600s;
        include uwsgi_params;
    }
}
```

No port-80 block here → plain `http://tool2-dev...` falls to `default.conf`, which redirects to HTTPS anyway.

### 10.5 How the `ps` output maps to these configs

| `ps` process (user `nginx`) | What it is | Reached via |
|---|---|---|
| `uwsgi --ini /etc/tool2_autodeploy/uwsgi.ini` | tool2 web app | `/run/uwsgi/tool2_autodeploy.sock` ← `tool2-dev.conf` |
| `uwsgi --ini /etc/tool1_api_autodeploy/uwsgi.ini` | tool1 API | `/run/uwsgi/tool1_api_autodeploy.sock` â1-api-dev.conf` |
| `uwsgi --ini /etc/tool3/uwsgi.ini` | tool3 | ← `tool3-dev.conf` |
| `uwsgi --ini /etc/tool4_api_autodeploy/uwsgi.ini` | tool4 API | ← `tool4-api-def.conf` |
| `celery ... worker` | background task workers | not via nginx (talk to a queue) |
| `celery ... beat` | scheduled-task trigger | not via nginx |
| `manage.py tftpserver` | TFTP server | not via nginx (own UDP port) |

Several uwsgi lines with the same `--ini` = one uwsgi master plus its own worker children (same master/workera as nginx, see the PPID column).

---

## 11. Server 85 Walkthrough — My Boardfarm Config

Style: **one server block, path-based routing**, plain HTTP on the IP.

`/etc/nginx/sites-enabled/boardfarm`:

```nginx
server {
    listen 80;
    server_name 10.63.68.173;          # matches requests whose Host is the IP

    # React frontend — everything not matched below
    root /home_ldap/ahazra/workspace/boardfarm_frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.ht   # SPA fallback
    }

    # FastAPI — all API routes
    location /api/ {
        proxy_pass http://127.0.0.1:8000;    # no trailing slash → FastAPI receives /api/...
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Swagger docs and OpenAPI schema
    location /docs {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /redoc {
        p_pass http://127.0.0.1:8000;
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
http://10.63.68.173/docs           → FastAPI Swagger 10.63.68.173/redoc          → FastAPI ReDoc
http://10.63.68.173/openapi.json   → FastAPI schema
```

Notes:
- `server_name` can be an **IP**. If someone uses a hostname instead (e.g. `server85`), the Host won't match → nginx falls back to the `default_server` (Debian ships `sites-enabled/default` with `listen 80 default_server;` showing the "Welcome to nginx" page). Check `ls -l /etc/nginx/sites-enabled/`.
- `www-data` needs traverse permission on `/home_ldap/ahazra/...` (see 2.13).
- `127.0.0.1:8000`be where the backend is actually reachable **on the host**: uvicorn running directly on the host, or a Docker container published to host port 8000 (`-p 127.0.0.1:8000:8080`). An earlier session mentioned port 9090 — whichever it is, `proxy_pass` must point to the **host-side** port. Verify with `ss -tlnp | grep -E '8000|9090'`.

### 11.1 Server 14 vs Server 85 — two deployment styles

| | Server 14 | Server 85 |
|---|---|---|
| Routing by | **domain name** (`server_name`) | **URL path** (`location`) |
ontend URL | `https://tool1-dev.example.com/` | `http://10.63.68.173/` |
| API URL | `https://tool1-api-dev.example.com/...` | `http://10.63.68.173/api/...` |
| `server {}` blocks per app | separate for frontend and API | one for both |
| Same-origin? | **No** → CORS headers needed | **Yes** → no CORS needed |
| DNS entries needed | one per app | none (uses IP) |
| HTTPS | yes (wildcard cert) | no (plain HTTP) |

Both are valid and use exactly the same nginx mechanisms. The choice is organizational, notechnical necessity.

---

## 12. The Browser Flow — Frontend Download, Then API Calls

### 12.1 Step 1 — browser downloads `index.html`

User types `http://10.63.68.173/`:

```
Browser → nginx:   GET / HTTP/1.1
                   Host: 10.63.68.173

nginx: server_name 10.63.68.173 matches
       location / → try_files $uri $uri/ /index.html
       "/" is not a file → falls to /index.html
       reads .../boardfarm_frontend/dist/index.html from disk, sends it
```

`index.html` is a small skeleton:
!DOCTYPE html>
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

### 12.2 Step 2 — browser downloads JS and CSS

The browser sees the tags and makes **more requests**:

```
GET /assets/main-abc123.js     → location / → try_files finds dist/assets/main-abc123.js → sent
GET /assets/style-def456.css   → same → sent
```

Now the **entire React app is loaded and running ir**. Nginx's frontend job is done — it only served files. (The hash in the filename, `abc123`, changes every build so browsers never use a stale cached copy.)

From here the JavaScript takes over: every `fetch('/api/...')` it makes is a **new, separate HTTP request** to nginx (a relative URL uses the page's own origin, `http://10.63.68.173`), routed by path like any other request:

```
GET /                     → index.html        (nginx, from disk)
GET /assets/main.js       → JS bundle         (nginx disk)
GET /assets/style.css     → CSS               (nginx, from disk)
       [the app now runs in the browser]
GET /api/devices/         → JSON              (nginx → FastAPI)
POST /api/devices/5/reset → JSON              (nginx → FastAPI)
```

### 12.3 Separate domains → cross-origin → CORS headers in nginx

**Origin = scheme + host + port.** On server 14 the frontend (`https://tool1-dev.example.com`) calls the API on `https://tool1-api-dev.example.com` — a different origin. The browser then lets the JavaScript read the response only if the API answers with `Access-Control-Allow-*` headers, and for requests carrying e.g. `Authorization` or a JSON body it first sends an `OPTIONS` **preflight**. nginx can answer both (this is what server 14's configs do, 10.3):

```nginx
location / {
    if ($request_method = OPTIONS) {                  # preflight: answered by nginx, never reaches the app
        add_header Access-Control-Allow-Origin  * always;
        add_header Access-Control-Allow-Methods "GET, POST, DELETE, OPTIONS";
        add_header Access-Control-Allow-Headers "Authorization, Content-Type";
        return 204;
    }
    add_header Access-Control-Allow-Origin * always;  # actual requests
    proxy_pass http://backend;
}
```

CORS is enforced only by browsers (`curl` ignores it). If cookies must be sent cross-origin, `*` is not allowed: answer with the specific origin plus `Access-Control-Allow-Credentials: true`. Same-origin path routing (server 85: page and API both on `http://10.63.68.173`) needs no CORS at all.

---

## 13. Docker and `0.0.0.0`

An app inside a container must listen on **`0.0.0.0`**, not `127.0.0.1`: the container has its own network stack, so its `localhost` is reachable only from inside the container. Docker's port forwarding arrives on the container's own IP, and only `0.0.0.0` ("accept on every interface") lets it in. In `proxy_pass`, use the **host-side** published port (left side of `-p HOST:CONTAINER`). Details — port publishing, bypassing nginx, who manages wt — are in `docker-networking-guide.md`.

---

## 14. Advanced — `internal`, `auth_request`, `location = /__whoami`

So far every request came **from a client**. But nginx can also make requests **to itself** — internal redirects and subrequests. That's what `internal`, `auth_request`, `@named` locations and `/__whoami` are about.

### 14.1 External vs internal requests

| | External request | Internal request |
|---|---|---|
| Who starts it | the browser / curl | nginx itself |
| Visible to client? | no — happens inside nginx |
| Examples | `GET /api/devices/` | `try_files` fallback to `/index.html`, `error_page`, `auth_request` subrequest, `X-Accel-Redirect` |

I've already used one without knowing: `try_files $uri $uri/ /index.html;` — the jump to `/index.html` is an **internal redirect**. The browser asked for `/devices/5` and never learns nginx actually served `/index.html`.

### 14.2 `internal` — a location clients can't reach

```nginx
location /protected_files/ {
    internal;             only internal redirects/subrequests may use this location
    alias /srv/files/;
}
```

- Browser requests `GET /protected_files/report.pdf` directly → **404**.
- nginx itself (via `auth_request`, `error_page`, `X-Accel-Redirect`, `try_files`, `rewrite`) → allowed.

Think of it as a staff-only door inside the building: customers can't open it, staff can.

### 14.3 Named locations `@name` — always internal

```nginx
location @login {
    return 302 /login?next=$request_uri;
}
```

A named location can'ddressed by any URL at all; it's only a target for `try_files`, `error_page`, etc. Example:

```nginx
location / {
    try_files $uri @backend;      # file not found → hand off to the backend
}
location @backend {
    proxy_pass http://127.0.0.1:8000;
}
```

### 14.4 `error_page` — internal redirect on an error code

```nginx
error_page 404 /404.html;          # show a custom page (internal redirect, client still sees 404)
error_page 401 = @login;           # "=" → response code comes from @login (her redirect)
error_page 502 503 504 /maintenance.html;
```

### 14.5 `auth_request` — nginx asks "is this user allowed?" before every request

**The problem:** I want `/api/` (or the whole site) protected by login, but I don't want every backend/static location to implement auth itself.

**The idea:** before handling a request, nginx makes an **internal subrequest** to an auth endpoint. The auth endpoint's **status code** decides:

| Subrequest returns | nginx does |
|---|---|
| **2xx** (200, 204) | ✅ all continue with the original request |
| **401** or **403** | ❌ deny — returns that code to the client (can be caught with `error_page`) |
| anything else | 💥 500 Internal Server Error |

The auth endpoint's **body is ignored**; only status (and optionally headers) matter.

> Who really checks credentials, the exact phase-by-phase flow, cookies/tokens, shared secrets, roles, trust boundaries and when this design fits → **Section 15**.

### 14.6 `location = /__whoami` — the auth endpoint

```nginx
 /__whoami {
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
- The original request's headers (including **Cookie** and **Authorization**) are passed to the subrequest by default — that's how the backend sees the session.
- `proxy_pass` here **I part** (`/auth/whoami`), so the backend receives `/auth/whoami`, not `/__whoami` (trailing-URI rule, 9.6).

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
        proxy_set_header Host $host;
    }

    # ── I ──
    location /api/ {
        auth_request /__whoami;                          # 1. ask first
        auth_request_set $auth_user $upstream_http_x_user;   # 2. capture X-User header from the auth response
        proxy_set_header X-User $auth_user;              # 3. pass identity to the real backend

        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }  # ── The internal auth check ──
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

    # ── Unauthenticated → JSON 401 for the API ──
    error_page 401 = @ud;
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

### 14.8 Flow of one protected request

```
Browser:  GET /api/devices/   Cookie: session=abc
   │
   ▼
nginx: location /api/ matched → sees auth_request /__whoami
   │
   ├──► INTERNAL subrequest: GET /__whoami  (Cookie: session=abc copied along)
   │        location = /__whoami → proxy_pass → FastAPI /api/auth/whoami
   │        FastAPI: session valid → 204, X-User: ahazra
   │◄──── 204
   │
   │  2xx → allowed. auth_request_set: $auth_user = "ahazra"
   │
   ├──► proxy_pass → FastAPI /api/devices/   (X-User: ahazra)
   │◄──── 200 JSON
   ▼
Browser receives JSON.  (It never saw /__whoami.)

If the session is invalid:
   /__whoami âginx stops → error_page 401 → @unauthorized → client gets 401 JSON
   /api/devices/ backend is never even called.
```

Every protected request costs one extra subrequest. For heavy traffic you can cache auth results (`proxy_cache` keyed on the cookie) — usually unnecessary on an internal tool.

Check that the module is present (both packages normally include it):

```bash
nginx -V 2>&1 | grep -o with-http_auth_request_module
```

### 14.9 `X-Accel-Redirect` — a response header nginx understands
end response contains `X-Accel-Redirect: /some/uri`, nginx does not pass that response to the client; it performs an **internal redirect** to `/some/uri` instead. Typical use: the backend checks permissions, then lets nginx serve a protected file from an `internal` location:

```nginx
location /protected_files/ {
    internal;                 # clients can't request it directly
    alias /srv/files/;
}
# backend answers with the header:  X-Accel-Redirect: /protected_files/report.pdf
```

### 14.10 Summary of internal machinery

| Feature | Starts an internal request when... | Typical use |
|---|---|---|
| `try_files ... /index.html` | file not found | SPA routing |
| `error_page CODE target` | a response has that code | custom error pages, login redirect |
| `auth_request /x` | before every request in that location | central authentication |
| `X-Accel-Redirect` header | backend sends that header | protected downloads |
| `internal;` | — (marks a location as internal-only) | hide auth endpoints/files |
| `@me` | — (always internal) | fallback handlers |

---

## 15. Authentication with nginx — The Full Picture

Section 14 showed the *mechanics* of `auth_request`. This section answers the questions that come right after: who really authenticates, how a request flows through it exactly, what happens to cookies and tokens, whether backends need shared secrets/DBs, and when this design is right or wrong.

### 15.1 Authentication vs authorization

| | Question | Where it can live |
|---|---|---|
| **Authentica** | "Who are you? Is your session/token/login valid?" | gateway (nginx + auth service) **or** app |
| **Authorization** | "May *this* user do *this* action on *this* object?" (e.g. delete test session 42) | **the app** — it's business logic |

When an architecture diagram puts "Authentication" on the API Gateway / Load Balancer box (next to SSL termination, routing, rate limiting, load balancing), it means the first row: reject requests without valid credentials **before** they reach any backend. It's thstandard API-gateway feature list (nginx, F5, Kong, AWS API Gateway, Envoy all advertise it). It does not mean the gateway decides app permissions.

### 15.2 Who actually checks the credentials?

**With `auth_request`, nginx does NOT authenticate. It only enforces the verdict.** The auth service (Flask, FastAPI, anything — e.g. on port 9000) checks the cookie or token against LDAP or the DB and answers **2xx, 401, or 403**. Nginx just obeys the answer.

The exceptions — where **nginx itself** checks creials:

| Method | Who checks | Typical use |
|---|---|---|
| `auth_request` | an external auth service; nginx obeys its status | SSO, LDAP, sessions, JWT via a service |
| `auth_basic` | **nginx**, against a password file | quick protection for internal tools |
| mTLS (`ssl_verify_client`) | **nginx**, during TLS: client must present a cert signed by your CA | machine-to-machine, high security |
| `auth_jwt` | **nginx**, validates JWT signature/expiry — **NGINX Plus only** (commercial) | API gateways on NNX Plus |
| `allow` / `deny` | **nginx**, by client IP — access control, not identity | "only the office network" |

**`auth_basic`** — browser shows a username/password popup:

```bash
sudo apt install apache2-utils               # provides htpasswd
sudo htpasswd -c /etc/nginx/.htpasswd ahazra # -c creates the file; omit -c to add more users
```

```nginx
location /admin/ {
    auth_basic           "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8000;
    prset_header Host   $host;
    proxy_set_header X-User $remote_user;     # nginx knows the username after basic auth
}
```

(Only safe over HTTPS — basic auth sends the password base64-encoded, i.e. readable, on every request.)

**mTLS** — the client proves identity with a certificate:

```nginx
server {
    listen 443 ssl;
    ssl_certificate        /etc/nginx/ssl/server.crt;
    ssl_certificate_key    /etc/nginx/ssl/server.key;
    ssl_client_certificate /etc/nginx/ssl/company-ca.crt;   # CA that signedowed client certs
    ssl_verify_client      on;                              # no valid client cert → 400, never reaches a location

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-Client-DN $ssl_client_s_dn;      # e.g. "CN=ci-runner-01,O=Company"
    }
}
```

**`auth_jwt`** (NGINX Plus only — open-source nginx does JWT checks via `auth_request` to a small service):

```nginx
location /api/ {
    auth_jwt          "api";
    auth_jwt_key_file /etc/nginx/jwks.json; public keys to verify signatures
    proxy_set_header  X-User $jwt_claim_sub;  # claims become variables
    proxy_pass        http://127.0.0.1:8000;
}
```

**IP rules combined with a password — `satisfy any`:**

```nginx
location /internal/ {
    satisfy any;                  # pass if EITHER check passes (default is "all")
    allow 10.63.0.0/16;           # office network: no password needed
    deny  all;
    auth_basic "Restricted";      # everyone else: password
    auth_basic_user_file /etc/nginx/tpasswd;
    proxy_pass http://127.0.0.1:8000;
}
```

### 15.3 Exactly how a request flows through `auth_request` (corrected)

My first mental model, checked line by line:

| What I thought | Reality |
|---|---|
| nginx checks the Host matches, then the path matches (exact or partial), then goes inside that block | ✅ Correct — first `listen` IP:port, then `server_name`, then the best `location` (9.2) |
| "if the **first line** is `auth_request`..." | ❌ **Line order inside a location does not matter.** config is declarative; nginx processes every request in fixed **phases**. `auth_request` belongs to the *access* phase, `proxy_pass` to the *content* phase, so auth always runs first wherever it's written. It can even be written once at `server {}` level and inherited. |
| the auth URL is defined in a location in **another server block**, and since it's `internal` the host doesn't matter | ❌ **The subrequest is resolved inside the SAME server block.** `internal` means "clients can't call it", not "global Every server block that uses `auth_request /__auth` needs its own `location = /__auth` — write it once in a snippet and `include` it (example below). What *can* live anywhere is the auth **service** that location proxies to. |
| the auth location proxies to the auth server, the response comes back, nginx captures it into variables we define | ✅ Correct — `auth_request_set $var $upstream_http_<header>;` The **status code** decides allow/deny. |
| then it returns to the same place and "hits the next lihe `proxy_pass` | ⚠️ Conceptually yes — control returns to the original request, which moves on through its remaining phases (POST_ACCESS, PRECONTENT) to **CONTENT**, where `proxy_pass` runs. Not "next line". |
| it forwards the entire request with the same payload and modified headers | ✅ Correct — body untouched (it was never sent to the auth service), original headers plus whatever `proxy_set_header` adds or overrides |

**The phases, in the order nginx runs them for every request.** nginx has l phases (names as in the nginx development guide). Phases marked *(internal)* have nothing to configure:

```
 #  Phase            What runs there
 1  POST_READ        realip  (take the real client IP from a trusted proxy header)
 2  SERVER_REWRITE   rewrite / return / set / if   written at server level
 3  FIND_CONFIG      choose the location (9.2 rules)
 4  REWRITE          rewrite / return / set / if   written inside the location
 5  POST_REWRITE     (internal) re-run location search if the URI was rewritten
 6  PREACCESS        limit_req, limit_conn   (rate / connection limiting)
 7  ACCESS           allow/deny, auth_basic, auth_request, auth_jwt
 8  POST_ACCESS      (internal) applies "satisfy all | any" to the access results
 9  PRECONTENT       try_files, mirror
10  CONTENT          proxy_pass, uwsgi_pass, fastcgi_pass, static files (root/alias, index)
11  LOG              access_log
    + response filters on the way out: add_header, gzip, sub_filter, ...
```

**Where `proxy_pass` runs — an auth set has two of them:**

- `proxy_pass` in the **protected location** (to the backend) runs in phase **10 CONTENT** of the main request. `proxy_pass` doesn't execute "at its line"; it installs the location's content handler, which is why it always runs last no matter where it's written.
- `proxy_pass` in **`location = /__auth`** (to the auth service) runs in phase **10 CONTENT of the subrequest**. That subrequest is launched from phase **7 ACCESS** of the main request, and the main request waits in ACCESS until the answer arrives. (Subrequests skip the ACCESS phase themselves, so `/__auth` is never auth-checked.)

```
MAIN REQUEST  GET /api/devices
 2 SERVER_REWRITE → 3 FIND_CONFIG (location /api/) → 4 REWRITE → 6 PREACCESS
 → 7 ACCESS: auth_request /__auth ───────────────┐   main request waits here
                                                 ▼
        SUBREQUEST /__auth   (same server block)
        FIND_CONFIG (location = /__auth) → ... → 10 CONTENT: proxy_passe
                                                 │   answer: 2xx / 401 / 403
   ◄─────────────────────────────────────────────┘
   2xx → continue                401/403 → stop, send that code to the client
 → 8 POST_ACCESS → 9 PRECONTENT → 10 CONTENT: proxy_pass → backend → 11 LOG
```

**⚠️ Pitfall that follows from the phases — `return` runs BEFORE auth:**

```nginx
location /admin/ {
    arequest /__auth;
    return 200 "secret stuff";   # served to EVERYONE: return is phase 4 REWRITE, auth is phase 7 ACCESS
}
```

The same fact is *useful* for CORS: `if ($request_method = OPTIONS) { return 204; }` answers preflights before auth — correct, since preflights never carry credentials.

**The refined flow, step by step:**

```
Request:  GET /sessions/42   Host: gw.example.com   Cookie: session=abc

 ① Server selection     listen 443 + server_name gw.example.com      → server block "gw"
 ②n selection   longest prefix /sessions/                     → location /sessions/
 ③ Rewrite phase        no return/rewrite here                        → continue
 ④ Access phase         auth_request /__auth
      ├─ nginx creates an INTERNAL SUBREQUEST to /__auth
      │    resolved in the SAME server block → location = /__auth { internal; ... }
      │    it carries the original headers (Cookie, Authorization) but no body
      ├─ that location proxy_passes to the auth service (http:.2.50:9000/verify)
      ├─ auth service checks session=abc against LDAP/DB
      │    → 204   X-User: ahazra   X-Roles: qa,admin
      ├─ nginx reads the STATUS: 2xx → allowed   (401/403 → stop & deny; other → 500)
      └─ auth_request_set copies X-User / X-Roles into $user / $roles
 ⑤ Content phase        proxy_pass http://compute2:8001
      └─ new request to the backend: same method, path, body, client headers
         + proxy_set_header X-User $user, X-Roles $roles
 ⑥ Res    backend 200 JSON → nginx → browser
                        (the browser never sees /__auth or the auth service)
```

The complete config for that flow, shared across several server blocks:

```nginx
# /etc/nginx/snippets/auth.conf   — written once
location = /__auth {
    internal;
    proxy_pass http://10.7.2.50:9000/verify;        # auth service, can be on another host
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI    $request_uri;   auth service otherwise only sees "/verify"
    proxy_set_header X-Original-Method $request_method;
}
```

```nginx
server {
    listen 443 ssl;
    server_name gw.example.com;
    # ssl_certificate ... ;

    include snippets/auth.conf;                     # pasted here → location = /__auth exists in THIS block

    location /sessions/ {
        auth_request /__auth;
        auth_request_set $user  $upstream_http_x_user;
        auth_request_set $roles $upstream_http_x_roles;
        proxy_set_header Host  $host;
        proxy_set_header X-User  $user;
        proxy_set_header X-Roles $roles;
        proxy_pass http://compute2:8001;
    }

    location /tools/ {
        auth_request /__auth;
        auth_request_set $user  $upstream_http_x_user;
        auth_request_set $roles $upstream_http_x_roles;
        proxy_set_header Host    $host;
        proxy_set_header X-User  $user;
        proxy_set_header X-Roles $roles;
        proxy_pass http://compute2:8002;
    }
}

server {
    listen 443 ssl;
    server_name ai.example.com;
    include snippets/auth.conf;                     # needed AGAIN — different server block
    location / {
        auth_request /__auth;
        auth_request_set $user $upstream_http_x_user;
        proxy_set_header Host   $host;
        proxy_set_header X-User $user;
        proxy_pass http://ai-backend:8000;
    }
}
```

**It runs on every request.** nginx keeps no memory between requests: every request to a protected location triggers its own auth subrequest (unless you add cachg, 15.5).

### 15.4 Can the auth service set cookies or issue tokens?

Not by itself: the auth subrequest's **body is discarded** and its **headers never reach the browser**. So if `/verify` returns a refreshed session cookie, the browser never gets it — unless you forward it by hand (messages shown in Section 16):

```nginx
location /api/ {
    auth_request /__auth;
    auth_request_set $new_cookie $upstream_http_set_cookie;   # capture from the AUTH response
    add_header Set-Cookie $new_cookie always;                # put it on the response to the BROWSER
    proxy_pass http://127.0.0.1:8000;
}
```

Forward one cookie only (several `Set-Cookie` headers through one variable is unreliable), and remember `add_header` inheritance (9.9). Login, refresh and logout don't need this trick — make them ordinary public locations so their `Set-Cookie` reaches the browser normally:

```nginx
location /auth/ {                      # login / refresh / logout — public, NOT behind auth_request
    proxy_pass http://1.0.1:9000;
    proxy_set_header Host $host;
}
```

### 15.5 Caching auth results

Every protected request costs one auth subrequest — usually a fast local call. If it matters, nginx can cache the verdict per credential:

```nginx
# in http {}
proxy_cache_path /var/cache/nginx/auth levels=1 keys_zone=authcache:10m max_size=50m inactive=10m;

location = /__auth {
    internal;
    proxy_pass http://127.0.0.1:9000/auth/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";

    proxcache           authcache;
    proxy_cache_key       "$http_authorization$cookie_session";  # one cache entry per credential
    proxy_cache_valid     200 204 30s;                           # remember "allowed" for 30s
    proxy_ignore_headers  Cache-Control Expires;                 # cache even if the auth service says no-cache
}
```

Trade-off: a cached "allowed" can outlive a logout by up to 30 s. Responses carrying `Set-Cookie` aren't cached by default.

### 15.6 The trust boundary — the part that mak or breaks gateway auth

Backends trust `X-User` blindly. That is only safe if **nothing except nginx can reach them.**

**⚠️ Pitfall 1 — bypassing nginx:** if `10.7.2.48:8001` is reachable from the network, anyone can call it directly with `X-User: admin`. Ways to close it (pick at least one):

| Option | How |
|---|---|
| Same machine, loopback | backend binds `127.0.0.1` (or Docker `-p 127.0.0.1:8001:8000`) — simplest |
| Private network + firewall | backends on another host, firewall allows onlyeway's IP |
| Docker internal network | backends have no published ports; nginx container on the same network |
| Shared secret header | nginx adds `proxy_set_header X-Gateway-Token "<long random>";`, backend rejects requests without it |
| mTLS gateway → backend | `proxy_ssl_certificate` on nginx; backend requires that client cert |

So backends do **not** have to be on the same machine — they have to be **unreachable except via the gateway**. Loopback is just the easiest way to guarantee that.

**⚠ï 2 — client-supplied identity headers:** a client can send `X-User: admin` *to nginx*.
- In a protected location, `proxy_set_header X-User $user;` **replaces** whatever the client sent — safe.
- In a location **without** `auth_request` that proxies to the same backend, the client's header passes straight through! Blank it explicitly:

```nginx
location /public/ {
    proxy_set_header X-User  "";      # empty value = header not sent upstream
    proxy_set_header X-Roles "";
    proxy_pass http://127.0.8001;
}
```

The backend can additionally reject requests that lack the gateway secret header (code in `integration-implementation-guide.md`).

**⚠️ Pitfall 3 — `return` in a protected location skips auth** (15.3).

### 15.7 When gateway auth fits — and when it doesn't

Gateway auth answers one question centrally — *"is this a valid, logged-in user?"* — for **many services sharing one user base**. It is not a replacement for an application's own login.

| Situation | Authentication lives in |
|-ny internal services, same users | gateway / central identity provider; each app keeps its own permissions |
| One self-contained product (UI + backend) | the app; nginx only does TLS and routing |
| A product deployed for many customers | the app, optionally with a "trust the proxy's user header" mode for customers who run an SSO gateway |
| External systems calling your API | standard API keys / OAuth tokens checked by the app — never gateway headers |

Both styles can sit behind the same nginx:

```ngi
# Internal tools: nginx does the coarse check, the app decides permissions
location /tools/ {
    auth_request /__auth;                         # "is this a logged-in user?"
    auth_request_set $user $upstream_http_x_user;
    proxy_set_header X-User $user;
    proxy_pass http://tools-backend:8000;
}

# Self-contained product: nginx only routes, the app runs its own login
location /product/ {
    proxy_pass http://product-backend:8000;
    proxy_set_header Host $host;
}
```

Defense in depth is common: the gateway rejects unauthenticated traffic early, and the app still validates and authorizes. Design discussion (BFF, multi-customer products, proxy-auth modes) is in `integration-implementation-guide.md`.

### 15.8 External services behind nginx

**The rule:** nginx can only modify requests whose URL points at nginx. If the browser calls `https://partner.example.com/...` directly (a `fetch` or an `<iframe src>`), your nginx never sees it and can't add credentials. To add credentials, route the call through your nginx.

**Inject the partner's credential at the gateway** — the browser never sees the key:

```nginx
location /partner/ {
    auth_request /__auth;                                 # caller must be logged in with us
    proxy_pass https://partner.example.com/;              # path "/" strips /partner/ (9.6.1)
    proxy_set_header Host partner.example.com;            # the partner's name, not $host (9.9)
    proxy_ssl_server_name on;                             # send SNI to the partner's HTTPS server   proxy_set_header Authorization "Bearer <partner-api-key>";
    proxy_set_header Cookie "";                           # don't leak our session cookie
    proxy_set_header X-User "";
}
```

`GET /partner/v1/items` → the partner receives `GET /v1/items` with the key. It's **one** browser request; the auth subrequest and the forward both happen inside it (15.3). To pick the key per user or role, let the auth service return it in a header and inject that instead:

```nginx
auth_request_set $ext_token $upstrm_http_x_ext_token;
proxy_set_header Authorization "Bearer $ext_token";
```

Limits: the partner sees every call as one service account, the secret lives in nginx config (or the auth service), and there's no reshaping or error handling. When you need logic, call the partner from your **backend** instead: `browser → nginx → your backend → partner`.

**Iframes:** an iframe pointing at the partner's domain loads directly from them, so their app must handle login (SSO or an embed token). To run it throughnginx, give it its own **subdomain** rather than a sub-path, because absolute asset paths break under a prefix (9.6.1):

```nginx
server {
    listen 443 ssl;
    server_name partner.ourapp.example.com;
    include snippets/auth.conf;                 # location = /__auth must exist in this block
    location / {
        auth_request /__auth;
        proxy_pass http://10.0.0.20:8000;       # no path: identical paths on both sides
        proxy_set_header Host 10.0.0.20;
        proxy_set_header X-API-Key "<partner-key>";
    }
}
```

**Keep gateway headers internal:** `X-User` / `X-Roles` are a contract inside your own deployment. Partners calling *your* API get standard API keys or OAuth tokens.

Step-by-step implementation (backend verify endpoint, embed tokens, SSO, choosing between them) is in `integration-implementation-guide.md`.

### 15.9 Pitfalls checklist

| ✔ | Check |
|---|---|
| ☐ | Backends unreachable except through nginx (loopback / firewall / internal network / gateway secret / mTLS) |
| ântity headers blanked (`proxy_set_header X-User "";`) in every non-protected location that proxies to those backends |
| ☐ | No `return` inside protected locations (it runs before auth) |
| ☐ | `location = /__auth` exists (via `include`) in **every** server block that uses `auth_request` |
| ☐ | `/auth/login`, `/auth/refresh`, `/auth/logout` are public, normal locations — not behind `auth_request` |
| ☐ | Auth endpoint returns only 2xx / 401 / 403 (anything else = 500 for the user) |
| ☐ | `Setm the auth subrequest is forwarded only if intended (`auth_request_set` + `add_header ... always`) |
| ☐ | Locations re-declare all needed `proxy_set_header` / `add_header` (inheritance is all-or-nothing) |
| ☐ | Session cookies `HttpOnly`; `Secure` only works over HTTPS; `Domain=` set if subdomains must share the login |
| ☐ | Cross-origin + cookies → specific origin + `Access-Control-Allow-Credentials: true` (never `*`) |
| ☐ | Authorization (who may do what) stays in each app |
| ☐ | Externals use standard credentials; gateway headers stay internal |

---

## 16. Request vs Response — Which Directive Changes Which Message

A proxied request is not one message but **four**, and each has its own headers. Almost every header question ("does the backend see this?", "does the browser get this?") is answered by asking **which of the four messages** a directive touches.

### 16.1 The four messages and nginx's defaults

```
            ① request                    ② request (a NEW one)
 Browser â───────►   nginx   ───────────────►   Backend
         ◄───────────────           ◄───────────────
            ④ response                   ③ response
```

| Message | What nginx does by default |
|---|---|
| ① browser → nginx | reads it; headers available as variables (`$http_*`, `$cookie_*`) |
| ② nginx → backend | builds a **new** request: client headers copied, except `Host` (seost`) and `Connection` (set to `close`) — see 9.9 |
| ③ backend → nginx | reads it; headers available as `$upstream_http_*` |
| ④ nginx → browser | backend headers copied, except `Date`, `Server`, `X-Pad` and `X-Accel-*`, which nginx does not pass on |

With `auth_request` there are two extra messages — the internal subrequest to the auth service and its response. Their headers go **nowhere** unless you capture them (16.5).

### 16.2 `Cookie` vs `Set-Cookie`

| Header | Travels in | Direction | --|---|---|---|
| `Cookie: session=abc` | a **request** (① → ②) | browser → server | "here is the cookie I already have" |
| `Set-Cookie: session=new` | a **response** (③ → ④) | server → browser | "please store this cookie" |

- Both pass through nginx automatically: the browser's `Cookie` is copied into ②, a backend's `Set-Cookie` is copied into ④.
- Only browsers store cookies, so `Set-Cookie` only makes sense on a response **going to the browser**.
- Cookies are scoped by **domain + p not port**; `Domain=.example.com` shares one across subdomains; `Secure` cookies are only stored over HTTPS (so not on plain-http server 85).
- The browser only ever sees ① and ④. A cookie set "by the auth service" or "by the backend" is, to the browser, simply a cookie from the host in the URL bar.

### 16.3 Which directive changes which message

| Message | Directive | Effect |
|---|---|---|
| ② to backend | `proxy_set_header Name value;` | add or override a header; an empty value removes it |
| ây_pass_request_headers off;` | send none of the client's headers |
| ② | `proxy_pass_request_body off;` | send no body (typical for auth subrequests) |
| ④ to browser | `add_header Name value [always];` | add a header — only on 2xx/3xx responses unless `always` |
| ④ | `proxy_hide_header Name;` | drop a header the backend sent |
| ④ | `proxy_pass_header Name;` | let through a header nginx normally drops (e.g. `Server`) |
| ④ | `proxy_cookie_path` / `proxy_cookie_domain` / `proxy_cookie_flags` |ributes of the backend's `Set-Cookie` (16.6) |
| ④ | `proxy_redirect` | rewrite the backend's `Location` header |
| ④ | `expires` | add `Expires` / `Cache-Control` |
| *(none)* | `auth_request_set $var $upstream_http_name;` | copy a header of the **auth** response into a variable, to use in ② or ④ |

⚠️ `proxy_set_header` and `add_header` inherit into a location only if it defines none of its own (9.9).

### 16.4 Reading headers as variables

| Variable | Reads | Example |
|---|---|---|
| `$http header of the client request ① | `$http_authorization`, `$http_user_agent` |
| `$cookie_<name>` | one cookie from ① | `$cookie_session` |
| `$upstream_http_<name>` | a header of the backend / auth response ③ | `$upstream_http_x_user` |
| `$sent_http_<name>` | a header of the response sent to the client ④ | `$sent_http_content_type` |

Header names become lowercase with `-` turned into `_`: `X-User` → `x_user`, `Set-Cookie` → `set_cookie`.

### 16.5 Worked example — a refreshed cookie through 

Message numbers here count every hop, including the auth subrequest (② ③), so the backend messages are ④ ⑤ and the browser response is ⑥.


```nginx
location /api/ {
    auth_request /__auth;
    auth_request_set $auth_cookie $upstream_http_set_cookie;   # capture Set-Cookie from the AUTH response
    add_header Set-Cookie $auth_cookie always;                 # attach it to the response going to the BROWSER
    proxy_pass http://127.0.0.1:8001;
}

location = /__auth {
    internal;
    proxy_pas0.12.3.4/something/auth;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
}
```

```
Browser                    nginx                     Auth (/__auth)          Backend (8001)
   │ ① REQUEST               │                            │                       │
   │ GET /api/devices        │                            │                       │
   │ Cookie: session=old     │                            │                       │
   │──────────►│ ② REQUEST (internal)       │                       │
   │                         │ Cookie: session=old        │                       │
   │                         │───────────────────────────►│                       │
   │                         │ ③ RESPONSE  204            │                       │
   │                         │ Set-Cookie: session=new    │                       │
   │                 │◄───────────────────────────│                       │
   │                         │ auth_request_set → $auth_cookie = "session=new"    │
   │                         │                                                    │
   │                         │ ④ REQUEST  GET /api/devices                        │
   │                         │ Cookie: session=old   (NO Set-Cookie here)         │
   │                   ──────────────────────────────────────────────►│
   │                         │ ⑤ RESPONSE  200 JSON  (knows nothing of new cookie)│
   │                         │◄───────────────────────────────────────────────────│
   │ ⑥ RESPONSE  200 JSON    │                                             │ Set-Cookie: session=new │ ← added by add_header from $auth_cookie            │
   │◄────────────────────────│                                                    │
 browser stores session=new; the next request sends Cookie: session=new
```

- The backend never sees the new cookie: ④ carries only the browser's `Cookie`, and ⑤ doesn't contain it.
- nginx carries it in `$auth_cookie` for this one request; `add_header` attaches it to ⑥. Withdd_header` it is dropped; if the auth service sends none, nothing is added.
- `/__auth` runs on **every** request. On 401 the backend is never called and the browser gets the 401 (the UI then sends the user to login).

### 16.6 Rewriting a backend's cookies

When an app is proxied under a different path or name, the cookies it sets may be scoped wrong for the browser. nginx can fix the `Set-Cookie` attributes on the way out (④):

```nginx
location /app/ {
    proxy_pass http://10.0.0.20:8000/;            the app thinks it lives at /
    proxy_cookie_path   / /app/;                  # its "Path=/..." cookies become "Path=/app/..."
    proxy_cookie_domain 10.0.0.20 $host;          # "Domain=10.0.0.20" → the name the browser used
    proxy_cookie_flags  ~ httponly samesite=lax;  # add flags to all its cookies (nginx ≥ 1.19.3)
}
```


---

## 17. Command Cheat Sheet

### Phases at a glance

| # | Phase | Typical directives |
|---|---|---|
| 1 | POST_READ | realip (`set_real_ip_from`, `real_ip_header`) |
| 2ERVER_REWRITE | `return`, `rewrite`, `set`, `if` at server level |
| 3 | FIND_CONFIG | `location` matching; `internal` check |
| 4 | REWRITE | `return`, `rewrite`, `set`, `if` inside the location |
| 5 | POST_REWRITE | *(internal)* re-run location search after a rewrite |
| 6 | PREACCESS | `limit_req`, `limit_conn` |
| 7 | ACCESS | `allow` / `deny`, `auth_basic`, `auth_request`, `auth_jwt` |
| 8 | POST_ACCESS | *(internal)* applies `satisfy` |
| 9 | PRECONTENT | `try_files`, `mirror` |
| 10 | CONTENT | `proxy_pass`, `uwsgi_pass`, `fastcgi_pass`, static files |
| 11 | LOG | `access_log` |

Consequences: `return` (2/4) runs **before** auth (7); `proxy_pass` (10) always runs **last**, whatever its line position. Details in 15.3.

### Directives at a glance — what it does, when it runs

**Routing and structure**

| Directive | What it does | When |
|---|---|---|
| `listen` | IP:port a server block accepts (`default_server`, `ssl`) | server selection |
| `server_name` | names matched against the `Host` header | rver selection |
| `location` | path match inside a server block | 3 FIND_CONFIG |
| `internal` | location only nginx itself may use (clients get 404) | 3 FIND_CONFIG |
| `include` | paste other files into the config | config load |
| `upstream` | named group of backends (simple load balancing) | config; used by `*_pass` in 10 |

**Rewrite**

| Directive | What it does | When |
|---|---|---|
| `return` | answer immediately: status, text or redirect | 2 / 4 REWRITE |
| `rewrite` | change the URI with a regex | 2 / 4 REWRITE |
| `set` | set a variable | 2 / 4 REWRITE |
| `if` | conditional block (keep it to `return` / `set` / `add_header`) | 2 / 4 REWRITE |

**Limits and access**

| Directive | What it does | When |
|---|---|---|
| `limit_req` / `limit_conn` | rate / connection limits (zones defined in `http` via `limit_req_zone` / `limit_conn_zone`) | 6 PREACCESS |
| `allow` / `deny` | IP-based access control | 7 ACCESS |
| `auth_basic` + `auth_basic_user_file` | username/password check by nginx | 7 ACCESS |
| `auth_request` | subrequest to an auth endpoint; 2xx allow, 401/403 deny | 7 ACCESS |
| `auth_request_set` | copy a header of the auth response into a variable | 7 ACCESS (when the subrequest finishes) |
| `satisfy any \| all` | combine the access checks | 8 POST_ACCESS |
| `client_max_body_size` | max request body; larger → 413 | after location selection |

**Files and content**

| Directive | What it does | When |
|---|---|---|
| `try_files` | try files in order, else fallback (internal redirect or cod | 9 PRECONTENT |
| `root` / `alias` | map the URI to a filesystem path | used in 9–10 |
| `index` | file served for a directory request | 10 CONTENT |
| `proxy_pass` | forward to an HTTP backend | 10 CONTENT |
| `uwsgi_pass` / `fastcgi_pass` | forward using the uwsgi / FastCGI protocol | 10 CONTENT |

**Shaping the request to the backend (②)** — applied when `proxy_pass` builds the request, phase 10

| Directive | What it does |
|---|---|
| `proxy_set_header` | add / override / remove (empty value) ar sent to the backend |
| `proxy_pass_request_body` / `proxy_pass_request_headers` | send the client's body / headers, or not |
| `proxy_http_version` | HTTP version to the backend (1.1 for keepalive and WebSockets) |
| `proxy_connect_timeout` / `proxy_read_timeout` | backend timeouts (504 when exceeded) |
| `proxy_ssl_server_name` | send SNI to an HTTPS backend |
| `proxy_cache` (+ `proxy_cache_path`, `proxy_cache_key`, `proxy_cache_valid`) | cache backend responses |

**Shaping the response to the browser (④)** — applied as the response goes out

| Directive | What it does |
|---|---|
| `add_header` | add a response header (2xx/3xx only, unless `always`) |
| `proxy_hide_header` / `proxy_pass_header` | drop / allow a header from the backend |
| `proxy_cookie_path` / `proxy_cookie_domain` / `proxy_cookie_flags` | rewrite the backend's `Set-Cookie` attributes |
| `proxy_redirect` | rewrite the backend's `Location` header |
| `expires` | caching headers |
| `gzip` | compress the response |

**Errors and intl redirects**

| Directive | What it does | When |
|---|---|---|
| `error_page` | on a status code, internal redirect to a URI or `@name` | whenever that code is produced |
| `X-Accel-Redirect` *(backend response header)* | backend asks nginx for an internal redirect | after the backend responds |

**Global, TLS and logging**

| Directive | What it does | When |
|---|---|---|
| `user`, `worker_processes`, `worker_connections`, `pid` | process model | startup |
| `ssl_certificate` / `ssl_certificate_key` / `ssl_verify_client` | server cert / client-cert check | TLS handshake, before HTTP |
| `sendfile`, `keepalive_timeout` | connection / file-sending behaviour | connection handling |
| `access_log` / `log_format` | request log and its format | 11 LOG |
| `error_log` | error log | any time |


### Processes & service

```bash
systemctl status nginx              # is it running, since when, master + workers (CGroup)
systemctl cat nginx                 # unit file in effect (incl. overrides)
cat /usr/lib/systemd/system/nginx.service
systemctl is-enabled nginx          # starts at boot?
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

### Package / ild

```bash
nginx -v ; nginx -V 2>&1 | tr ' ' '\n'
apt-cache policy nginx
dpkg -S /usr/lib/systemd/system/nginx.service
```

### Network

```bash
ip addr                             # my interfaces and IPs
ss -tlnp                            # who listens on which address:port
sudo ss -tlnp | grep nginx
getent hosts tool2-dev.example.com
dig +short tool2-dev.example.com
curl -v http://10.63.68.173/api/
curl -v --resolve tool2-dev.example.com:443:10.63.69.36 https://tool2-dev.example.com/
curl -vk -H "Host: tool2-dev.example.com" https://10.63.69.36/
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

## 18. Troubleshooting — Error → Cause

| Symptom | Likely cause | Check |
|---|---|---|
| **502 Bad Gateway** | backend not running / wrong port in `proxy_pass` / app bound to `127.0.0.1` inside container | `error.log` ("connect() failed ... Connection refused"), `ss -tlnp`, `curl 127.0.0.1:PORT` |
| **504 Gateway Timeout** | backend too slow | raise `proxy_read_timeout` / `uwsead_timeout` |
| **403 Forbidden** on static files | `www-data` can't traverse a parent dir / read the file | `namei -l <path>`, `error.log` "Permission denied" |
| **404 on refresh** of a React route | missing `try_files ... /index.html` | config |
| **404 from FastAPI** for `/api/...` | `proxy_pass` trailing-slash mismatch vs FastAPI route prefix | 9.6, `curl 127.0.0.1:8000/api/...` |
| **Wrong site / "Welcome to nginx"** | Host didn't match any `server_name` → default server used | `nginx -T | grep -n rver_name`, `sites-enabled/default` |
| **413 Request Entity Too Large** | upload larger than `client_max_body_size` | raise it in that server block |
| **CORS error in browser console** | cross-origin call without `Access-Control-Allow-*` headers | 12.3; or switch to same-origin path routing |
| **Config change has no effect** | not reloaded, or reload failed due to syntax error | `sudo nginx -t`, then reload |
| **Backend reachable from network, bypassing nginx** | Docker published on `0.0.0.0` | publish as `127.0.0.1:HOST:CONTAINER` |
| **500 on every protected request** | auth_request endpoint returned something other than 2xx/401/403 (e.g. 404 because the path is wrong) | `error.log`, `curl` the auth endpoint directly |
| **400 Bad Request / "Invalid HTTP_HOST header"** (Django) | Host sent to backend not in `ALLOWED_HOSTS` (often missing `proxy_set_header Host $host;`) | 9.9 |
| **Redirect sends browser to `127.0.0.1:8000`** | backend saw `Host: 127.0.0.1:8000` | add `proxy_set_header Host $host;` (9.9) |
| **CSRF "Origin checking failed"** | Host / `X-Forwarded-Proto` don't match what the browser used | 9.9 |
| **Protected location served without login** | `return` inside it (runs before auth), or identity header passed through from client | 15.3, 15.6 |
| **Cookie from auth service never reaches browser** | subrequest headers are dropped | `auth_request_set` + `add_header ... always`, or make login a normal endpoint (15.4) |
| **Session cookie not stored on server 85** | `Secure` cookie over plain HTTP | 16.2 |
| **Security headers disappear in one location** | `add_header`/`proxy_set_header` inheritance is all-or-nothing | 9.9, 15.4 |

---

## 19. FAQ — Every Question I Asked, Answered

**Q: Why do my two servers run nginx two different ways? I didn't change anything.**
Different **packages**: server 85 has Ubuntu/Debian's nginx package, server 14 has nginx.org's. Each package ships its own unit file, default config, and service user. Chosen when the machine was provisioned. Same program, same behaviou (Sections 3–4)

**Q: Server 14 shows `-c /etc/nginx/nginx.conf`, server 85 doesn't. Different config files?**
No. Both load `/etc/nginx/nginx.conf`. Server 14's unit passes it explicitly with `-c ${CONFFILE}`; server 85 relies on the compiled-in default (`--conf-path` in `nginx -V`). (4.4)

**Q: What's `-g 'daemon on; master_process on;'`?**
Global directives given on the command line instead of in the file: run in background, use master/worker model. (4.2)

**Q: Did I install or start nginx?**
No. It's  OS service installed by the platform/provisioning, managed by systemd, auto-started at boot (`enabled`). Root master + persistent workers since the boot date is the signature of a systemd daemon. (3.4, 4.5)

**Q: Why did `ps -ef | grep nginx` on server 14 show uwsgi, celery, python?**
They run as the Linux **user** named `nginx`; grep matched the username column. They're separate Django apps, not the web server. (2.5, 10.5)

**Q: Who creates the worker processes, and why 8 here and 4 there?**
The master forks them. `worker_processes auto;` = one per CPU core: server 85 has 8 cores, server 14 has 4. (5.1–5.3)

**Q: Why does the master run as root and workers as `www-data`/`nginx`?**
Root is only needed to bind ports 80/443. Workers handle untrusted traffic, so they run as a low-privilege user for security. (5.6)

**Q: How does reload work without downtime?**
Master validates new config, starts new workers, old workers finish and exit; master never stops. (5.7)

**Q: Why do the `nginx.conf` files differ (`wwdata` vs `nginx`, `sites-enabled`, `modules-enabled`)?**
Packaging again — Debian vs nginx.org defaults. The site-specific parts live in included files. (6.4)

**Q: Is `include` like C's `#include` — copies everything into one config before starting?**
Yes. Files are pasted in place (glob expanded alphabetically), then nginx parses one big config. `sudo nginx -T` shows the result. (7)

**Q: One nginx, many `server {}` blocks with different names — different IPs or ports?**
Neither. Same IP, same port.re distinguished by the **`Host` header** (domain name) matched against `server_name`. That's virtual hosting. (8)

**Q: All the `*.example.com` names resolve to the same IP — so what's different?**
Only the name. DNS maps every name to `10.63.69.36`; the browser puts the name in `Host` (and SNI for TLS); nginx routes by it. (8.5–8.7)

**Q: Why can several files all have `location /`?**
`location` is scoped to its own `server {}` block. Nginx enters exactly one block per request, then matches locations  inside it. (9.1)

**Q: How does nginx pick a location?**
Exact `=` → longest prefix (`^~` stops) → regex in order → longest prefix. (9.2)

**Q: Does the browser download everything and then make separate calls with the full URL?**
Yes. It downloads `index.html`, then the JS/CSS it references; the React app then runs in the browser and makes separate `fetch` requests. A relative URL like `/api/devices/` is completed with the current origin; on server 14 the code uses a full URL to the API domain. Ngines each request by Host + path. (12)

**Q: Why does server 14 have all those `Access-Control-Allow-*` headers but server 85 doesn't?**
Server 14's frontend and API are on different domains → cross-origin → browser requires CORS headers (and sends OPTIONS preflights). Server 85 serves both from one origin → no CORS. (12.3)

**Q: Why `--host 0.0.0.0` in the container and not `localhost`?**
Docker forwards traffic to the container's `eth0` IP, not its loopback. `127.0.0.1` inside the container = unreacha0.0.0.0` = listen on all interfaces including `eth0`. Safe, because exposure is controlled by port mapping, firewall, nginx. (Section 13, `docker-networking-guide.md`)

**Q: Which port goes in `proxy_pass` when using Docker?**
The **host-side** published port (left side of `-p HOST:CONTAINER`). (Section 13, `docker-networking-guide.md`)

**Q: What are `internal`, `auth_request`, `location = /__whoami`?**
`internal` = location only nginx itself may use. `auth_request` = before handling a request, nginx subrequests an auth URL; 2xx allows, 401/403 denies. `location = /__whoami` = the conventional exact-match, internal auth endpoint that proxies to the backend's "who is this user" check. (14)

**Q: Who sets the `Host` header — is it a fixed header from nginx?**
The **client** sets it, from the URL that was typed/requested. Nginx only reads it (`$host`, `$http_host`). It can be faked with `curl -H`, so it's for routing, not security. (8.9)

**Q: Can a request move from one server block to another?**
No. Each reest lands in exactly one block (by `listen`, then `server_name`), and stays there. Share behaviour via the same upstream or an `include`d snippet. (8.10)

**Q: Why `proxy_set_header Host $host;` — what happens without it?**
Proxying is a second, new HTTP request. By default nginx sets its Host to the `proxy_pass` address (`127.0.0.1:8000`), so the backend generates wrong redirects/links, and Django may reject it (ALLOWED_HOSTS, CSRF). The line copies the user's real Host. (9.9)

**Q: Is "Authentication" oan nginx/API-gateway box valid, or nonsense?**
Valid and common — it means "reject requests without valid credentials before they reach any backend". Authorization (who may do what) stays in the app. (15.1)

**Q: Does nginx itself authenticate with `auth_request`?**
No — it only enforces the verdict (2xx allow, 401/403 deny) from an auth service. nginx checks credentials itself only with `auth_basic`, mTLS, and `auth_jwt` (NGINX Plus). (15.2)

**Q: Does the `/__auth` location have to be in the same servlock?**
Yes — the subrequest is resolved in the same block; `internal` doesn't make it global. Put it in a snippet and `include` it in each block. The auth *service* can be anywhere. (15.3)

**Q: Does the order of lines (auth_request first, proxy_pass after) matter?**
No — nginx runs fixed phases; access (auth) always precedes content (proxy_pass). But `return` runs *before* auth, so it bypasses it. (15.3)

**Q: Can the auth service set a cookie / issue a token via `auth_request`?**
Not by default: the equest's body is discarded and its headers don't reach the browser. You can forward one header manually with `auth_request_set` + `add_header`. Normally login/refresh are ordinary public endpoints. (15.4)

**Q: `add_header Set-Cookie` — does that tell the backend or the browser?**
The **browser** (response). `proxy_set_header` is what goes to the backend. (16.3)

**Q: Will the browser distrust a cookie set by the auth service on another port/server?**
No — the browser only sees nginx; cookies are scopeddomain + path, not port. (16.2)

**Q: Do all backends need the JWT secret, a shared user DB, refresh tokens?**
Not in the gateway pattern — only the auth service holds them; backends read `X-User`. If services verify tokens themselves, use asymmetric JWT (public keys), not shared secrets. (`integration-implementation-guide.md`)

**Q: Must all services be on the same machine on localhost?**
They must be **unreachable except via nginx**; loopback is simply the easiest way. Firewalls, internal networks, a gaway secret header, or mTLS also work. (15.6)

**Q: For one UI + backend product, should auth be at the gateway?**
No — keep it in the app (BFF: HttpOnly session cookie). Gateway auth fits many services sharing one user base. Products for many customers should have built-in auth plus an optional proxy-header mode (like Grafana). (15.7)

**Q: How do I integrate with external services that need their own credentials?**
Preferably through my backend's integration layer (`/api/integrations/...`) which calls th server-side with a token; nginx-injected static credentials are possible but limited. Gateway headers never become an external contract. (15.8)

**Q: With `proxy_pass http://b:8000/;` does nginx replace the whole path?**
No — only the part that **matched the location** is replaced; the remainder is appended. `/api/devices/5` in `location /api/` → `/` + `devices/5` = `/devices/5`. Without a path in `proxy_pass`, the path is sent unchanged. Verified against the official docs. (9.6.1)

**Q: `location = /_h_qadash` + `proxy_pass http://127.0.0.1:8000/api/auth/verify;` — does the backend get `/api/auth/verify/__auth_qadash`?**
No — the whole path matched, so it's fully replaced: the backend gets `/api/auth/verify`. (9.6.1)

**Q: Does the other team's server need an `/integrations/qadash/...` route?**
No — with `proxy_pass http://10.1.1.1:8000/;` our prefix is stripped; they receive `/reports/5` etc. (9.6.1, 15.8)

**Q: `Cookie` vs `Set-Cookie` — and where does `add_header Set-Cookie` put it?**
`Cookieest header, browser → server. `Set-Cookie` = response header, server → browser. `add_header` puts it on the response to the **browser**; the backend never sees it. (16.2, 16.3)

**Q: Can our nginx inject an API key into an iframe that points at their domain?**
No — the browser sends that request directly to them. Only URLs pointing at our nginx can be modified. Use an embed token, SSO, or proxy their UI through our nginx on a subdomain. (15.8)

---

*End of guide. If something new confuses me: find thin Section 1's diagram it belongs to, then jump to that section.*

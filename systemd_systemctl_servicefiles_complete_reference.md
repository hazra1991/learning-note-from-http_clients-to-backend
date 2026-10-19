# systemd, systemctl & Service Files — A Clear Mental Model

> A no-black-box reference. Read this top to bottom once and the whole thing clicks:
> what systemd is, what a service is, where `.service` files live, how systemd finds
> them, name collisions, `enable` vs `start`, symlinking your own service files, and
> drop-in overrides. Real examples from an actual machine throughout.

---

## 1. What problem does systemd solve?

Think about what happens when your Ubuntu machine boots up. Dozens of things need to start: the networking stack, the SSH server so you can log in remotely, Docker, your display manager, time synchronization, and so on. Somebody has to orchestrate all of that — decide what starts first, what depends on what, restart things that crash, and collect their logs.

Before systemd existed, Linux used simple shell scripts (called "init scripts") for this, and they were fragile, slow, and hard to manage.

**systemd is the first process that runs when your Linux machine boots.** It literally has process ID **1**. It is *not* something you installed — it came baked into Ubuntu. It is the "init system," meaning it is responsible for initializing everything else on your machine. Every single process on your system is either systemd itself or something that systemd (directly or indirectly) started.

> **Mental model:** systemd is the operating system's project manager. It reads a bunch of configuration files that describe *what* needs to run, *how* to run it, and *when* to run it — then it manages all of that for the lifetime of the machine.

---

## 2. What is a "service"?

A "service" is just systemd's word for a long-running background process — what Unix people traditionally call a **daemon**.

- Your SSH server is a service.
- Docker is a service.
- Nginx is a service.
- Your boardfarm FastAPI app is a service.

The key idea: a service is a program that should **start, keep running in the background, and ideally restart if it crashes** — without anyone manually typing commands in a terminal.

**Why you need this:** when you run

```bash
uvicorn boardfarm_api.api.app:app --host 127.0.0.1 --port 8000
```

by hand in a terminal, it works — but the moment you close that terminal or log out, the process dies. A service file tells systemd *"run this command for me, keep it alive, and start it automatically on boot."*

---

## 3. What is a `.service` file?

A `.service` file is just a **plain-text configuration file** — nothing more. It is not a script, it is not compiled code, it is not an application. It is a *declarative description* that tells systemd: here is the command to run, here is which user to run it as, here is what it depends on, and here is what to do if it fails. That's the entire idea.

### Example: `boardfarm-api.service`

Located at `/etc/systemd/system/boardfarm-api.service`:

```ini
[Unit]
Description=Boardfarm FastAPI Backend
After=network.target

[Service]
Type=simple
User=ahazra
WorkingDirectory=/home_ldap/ahazra/workspace/test-automation-engine
ExecStart=/usr/local/bin/uv run uvicorn boardfarm_api.api.app:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### What each section means

**`[Unit]` — metadata.**
- `Description` is a human-readable label (this is the "Boardfarm FastAPI Backend" you see in `systemctl status` output).
- `After=network.target` means *"don't start this until networking is up,"* because your API server needs a network to listen on. This is how systemd handles **ordering and dependencies**.

**`[Service]` — the actual runtime configuration.**
- `ExecStart` is the command systemd will execute — the *exact same command* you'd type in a terminal.
- `WorkingDirectory` is the directory systemd `cd`s into before running that command.
- `User` tells it which Linux user to run as.
- `Restart=on-failure` means if the process crashes (exits non-zero), systemd automatically restarts it.

**`[Install]` — *when* this service should start.**
- `WantedBy=multi-user.target` means *"start this service when the system reaches the normal multi-user runlevel"* — in practical terms, during a normal boot, after the system is basically up and running.
- **This section only matters when you run `systemctl enable`** (more on that below).

---

## 4. Where do `.service` files live, and how does systemd find them?

systemd looks in **specific directories**, and the location matters because it determines **priority**. There are three main places:

| Directory | Who owns it | Purpose |
|---|---|---|
| `/usr/lib/systemd/system/` | Packages (`apt`) | Where installed software drops its service files. **Never edit these** — package updates overwrite them. |
| `/etc/systemd/system/` | You (the admin) | Your own service files and overrides. **Highest priority.** |
| `/run/systemd/system/` | Runtime | Generated units that don't survive a reboot. Rarely touched directly. |

When you ran `sudo apt install nginx`, the nginx package dropped `nginx.service` into `/usr/lib/systemd/system/`. Your `boardfarm-api.service` sits in `/etc/systemd/system/` because it's *your* app.

### The two hard rules

1. **The file must end in `.service`.** That's how systemd knows it describes a service, as opposed to a `.timer`, `.socket`, `.mount`, or other unit type.
2. **It must be in one of these directories** for systemd to find it. You can't just put a `.service` file in your home directory and expect it to work.

The filename, minus the `.service` extension, becomes the **unit name** you use in all `systemctl` commands (e.g. `boardfarm-api`).

---

## 5. Name collisions & priority

**The filename *is* the identity.**

If you create `/etc/systemd/system/nginx.service`, it will **shadow (override)** the `/usr/lib/systemd/system/nginx.service` that came with the package. systemd uses a clear priority order:

```
/etc/systemd/system/   >   /run/systemd/system/   >   /usr/lib/systemd/system/
      (wins)                                              (lowest)
```

Within the *same* directory you simply cannot have two files with the same name — the filesystem prevents it. So the name you choose for your `.service` file is essentially a **unique identifier on that machine**.

---

## 6. What is `systemctl`?

If systemd is the **engine**, `systemctl` is the **steering wheel**. It's the command-line tool you use to talk to systemd.

| Command | What it actually does |
|---|---|
| `systemctl start boardfarm-api` | Run the `ExecStart` command **right now**. Process starts in the background; systemd tracks it. |
| `systemctl stop boardfarm-api` | Send a termination signal to the process and clean up. |
| `systemctl enable boardfarm-api` | **Does not start anything.** Creates a symlink in `multi-user.target.wants/` so the service starts automatically **on boot**. |
| `systemctl disable boardfarm-api` | Removes that symlink (won't start on boot). Does *not* stop a running instance. |
| `systemctl daemon-reload` | *"I changed a `.service` file on disk — re-read it."* Required after editing any unit file. |
| `systemctl status boardfarm-api` | Show whether it's running, its PID, memory, CPU time, and the last few log lines. |

> **Why `daemon-reload` exists:** systemd caches unit file contents in memory. After editing a service file (or a drop-in), you must run `daemon-reload` before the change takes effect.

### How `enable` really works (the symlink)

`systemctl enable` creates a symlink from `multi-user.target.wants/boardfarm-api.service` back to your service file. That symlink is how systemd knows *"when I reach multi-user.target during boot, I should also start boardfarm-api."*

Those `*.target.wants/` directories you see (like `multi-user.target.wants/`, `sockets.target.wants/`) are full of exactly these symlinks — one per service that should activate at that stage.

---

## 7. `enable` vs `start` vs `--now`

This trips everyone up, so here it is cleanly:

- **`enable`** = "start on **boot**" (creates the symlink, nothing more). Does **not** start it now.
- **`start`** = "start **right now**" (this instant). Does **not** survive a reboot.
- **`--now`** = "do **both**."

So this single command:

```bash
sudo systemctl enable --now boardfarm-api.service
```

is just shorthand for:

```bash
sudo systemctl enable boardfarm-api.service   # start on boot
sudo systemctl start  boardfarm-api.service   # start right now
```

People use `enable --now` when setting up a new service for the first time and they want it running immediately **and** surviving reboots.

The reverse works too:

```bash
sudo systemctl disable --now boardfarm-api.service   # stop now AND remove from boot
```

---

## 8. How this all ties together: the nginx reverse-proxy picture

Here's what you actually set up, conceptually:

1. **Your FastAPI app (boardfarm)** is a Python web server listening on `127.0.0.1:8000`. The `127.0.0.1` matters — it means *"only accept connections from this machine itself."* Nobody on the outside network can reach port 8000 directly.

2. **Nginx** is a separate service (also managed by systemd, from the package-installed `/usr/lib/systemd/system/nginx.service`). It listens on port **80/443** (standard HTTP/HTTPS), which *are* reachable from the outside. In your nginx config, a `proxy_pass` directive says *"forward incoming requests to `http://127.0.0.1:8000`."* Nginx is acting as a **reverse proxy** — a middleman.

The request flow:

```
Browser  →  nginx (port 80/443, public)  →  FastAPI app (port 8000, local only)
```

This is a standard deployment pattern because nginx handles things your Python app shouldn't worry about: SSL termination, serving static files efficiently, load balancing, rate limiting, and buffering slow clients.

Both nginx and boardfarm are just **two background processes systemd babysits**: started at boot, restarted on crash, inspectable with `systemctl status`, logs in the journal (`journalctl`).

---

## 9. Is creating a `.service` file "installing an application"?

**No.** Creating a `.service` file does not install anything.

Your application code (the FastAPI project in `/home_ldap/ahazra/workspace/test-automation-engine/`) is already on disk. The `.service` file is *purely configuration* telling systemd how to run that code as a managed background process.

> **Analogy:** The `.service` file is a **recipe card**. The recipe card doesn't create the food — the food (your code) already exists. The card just tells the chef (systemd) how to prepare and serve it.

When you `apt install nginx`, the package does **two things**:
1. Installs the nginx binary + config (the actual application).
2. Drops a `.service` file so systemd knows how to manage it.

For *your own* apps you do those two steps separately: put your code somewhere, then write a `.service` file to tell systemd about it.

> **Core insight:** systemd doesn't care what your app is, what language it's in, or how it works internally. It only cares about the command to start it, the user to run it as, and what to do if it fails. That's the entire contract between systemd and your application.

---

## 10. Keeping your `.service` file in your own repo (the symlink trick)

You can keep your `.service` file inside your project repository (so it's **version-controlled alongside your code**) and symlink it into `/etc/systemd/system/`.

```bash
# Your actual file lives in your project
/home_ldap/ahazra/workspace/test-automation-engine/boardfarm-api.service

# Create a symlink where systemd expects to find it
sudo ln -s /home_ldap/ahazra/workspace/test-automation-engine/boardfarm-api.service \
           /etc/systemd/system/boardfarm-api.service

# Tell systemd to re-read
sudo systemctl daemon-reload
```

systemd follows the symlink and reads the file from your project directory. Update the file in your repo → `systemctl daemon-reload` → changes picked up. No copying.

**This pattern is already all over your machine.** These lines from `/etc/systemd/system/` are symlinks:

```
redis.service -> /usr/lib/systemd/system/redis-server.service
sshd.service  -> /usr/lib/systemd/system/ssh.service
chronyd.service -> /usr/lib/systemd/system/chrony.service
```

Same mechanism — here the package manager uses it to create aliases (e.g. making `sshd.service` point to `ssh.service`).

### Can you point systemd at arbitrary custom directories?

**No.** systemd scans a *fixed* set of directories (`/etc/systemd/system/`, `/usr/lib/systemd/system/`, `/run/systemd/system/`, and a few others). There is no config option to add, say, `/home/ahazra/my-services/`. **The symlink approach is the intended solution** for keeping the file wherever you want while still having systemd see it.

> **One caveat:** if the symlink target is on a network filesystem or inside an encrypted home directory that isn't mounted yet at early boot, systemd may fail to read it during startup. For a home dir on a local disk this is rarely an issue — but it explains the occasional "service not found after reboot" mystery.

---

## 11. Drop-in overrides — customizing a package's service *without* editing its file

This is one of the most useful systemd features. Example comes straight from Docker on your machine.

### The problem drop-ins solve

Docker's service file lives at `/usr/lib/systemd/system/docker.service` and is **owned by the Docker package**. Every `apt upgrade` that updates Docker **overwrites** that file. So if you edited it directly to add proxy settings or change `ExecStart`, your changes get wiped on the next update.

You need a way to customize a package's service **without touching the package's own file.** That's what drop-ins are for.

### What a drop-in actually is

A drop-in is a small `.conf` file in a specially-named directory next to the service, which systemd **automatically merges on top of** the original `.service` file.

**The directory naming convention is the rule, not arbitrary.** For a service called `docker.service`, the drop-in directory **must** be named:

```
docker.service.d
```

That is: take the full unit name (`docker.service`), append `.d`. The `.d` suffix is a common Linux convention meaning *"a directory of configuration fragments"* (you'll see it in `/etc/cron.d/`, `/etc/sudoers.d/`, etc.).

Inside that directory, **any file ending in `.conf`** gets picked up. The filenames themselves are free-form:

```
/etc/systemd/system/docker.service.d/
├── http-proxy.conf
└── override.conf
```

Both are merged on top of `/usr/lib/systemd/system/docker.service`.

### How does systemd know to look? Is it automatic?

**Yes — completely automatic. There is no "register this drop-in" step.** When systemd loads a unit, it builds the final configuration by scanning a fixed set of locations **in order**, using the directory-naming convention to know what belongs to what. For `docker.service` it looks for `docker.service.d/` in each standard location:

```
/usr/lib/systemd/system/docker.service.d/   (package-provided drop-ins)
/run/systemd/system/docker.service.d/        (runtime)
/etc/systemd/system/docker.service.d/        (your admin overrides — highest priority)
```

It reads the main `.service` file first, then applies every `.conf` it finds in those `.d/` directories **on top**. Within a single directory, `.conf` files are applied in **alphanumeric order of filename** (so `http-proxy.conf` before `override.conf`, because 'h' < 'o'). That order only matters when two drop-ins set the *same* directive — the later one wins.

The `Drop-In:` line in `systemctl status` is systemd literally telling you what it found and merged:

```
Drop-In: /etc/systemd/system/docker.service.d
         └─http-proxy.conf, override.conf
```

This merge happens every time the unit loads — at boot, and whenever you run `systemctl daemon-reload`.

### Merging vs overriding — the tricky part (`ExecStart`)

Most directives are **replaceable**: if your drop-in sets a value, it replaces the original. (Set `Restart=on-failure` in a drop-in and it beats the original `Restart=always`.)

But some directives are **lists that append** rather than replace — and **`ExecStart` is the most important one.** If you just write a new `ExecStart=` in a drop-in, systemd tries to *add a second* startup command, which is an error for most service types. To genuinely **replace** it, you first **clear the list with an empty assignment**, then set your new value.

That's exactly what Docker's `override.conf` does:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd --bridge=none --host unix:///var/run/docker.sock --host tcp://0.0.0.0:2375
```

- The first line, `ExecStart=` with nothing after it, **resets/clears** the inherited `ExecStart`.
- The second line sets the real command you want.

Without that empty `ExecStart=` first line, you'd get an error. This **empty-then-set** pattern applies to all list-type directives (`ExecStart`, `ExecStartPre`, `Environment`, and a few others).

**Result:** the effective config of Docker = everything from the original `/usr/lib/systemd/system/docker.service`, **except** `ExecStart`, which is swapped for your custom one. That's why `systemctl status` shows Docker running with your flags (`--bridge=none`, `--host tcp://0.0.0.0:2375`) instead of the package default (`-H fd://`). The merge worked.

For reference, the package's original `docker.service` `[Service]` default was:

```ini
ExecStart=/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
```

### The easy way to create a drop-in

Don't hand-create the directory. systemd does it for you:

```bash
sudo systemctl edit docker.service
```

This automatically:
1. Creates `/etc/systemd/system/docker.service.d/override.conf` (that's where the default name `override.conf` comes from),
2. Opens it in an editor,
3. Runs `daemon-reload` for you on save.

A conventionally-named file like `http-proxy.conf` is usually created by hand or by a provisioning script, since that's the common name people give proxy-specific settings.

### Don't forget to apply it

After adding/changing any drop-in **by hand**:

```bash
sudo systemctl daemon-reload      # re-read & re-merge the config
sudo systemctl restart docker     # apply the new ExecStart to the running process
```

- `daemon-reload` makes systemd re-read and re-merge.
- `restart` applies the new `ExecStart` to the actually-running daemon.

---

## 12. One-page cheat sheet

**Concepts**
- **systemd** = PID 1, the init system / project manager. Starts & supervises everything.
- **service / daemon** = a long-running background process systemd manages.
- **`.service` file** = plain-text *recipe* telling systemd how to run something. Not an app, not a script.

**Where files live (priority high → low)**
```
/etc/systemd/system/      ← your files & overrides (wins)
/run/systemd/system/      ← runtime (ephemeral)
/usr/lib/systemd/system/  ← package-installed (never edit)
```

**Service file skeleton**
```ini
[Unit]
Description=...
After=network.target

[Service]
User=...
WorkingDirectory=...
ExecStart=...
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**Everyday commands**
```bash
sudo systemctl start   <name>     # run now
sudo systemctl stop    <name>     # stop now
sudo systemctl enable  <name>     # start on boot (symlink)
sudo systemctl disable <name>     # don't start on boot
sudo systemctl enable --now  <name>   # boot + now
sudo systemctl disable --now <name>   # stop now + remove from boot
sudo systemctl restart <name>     # stop then start
systemctl status  <name>          # state, PID, memory, recent logs
sudo systemctl daemon-reload      # after editing any unit file / drop-in
journalctl -u <name> -f           # follow a service's logs
```

**Keep your service file in your repo**
```bash
sudo ln -s /path/in/your/repo/foo.service /etc/systemd/system/foo.service
sudo systemctl daemon-reload
```

**Override a package's service (drop-in)**
```bash
sudo systemctl edit <name>        # creates /etc/systemd/system/<name>.service.d/override.conf
# To replace ExecStart, clear it first:
#   [Service]
#   ExecStart=
#   ExecStart=/new/command --flags
sudo systemctl daemon-reload
sudo systemctl restart <name>
```

**Golden rules to remember**
- File must end in `.service` and live in a systemd dir (or be symlinked into one).
- Filename = unit name = unique identity; `/etc` shadows `/usr/lib`.
- `enable` ≠ `start`. `--now` = both.
- Drop-ins live in `<unit>.service.d/*.conf`, merged automatically, no registration.
- `ExecStart` needs empty-then-set to truly replace.
- Edited a unit or drop-in? → `daemon-reload` (+ `restart` to apply to the running process).

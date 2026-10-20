# Docker Networking & IP Collisions — Reference

A from-scratch refresher on how Docker assigns container network subnets, why that can cut a server off the network, and how to configure and debug it.

---

## 1. The problem in one paragraph

A server was reached over SSH from a client whose address was `172.17.133.5`. Running `docker compose up` on that server created a new Docker network, and Docker picked `172.17.0.0/16` for it. The server now had a local route saying *"all of 172.17.x.x is on this Docker bridge"*, so replies to the SSH client were sent into the empty bridge instead of out through the real gateway. The SSH session died with `client_loop: send disconnect: Broken pipe`, and port 22 stopped answering. The server itself was healthy the whole time — only the route back to the client was hijacked.

Docker has no knowledge of your corporate network. It allocates subnets from private ranges that a company network may also use, and it does so silently.

---

## 2. Two kinds of Docker networks

| | Default bridge (`docker0`) | User-defined networks |
|---|---|---|
| Created by | Docker at startup | `docker compose up`, `docker network create` |
| Used by | `docker run` without `--network`, and image **build steps** (`RUN apt-get`, `RUN uv sync`, …) | Every Compose project (`<project>_default`) |
| Subnet controlled by | **`bip`** in `daemon.json` | Compose `ipam` subnet, else **`default-address-pools`**, else Docker's built-in pool |
| DNS by service name | No | Yes (`db:5432` works) |

**Why Compose doesn't just use `docker0`:** a per-project network gives isolation between projects and built-in DNS so services reach each other by name.

**Why `bip` alone isn't enough:** it only moves `docker0`. Compose networks ignore it. Moving `docker0` away from `172.17` actually *frees* `172.17.0.0/16` for the first Compose network — which is exactly what caused the incident above.

---

## 3. Docker's built-in address pool

When nothing else is configured, Docker hands out subnets in this order:

- `172.17.0.0/16` … `172.31.0.0/16` — in **/16** blocks
- `192.168.0.0/16` — in **/20** blocks

It picks the next free block. "Free" means not used by another Docker network and not overlapping a route already on the host. A client reached through the **default gateway** has no specific route, so Docker does not see it and happily takes its range.

**Subnet size is a fingerprint** when reading `ip a` or `docker network inspect`:

| You see | It came from |
|---|---|
| `172.x.0.0/16` | Built-in pool (auto-picked) |
| `192.168.x.0/20` | Built-in pool (auto-picked) |
| `/24` or any other size | Explicitly pinned (compose file, `--subnet`) or your own pool |

Two servers running the *same* compose file can get *different* subnets, depending on what else was created on each over time. A server that "works fine" may simply have landed on a range no client uses — it is lucky, not protected.

---

## 4. Which setting wins

| Situation | What Docker uses |
|---|---|
| Compose has `ipam: config: subnet: X` | Exactly `X`, whether or not a pool is configured, and even if `X` is outside the pool |
| Compose has no subnet, `daemon.json` has `default-address-pools` | The next free block from **your** pool |
| Neither | The next free block from Docker's **built-in** pool (`172.17`–`172.31`, then `192.168`) |
| `docker0` | Always `bip`, independent of both |

Rules that follow from this:

- **An explicit subnet is your responsibility.** Docker rejects overlap with another *Docker* network, but not with your corporate network.
- **Existing networks never move.** Changing a pool or a compose subnet only applies after the network is removed and recreated (`docker compose down`, then `up`).
- **Bridge subnets are local to each host.** Container traffic is NATed to the host's own IP before leaving, so two servers can safely use the same bridge subnet.
- **Your pool must not overlap subnets you pin explicitly**, or a pinned network can fail to create because the pool already handed that range out.

---

## 5. Choosing a safe range

A subnet is safe if it overlaps none of:

- The host's own networks (check `ip a`, e.g. `10.64.36.0/23`, `10.64.38.0/23`)
- `docker0` (the `bip` range, e.g. `192.168.101.0/24`)
- Any address clients connect **from** (check `echo $SSH_CONNECTION`)
- Any network the host must reach: proxy, registry, lab devices, corporate ranges (e.g. `172.16.0.0/12`)
- Other subnets pinned on the same host

Confirm with the network team when unsure.

---

## 6. Configuration

### `/etc/docker/daemon.json` (server-wide)

```json
{
    "bip": "192.168.101.1/24",
    "default-address-pools": [
        {"base": "192.168.192.0/20", "size": 24}
    ],
    "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2375"],
    "insecure-registries": ["10.64.38.13:5000"]
}
```

| Key | Meaning |
|---|---|
| `bip` | Address and subnet of `docker0`. Keep it set explicitly. |
| `default-address-pools` | Pool for every network created without an explicit subnet. `base` = the range, `size` = prefix length of each network handed out. `192.168.192.0/20` split into `/24` = 16 networks of ~250 addresses. |
| `hosts` | Where the daemon listens. The Unix socket is what local `docker` / `docker compose` use and works by default. `tcp://0.0.0.0:2375` exposes the **unauthenticated, unencrypted** Docker API on every interface — equivalent to root access for anyone who can reach port 2375. Only needed for remote clients such as CI; prefer TLS on 2376. Not required for running containers. |
| `insecure-registries` | Registries Docker may use over plain HTTP or with an untrusted certificate. Acceptable for internal registries on trusted networks. |

> **Warning about `hosts`:** on a stock systemd install, `docker.service` already passes `-H fd://`. Setting `hosts` in `daemon.json` as well makes dockerd **refuse to start**, unless a systemd drop-in (`/etc/systemd/system/docker.service.d/override.conf`) replaces the start command. Never copy a `daemon.json` containing `hosts` to another server without checking this.

**Applying a daemon change** — restarting Docker stops every running container (those with a restart policy come back):

```bash
sudo dockerd --validate --config-file /etc/docker/daemon.json   # syntax + option check
sudo systemctl restart docker
docker info | grep -A5 -i "address pools"                        # confirm the pool is active
```

### Compose — pin the project's subnet (per project, no daemon restart)

At the top level of `docker-compose.yaml`, beside `services:`:

```yaml
networks:
  default:
    ipam:
      config:
        - subnet: 192.168.56.0/24
```

### Compose — skip the project network entirely

For a single service that doesn't need name-based DNS, join `docker0` instead. No new subnet is ever created; `ports:` mappings still work.

```yaml
services:
  myservice:
    network_mode: bridge
```

---

## 7. What to do when

| Situation | Do this |
|---|---|
| New project on a shared server | Pin a subnet in the compose file, or use `network_mode: bridge` |
| You control the server and want all future projects safe | Add `default-address-pools` to `daemon.json` (plan a Docker restart) |
| Project already running on a risky range (e.g. `172.x`) | Pin a safe subnet, then `docker compose down && docker compose up -d` |
| Single service, no inter-service DNS needed | `network_mode: bridge` |
| Several services that talk by name | Pinned subnet |
| Build steps can't reach the internet | Check `docker0` exists and the proxy is passed as build args; last resort `build: network: host` |

---

## 8. Debug toolkit

```bash
# Daemon config and active pools
cat /etc/docker/daemon.json
sudo dockerd --validate --config-file /etc/docker/daemon.json
docker info | grep -A5 -i "address pools"

# Every Docker network and its subnet
docker network ls
docker network inspect -f '{{.Name}}  {{range .IPAM.Config}}{{.Subnet}}{{end}}' $(docker network ls -q)

# Host interfaces and routes (docker0 and br-xxxx are Docker bridges)
ip -br addr
ip route
ip route | grep -E '192\.168\.|172\.'

# Who is connecting, and how the host routes back to them
echo $SSH_CONNECTION                 # first field = client IP
ip route get <client-ip>             # must be "via <gateway> dev <real NIC>", never "dev br-..." or "dev docker0"

# What a compose file will actually create
docker compose config | grep -A4 ipam

# Container health
docker inspect --format '{{json .State.Health}}' <container> | python3 -m json.tool
```

**Testing reachability:** `ping` uses ICMP, which is often filtered on corporate networks even when SSH and HTTPS work. A failed ping proves nothing. Test the real port instead:

```bash
nc -vz <host> 22
ssh -vvv user@<host>
```

---

## 9. Safe rollout with automatic rollback

Run from the same SSH path you care about (the one that would break):

```bash
cd <project-dir>
docker compose config | grep -A4 ipam                  # confirm the intended subnet

# Dead-man switch: tears the project down in 3 minutes unless cancelled.
# nohup keeps it alive even if SSH drops.
nohup sh -c 'sleep 180 && cd <project-dir> && docker compose down' > /tmp/rollback.log 2>&1 &
echo $!                                                 # note the PID

docker compose up -d
docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' <project>_default
ip route get <client-ip>                                # still via the gateway?

kill <PID>                                              # all good: cancel the rollback
```

If the session drops, wait 3 minutes — the network is removed and the route comes back on its own.

---

## 10. If you are already locked out

1. You cannot fix it over the network — the route to you is the broken part.
2. Get in another way:
   - an out-of-band console (server BMC / remote management interface), or
   - a colleague with a session on the host, or from a host whose traffic isn't in the hijacked range (e.g. a machine on the same server subnet).
3. Run `docker compose down` in the project directory. This removes the network and its routes; SSH recovers immediately.
4. Fix the subnet (section 6) **before** bringing it up again.

> **Reboot caveat:** a reboot clears the bad route, but a service with `restart: unless-stopped` comes back up and recreates the same network. Run `docker compose down` right after the reboot, or fix the subnet first.

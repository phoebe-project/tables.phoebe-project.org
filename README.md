# PHOEBE tables stack

Two version-specific backend servers (sharing one codebase) plus a router that
dispatches incoming requests to the right version, all in one Docker Compose
stack. The whole thing goes up and down together.

```
phoebe-tables/
│
├── docker-compose.yml      # the one stack: server-24, server-25, router
├── .env                    # namespaced config (SERVER24_*, SERVER25_*, ROUTER_*)
├── routing.conf            # routing ground truth (INI), mounted into the router
│
├── server/                 # the ONE shared server codebase
│   ├── server.py
│   └── Dockerfile          # builds a version via the PHOEBE_BRANCH build arg
├── router/
│   ├── router.py
│   └── Dockerfile
├── data/                   # version-specific passband data (NOT in git)
│   ├── 2.4/
│   └── 2.5/
└── apache/
    └── router.phoebe-project.org.conf   # host-side vhost (reference copy)
```

## How it fits together

Both backends build from the identical `./server` context; they differ only in
the `PHOEBE_BRANCH` build arg (and their tag/name/data). The router reads
`routing.conf` and proxies each request to the matching backend.

All three services share the Compose network and resolve each other by **service
name**, so `routing.conf` points at `http://server-24:80` / `http://server-25:80`
rather than host IP:port. This removes the host-port coupling: only the router
is publicly exposed, and there is no port number to keep in sync between the
router config and the backend mappings.

Routing precedence (in `router.py`): an `[exceptions]` substring match wins
first, then numeric `major.minor`, then the `[settings] default`. So
`2.4.22+feature-blending` goes to 2.5 even though it parses as 2.4.

## First-time setup

1. **Set the versions** in `.env`: `SERVER24_BRANCH`, `SERVER25_BRANCH` (git
   tags/branches in the PHOEBE repo).

2. **Populate the data dirs.** Each backend reads passband tables from
   `/tables/data` (mounted read-only). Copy your existing passband data into
   `data/2.4/` and `data/2.5/`. These are large binaries and are gitignored.

3. **Tune memory** in `.env`: `SERVER_MEMORY_LIMIT` (each backend holds PHOEBE +
   passbands in RAM) and `ROUTER_MEMORY_LIMIT` (small; the router only streams).

## Bring it up

```bash
docker compose up --build -d
docker compose ps          # router starts only after both backends are healthy
```

Smoke test (router is on `${ROUTER_PORT}`, default 8084):

```bash
curl -s "http://192.168.1.109:8084/info?phoebe_version=2.4.22"   # -> 2.4 backend
curl -s "http://192.168.1.109:8084/info?phoebe_version=2.5.0"    # -> 2.5 backend
curl -s "http://192.168.1.109:8084/info?phoebe_version=2.4.22%2Bfeature-blending"  # -> 2.5
```

**Closing check (do this every deploy).** `?check=1` makes the router actively
probe each routed backend and report whether it is reachable — this is what
catches a `routing.conf` entry pointing at a backend that never came up (the
"config points at something that isn't there" failure):

```bash
curl -s "http://192.168.1.109:8084/_router/health?check=1"
```

Every backend under `backend_checks` should report `"status": 200`. Anything
`"unreachable"` means that version is routed but not actually serving — fix it
before announcing the deploy.

## Adding a new version (e.g. 2.6)

1. Add a `server-26` service in `docker-compose.yml` (copy `server-25`, change
   the arg/tag/name/data/port).
2. Add `SERVER26_*` lines in `.env`.
3. Add `2.6 = http://server-26:80` under `[backends]` in `routing.conf`
   (and bump `[settings] default` if 2.6 becomes the latest — flush the Apache
   cache at that rollover).
4. Add `data/2.6/`.

Adding an **exception** rule is just a line in `routing.conf`.

## The timeout chain (must be ordered, innermost ≤ outermost)

A slow passband generation passes through several layers; each must allow at
least as long as the one inside it, or the request may be cut off mid-stream:

```
backend gunicorn --timeout (120s)   # server-24 / server-25
  < router READ_TIMEOUT (600s)      # router waits on the backend
    < router gunicorn --timeout (900s)
      < Apache ProxyPass timeout (900s, in the vhost)
```

If real generations can exceed 120s, raise the backend `--timeout` first —
otherwise the backend worker is killed before the outer layers even notice.

## Notes

- `routing.conf` is read once at startup; edit it and restart the router (or
  the stack) to apply.
- `routing.conf` must exist as a file before `up` (single-file bind mount).
- `data/<ver>/` directories are created by Docker if missing, but will be empty
  — populate them or the backend serves no passbands.

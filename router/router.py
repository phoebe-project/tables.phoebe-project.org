#!/usr/bin/python

"""
PHOEBE tables router.

Sits at https://tables.phoebe-project.org and transparently proxies every
request to the correct version-specific backend tables server, based on the
`phoebe_version` query parameter, then streams the backend's response back to
the caller unchanged. Callers are agnostic to the routing.

Routing is configured in an INI file (routing.conf), mounted read-only and
read once at startup, so adding a version or an exception rule is a config edit,
not a code change. Operational tuning (timeouts, log level, gunicorn) stays in
the environment / compose.
"""

import os
import re
import sys
import logging
import configparser

try:
    from flask import Flask, request, Response, jsonify
    import requests
except ImportError:
    raise ImportError("dependencies not met: pip install flask requests")


app = Flask(__name__)


CONFIG_PATH = os.environ.get("ROUTING_CONFIG", "/router/routing.conf")


def _load_config(path=CONFIG_PATH):
    """
    Load routing config from an INI file. Expected structure:

        [backends]                           # routing key -> backend base URL
        2.4 = http://192.168.1.109:8082
        2.5 = http://192.168.1.109:8083

        [settings]
        default = 2.5                        # version-less / latest / unknown

        [exceptions]                         # checked BEFORE numeric major.minor
        feature-blending = 2.5               # parsing; file order = first match wins

    Each [exceptions] key is a case-insensitive substring tested against the
    full phoebe_version string, so e.g. "2.4.22+feature-blending" routes to 2.5
    even though it parses as 2.4.

    Returns (backends, default_key, overrides) where overrides is an ordered
    list of {"contains", "backend"}. Validates referential integrity (default
    and every exception target must be a configured backend) and raises
    ValueError on any problem, so a bad config fails the container fast at boot
    rather than silently misrouting at request time.
    """
    if not os.path.exists(path):
        raise ValueError("routing config not found at {} (is routing.conf mounted?)".format(path))

    cp = configparser.ConfigParser(interpolation=None)  # don't treat % in URLs specially
    cp.optionxform = str                                 # preserve key case (e.g. version keys)
    try:
        with open(path, "r") as f:
            cp.read_file(f)
    except configparser.Error as e:
        # covers duplicate keys/sections and general parse errors
        raise ValueError("routing config {} is not valid INI: {}".format(path, e))

    if not cp.has_section("backends") or not cp.options("backends"):
        raise ValueError("routing config: [backends] section is missing or empty")

    backends = {}
    for key, url in cp.items("backends"):
        url = (url or "").strip().rstrip("/")
        if not url:
            raise ValueError("routing config: backend {!r} has an empty URL".format(key))
        backends[key] = url

    if not cp.has_option("settings", "default"):
        raise ValueError("routing config: [settings] 'default' is required")
    default_key = cp.get("settings", "default").strip()
    if default_key not in backends:
        raise ValueError("routing config: default {!r} is not a configured backend".format(default_key))

    overrides = []
    if cp.has_section("exceptions"):
        for contains, backend in cp.items("exceptions"):
            contains = (contains or "").strip()
            backend = (backend or "").strip()
            if not contains:
                raise ValueError("routing config: an [exceptions] entry has an empty key")
            if backend not in backends:
                raise ValueError("routing config: exception {!r} -> backend {!r} is not configured".format(contains, backend))
            overrides.append({"contains": contains, "backend": backend})

    return backends, default_key, overrides


def _version_sort_key(key):
    """Sort 'major.minor' keys numerically: '2.10' > '2.9'."""
    try:
        return tuple(int(p) for p in key.split("."))
    except ValueError:
        return (0,)


BACKENDS, DEFAULT_BACKEND_KEY, OVERRIDES = _load_config()
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.environ.get("READ_TIMEOUT", "600"))

# The "newest" configured backend, used as a last-resort default.
_HIGHEST_KEY = sorted(BACKENDS.keys(), key=_version_sort_key)[-1]

# HTTP headers split into two kinds. End-to-end headers are meant for the
# final recipient and must survive every proxy hop unchanged. Hop-by-hop
# headers describe a single transport connection between two adjacent nodes,
# are meaningful only for that one leg, and must NOT be forwarded onward -- a
# proxy consumes them and regenerates its own for the next connection. The
# conventional hop-by-hop list is below (RFC 7230 6.1 / RFC 9110 7.6.1).
# We additionally drop Content-Length and Content-Encoding because we re-stream
# the body: the length may change (or we switch to chunked), and requests'
# iter_content already decodes any content-encoding, so forwarding those would
# describe a body that no longer matches.

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
RESPONSE_SKIP = HOP_BY_HOP | {"content-length", "content-encoding"}

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tables-router")

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)")


def _version_key(version):
    """Extract 'major.minor' from a version string, or None if not usable."""
    if not version:
        return None
    if version.strip().lower() == "latest":
        return None
    m = _VERSION_RE.match(version)
    if not m:
        return None
    return "{}.{}".format(m.group(1), m.group(2))


def _choose_backend():
    """
    Return (base_url, key, reason) for the current request, where reason is
    'override:<token>', 'by-version', or 'default'.

    Order matters: overrides are evaluated BEFORE numeric major.minor parsing
    and win, so e.g. '2.4.22+feature-blending' is sent to its override backend
    even though it parses as '2.4'. (Note: a literal '+' in a query string
    decodes to a space, so matching is a substring test on the token itself,
    which is robust whether the client sends '+', '%2B', or a space.)
    """
    version = request.args.get("phoebe_version", None)

    if version and version.strip().lower() != "latest":
        vlow = version.lower()
        # overrides first (highest priority, first match wins)
        for ov in OVERRIDES:
            if ov["contains"].lower() in vlow:
                return BACKENDS[ov["backend"]], ov["backend"], "override:" + ov["contains"]
        # then numeric major.minor
        key = _version_key(version)
        if key is not None and key in BACKENDS:
            return BACKENDS[key], key, "by-version"

    # version-less, 'latest', unhosted, or unmatched -> default
    if DEFAULT_BACKEND_KEY in BACKENDS:
        return BACKENDS[DEFAULT_BACKEND_KEY], DEFAULT_BACKEND_KEY, "default"
    return BACKENDS[_HIGHEST_KEY], _HIGHEST_KEY, "default"


# dedicated router endpoint:

@app.route("/_router/health", methods=["GET"])
def health():
    info = {
        "router": "ok",
        "backends": BACKENDS,
        "default_backend_key": DEFAULT_BACKEND_KEY,
        "overrides": OVERRIDES,
    }

    # ?check=1 actively probes each backend's /info
    if request.args.get("check"):
        checks = {}
        for k, url in BACKENDS.items():
            try:
                r = requests.get(url + "/info", timeout=(2, 5))
                checks[k] = {"status": r.status_code, "body": r.json() if r.ok else None}
            except requests.exceptions.RequestException as e:
                checks[k] = {"status": "unreachable", "detail": str(e)}
        info["backend_checks"] = checks
    return jsonify(info)


# everything else (the two routes are catch-all):

@app.route("/", defaults={"path": ""}, methods=["GET", "HEAD", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "HEAD", "OPTIONS"])
def proxy(path):
    base_url, key, reason = _choose_backend()

    target = "{}/{}".format(base_url, path)
    if request.query_string:
        # forward the query string byte-for-byte (latin-1 round-trips all bytes)
        target = "{}?{}".format(target, request.query_string.decode("latin-1"))

    log.info("%s /%s  phoebe_version=%s -> %s (%s)",
             request.method, path,
             request.args.get("phoebe_version", "(none)"),
             key, reason)

    fwd_headers = {k: v for k, v in request.headers
                   if k.lower() not in HOP_BY_HOP and k.lower() != "host"}

    try:
        backend_resp = requests.request(
            method=request.method,
            url=target,
            headers=fwd_headers,
            data=request.get_data(),
            stream=True,            # don't buffer large downloads in memory
            allow_redirects=False,  # relay redirects to the caller unchanged
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.exceptions.RequestException as err:
        log.warning("backend %s unreachable: %s", base_url, err)
        return jsonify({"router_error": "backend unavailable",
                        "backend_key": key,
                        "detail": str(err)}), 502

    resp_headers = [(k, v) for k, v in backend_resp.raw.headers.items()
                    if k.lower() not in RESPONSE_SKIP]

    def generate():
        try:
            for chunk in backend_resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            backend_resp.close()

    return Response(generate(), status=backend_resp.status_code, headers=resp_headers)


if __name__ == "__main__":
    # local dev only; in the container gunicorn serves router:app
    port = int(sys.argv[1]) if len(sys.argv) >= 2 else 5557
    host = sys.argv[2] if len(sys.argv) >= 3 else "127.0.0.1"
    log.info("*** ROUTER READY at %s:%s -> %s ***", host, port, BACKENDS)
    app.run(host=host, port=port)

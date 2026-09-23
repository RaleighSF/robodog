#!/usr/bin/env python3
"""Operator login for the Watch Dog dashboard.

Every route (robot control, video, APIs, settings) requires a signed-in
operator. Open: /login, /logout, /healthz, /static/*.

Loopback trust: on the AGX an on-box supervisor (deploy/systemd/
watchdog-autostart.sh) drives the API from 127.0.0.1, so loopback is trusted
there. Set WATCHDOG_TRUST_LOOPBACK=0 wherever a proxy or other local service
could relay outside traffic over loopback (the Thor container disables it).

Sessions are bound to a credential *generation*: changing the password
rotates the generation, and any session minted under an older one is
refused on its next request, even one that was in flight during the change.
The cookie-signing key itself is stable.

Mutating requests (anything but GET/HEAD/OPTIONS) must carry an Origin or
Referer from this same host:port, which blocks cross-origin CSRF (including
other services on the same host at a different port).

Fail-closed: with no password configured the dashboard stays locked.
Credentials live on the device, never in git: auth.json next to the writable
config (Thor: /state/auth.json in the watchdog-state volume; AGX: repo dir,
gitignored). Throttling state is in memory and resets on restart.

Set or change the password:
    python3 auth.py set-password
    docker exec -it watchdog python3 auth.py set-password
"""
import collections
import fcntl
import getpass
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from werkzeug.security import check_password_hash, generate_password_hash

SESSION_DAYS = 30
_PER_ADDR_FAILURES = 5        # per client address within the window...
_GLOBAL_FAILURES = 30         # ...and across all addresses within the window
_WINDOW_SECONDS = 60
_MAX_TRACKED_ADDRS = 1024
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_mem_lock = threading.Lock()
_failures = {}                           # addr -> deque[timestamps]
_global_failures = collections.deque()   # timestamps
_snapshot_cache = {"sig": None, "data": {}}


# ── credential file ───────────────────────────────────────────────────────

def _auth_path():
    explicit = os.environ.get("WATCHDOG_AUTH_FILE")
    if explicit:
        return explicit
    cfg = os.environ.get("WATCHDOG_CONFIG", "config.yaml")
    return os.path.join(os.path.dirname(os.path.abspath(cfg)), "auth.json")


@contextmanager
def _file_lock():
    """Inter-process lock so the CLI and the running app never interleave."""
    fd = os.open(_auth_path() + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_file():
    try:
        with open(_auth_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_file(data):
    path = _auth_path()
    fd, tmp = tempfile.mkstemp(prefix=".auth-", suffix=".tmp",
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w") as f:           # mkstemp: 0600, unique name
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _stat_sig():
    try:
        st = os.stat(_auth_path())
        return (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def snapshot():
    """One consistent view of the credential file (hash, key, generation).
    Writes are atomic renames (new inode), and the file is re-read if its
    identity changed while it was being read."""
    for _ in range(5):
        before = _stat_sig()
        if before is not None and before == _snapshot_cache["sig"]:
            return _snapshot_cache["data"]
        data = _read_file()
        if _stat_sig() == before:
            _snapshot_cache.update(sig=before, data=data)
            return data
    return _read_file()


def _ensure_keys():
    """Create the signing key and generation once, at app start."""
    with _file_lock():
        data = _read_file()
        changed = False
        if not data.get("secret_key"):
            data["secret_key"] = secrets.token_hex(32)
            changed = True
        if not data.get("generation"):
            data["generation"] = secrets.token_hex(8)
            changed = True
        if changed:
            _write_file(data)


def password_configured():
    return bool(snapshot().get("password_hash"))


def set_password(password):
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    with _file_lock():
        data = _read_file()
        data["password_hash"] = generate_password_hash(password)
        data.setdefault("secret_key", secrets.token_hex(32))
        data["generation"] = secrets.token_hex(8)   # revokes every session
        _write_file(data)


# ── throttling ────────────────────────────────────────────────────────────

def _prune(now):
    cutoff = now - _WINDOW_SECONDS
    while _global_failures and _global_failures[0] < cutoff:
        _global_failures.popleft()
    for addr in list(_failures):
        q = _failures[addr]
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            del _failures[addr]


def _throttled(addr, now):
    _prune(now)
    if len(_global_failures) >= _GLOBAL_FAILURES:
        return True
    return len(_failures.get(addr, ())) >= _PER_ADDR_FAILURES


def _record_failure(addr, now):
    _global_failures.append(now)
    if addr not in _failures and len(_failures) >= _MAX_TRACKED_ADDRS:
        # Bounded memory: drop the address whose latest failure is oldest.
        oldest = min(_failures, key=lambda a: _failures[a][-1])
        del _failures[oldest]
    _failures.setdefault(addr, collections.deque()).append(now)


def verify(addr, password):
    """(ok, error, generation). The generation comes from the same snapshot
    the hash was checked against."""
    now = time.time()
    with _mem_lock:
        if _throttled(addr, now):
            return False, "Too many attempts. Wait a minute and try again.", None
    data = snapshot()
    stored = data.get("password_hash")
    if not stored:
        return False, "No operator password is set on this device yet.", None
    if check_password_hash(stored, password or ""):
        with _mem_lock:
            _failures.pop(addr, None)
        return True, None, data.get("generation")
    with _mem_lock:
        _record_failure(addr, now)
    return False, "Incorrect password.", None


# ── request helpers ───────────────────────────────────────────────────────

def safe_next(nxt):
    """Same-site relative path only. Rejects control characters and
    backslashes before parsing, so browser normalisation can't turn a
    validated path into an off-site authority (e.g. "/<TAB>/evil")."""
    if not nxt or any(ord(c) < 32 or ord(c) == 127 for c in nxt) or "\\" in nxt:
        return "/"
    parts = urlsplit(nxt)
    if parts.scheme or parts.netloc or not nxt.startswith("/") or nxt.startswith("//"):
        return "/"
    return nxt


def _same_origin(request):
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source or source == "null":
        return False
    parts = urlsplit(source)
    return parts.scheme in ("http", "https") and parts.netloc == request.host


def init_app(app, render_login):
    """Install the login guard. render_login(error, configured) -> response."""
    from flask import jsonify, redirect, request, session, url_for
    from flask.sessions import SecureCookieSessionInterface

    _ensure_keys()
    trust_loopback = os.environ.get("WATCHDOG_TRUST_LOOPBACK", "1") != "0"
    tls = bool(os.environ.get("WATCHDOG_TLS_CERT"))

    class _SnapshotKeySessions(SecureCookieSessionInterface):
        def get_signing_serializer(self, app_):
            app_.secret_key = snapshot().get("secret_key") or app_.secret_key
            return super().get_signing_serializer(app_)

    app.session_interface = _SnapshotKeySessions()
    app.secret_key = snapshot().get("secret_key")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=tls,
        SESSION_COOKIE_NAME="watchdog_session",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
    )
    open_endpoints = {"login", "logout", "healthz", "static"}

    @app.before_request
    def _require_operator():
        loopback = trust_loopback and request.remote_addr in ("127.0.0.1", "::1")
        if request.method not in _SAFE_METHODS and not loopback \
                and request.endpoint != "healthz" and not _same_origin(request):
            return jsonify({"error": "cross-origin request refused"}), 403
        if request.endpoint in open_endpoints or loopback:
            return None
        gen = snapshot().get("generation")
        if session.get("operator") and gen and session.get("gen") == gen:
            return None
        session.clear()     # stale generation: signed out by a password change
        wants_html = (request.method == "GET" and
                      "text/html" in (request.headers.get("Accept") or ""))
        if wants_html:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return jsonify({"error": "operator login required"}), 401

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            ok, err, gen = verify(request.remote_addr, request.form.get("password"))
            if ok:
                session.clear()
                session["operator"] = True
                session["gen"] = gen
                session.permanent = True
                return redirect(safe_next(request.args.get("next")))
            return render_login(err, password_configured()), 401
        return render_login(None, password_configured())

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/healthz")
    def healthz():
        return "ok", 200


def _main(argv):
    if len(argv) >= 2 and argv[1] == "set-password":
        if "--stdin" in argv:
            pw = sys.stdin.readline().rstrip("\n")
        else:
            pw = getpass.getpass("New operator password: ")
            if pw != getpass.getpass("Repeat: "):
                print("Passwords do not match.", file=sys.stderr)
                return 1
        try:
            set_password(pw)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        print("Operator password set in %s (all sessions signed out)." % _auth_path())
        return 0
    if len(argv) >= 2 and argv[1] == "status":
        print("password configured: %s (%s)" % (password_configured(), _auth_path()))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

#!/usr/bin/env python3
"""Operator login for the Watch Dog dashboard.

Every route (robot control, video, APIs, settings) requires a signed-in
operator. Open: /login, /logout, /healthz, /static/*. Requests from loopback
are trusted so on-box supervisors (deploy/systemd/watchdog-autostart.sh) keep
working; inside a container, host traffic arrives from the Docker bridge, not
loopback, so it is still challenged.

Fail-closed: with no password configured the dashboard stays locked and the
login page says how to set one. Credentials live on the device, never in git:
auth.json next to the writable config (Thor: /state/auth.json in the
watchdog-state volume; AGX: the repo dir, gitignored).

Set or change the password:
    python3 auth.py set-password            # prompts
    docker exec -it watchdog python3 auth.py set-password
"""
import getpass
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

SESSION_DAYS = 30
_MAX_FAILURES = 5          # per client address...
_LOCKOUT_SECONDS = 60      # ...then a cool-down
_lock = threading.Lock()
_failures = {}             # addr -> (count, first_failure_ts)


def _auth_path():
    explicit = os.environ.get("WATCHDOG_AUTH_FILE")
    if explicit:
        return explicit
    cfg = os.environ.get("WATCHDOG_CONFIG", "config.yaml")
    base = os.path.dirname(os.path.abspath(cfg))
    return os.path.join(base, "auth.json")


def _load():
    try:
        with open(_auth_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    path = _auth_path()
    # mkstemp creates the file 0600 with a unique name: safe if the CLI and
    # the running app write at the same moment.
    fd, tmp = tempfile.mkstemp(prefix=".auth-", suffix=".tmp",
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def password_configured():
    return bool(_load().get("password_hash"))


def set_password(password):
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    with _lock:
        data = _load()
        data["password_hash"] = generate_password_hash(password)
        # Rotating the key signs out every existing session.
        data["secret_key"] = secrets.token_hex(32)
        _save(data)


def _secret_key():
    with _lock:
        data = _load()
        if not data.get("secret_key"):
            data["secret_key"] = secrets.token_hex(32)
            _save(data)
        return data["secret_key"]


_key_cache = {"mtime": None, "key": None}


def _current_key():
    """Signing key, re-read whenever auth.json changes, so a password change
    from the CLI signs out live sessions without restarting the app."""
    try:
        mtime = os.stat(_auth_path()).st_mtime_ns
    except OSError:
        mtime = None
    if mtime is None or mtime != _key_cache["mtime"] or not _key_cache["key"]:
        _key_cache["key"] = _secret_key()
        try:
            _key_cache["mtime"] = os.stat(_auth_path()).st_mtime_ns
        except OSError:
            _key_cache["mtime"] = None
    return _key_cache["key"]


def _throttled(addr):
    count, first = _failures.get(addr, (0, 0.0))
    if count >= _MAX_FAILURES and time.time() - first < _LOCKOUT_SECONDS:
        return True
    if time.time() - first >= _LOCKOUT_SECONDS:
        _failures.pop(addr, None)
    return False


def _record_failure(addr):
    count, first = _failures.get(addr, (0, time.time()))
    _failures[addr] = (count + 1, first)


def verify(addr, password):
    """(ok, error message)."""
    with _lock:
        if _throttled(addr):
            return False, "Too many attempts. Wait a minute and try again."
        data = _load()
        stored = data.get("password_hash")
        if not stored:
            return False, "No operator password is set on this device yet."
        if check_password_hash(stored, password or ""):
            _failures.pop(addr, None)
            return True, None
        _record_failure(addr)
        return False, "Incorrect password."


def init_app(app, render_login):
    """Install the login guard. render_login(error, configured) -> response."""
    from flask import jsonify, redirect, request, session, url_for
    from flask.sessions import SecureCookieSessionInterface

    class _RotatingKeySessions(SecureCookieSessionInterface):
        def get_signing_serializer(self, app_):
            app_.secret_key = _current_key()
            return super().get_signing_serializer(app_)

    app.session_interface = _RotatingKeySessions()
    app.secret_key = _current_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="watchdog_session",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
    )
    open_endpoints = {"login", "logout", "healthz", "static"}

    @app.before_request
    def _require_operator():
        if request.endpoint in open_endpoints:
            return None
        if request.remote_addr in ("127.0.0.1", "::1"):
            return None
        if session.get("operator"):
            return None
        wants_html = (request.method == "GET" and
                      "text/html" in (request.headers.get("Accept") or ""))
        if wants_html:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return jsonify({"error": "operator login required"}), 401

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            ok, err = verify(request.remote_addr, request.form.get("password"))
            if ok:
                session.clear()
                session["operator"] = True
                session.permanent = True
                nxt = request.args.get("next") or "/"
                # Only same-site relative targets: never an open redirect.
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = "/"
                return redirect(nxt)
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

#!/usr/bin/env python3
"""Locate the robot's onboard service (go2_service on the backpack Orin).

The Orin's address changes with the WiFi network: static 192.168.50.207 on the
Cradlepoint, DHCP (historically 10.0.0.57) on the home network, and a ZeroTier
address that survives both. Fifteen hardcoded literals meant every venue change
broke the dashboard until someone sed-ed them. This module is the single place
the address is decided.

    from robot_host import robot_host
    robot_host.service_url()          -> "http://192.168.50.207:5001"
    robot_host.rtsp_url("color")      -> "rtsp://192.168.50.207:8554/color"
    robot_host.host()                 -> "192.168.50.207"

Resolution order: ORIN_HOST env var (pinned, no probing) -> candidates from
config.yaml go2.host_candidates -> built-in defaults. Each candidate is probed
on :5001/status with a short timeout; the first that answers is cached and
re-verified periodically, or immediately after a caller reports a failure.
If nothing answers, the last known (or first) candidate is returned so URLs
still build and the normal error paths run.
"""
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

_DEFAULT_CANDIDATES = [
    "192.168.50.207",   # Cradlepoint "Smart Robotics Lan" (static)
    "10.0.0.57",        # home "SmartRoboticsLan" (DHCP; may change)
    "192.168.193.111",  # ZeroTier - network-independent fallback
]
SERVICE_PORT = 5001
# The robot link serves HTTPS with a certificate from the Watch Dog demo CA.
# Verifying it proves we talk to OUR Orin (a look-alike host on the WiFi can't
# answer discovery, and never receives the control token). Plain HTTP only if
# explicitly configured (WATCHDOG_ROBOT_SCHEME=http, e.g. a legacy box).
SERVICE_SCHEME = os.environ.get("WATCHDOG_ROBOT_SCHEME", "https")
ROBOT_CA = os.environ.get("WATCHDOG_ROBOT_CA", "")


def _verify():
    """requests 'verify' value: the pinned demo CA (never the system store)."""
    return ROBOT_CA if ROBOT_CA else True
RTSP_PORT = 8554
_PROBE_TIMEOUT = 1.2
_RECHECK_SECONDS = 60.0


def _config_candidates():
    """Optional operator override list from config.yaml (go2.host_candidates)."""
    try:
        from config import get_config  # honours WATCHDOG_CONFIG / overlay
        cfg = get_config().config or {}
        c = (cfg.get("go2") or {}).get("host_candidates")
        if isinstance(c, list) and c:
            return [str(x) for x in c]
    except Exception:
        pass
    return []


class RobotHost:
    def __init__(self):
        self._lock = threading.Lock()
        self._host = None
        self._checked = 0.0
        self._reprobing = False

    def candidates(self):
        pinned = os.environ.get("ORIN_HOST", "").strip()
        if pinned:
            return [pinned]
        seen, out = set(), []
        for h in _config_candidates() + _DEFAULT_CANDIDATES:
            if h not in seen:
                seen.add(h); out.append(h)
        return out

    @staticmethod
    def _alive(host):
        try:
            r = requests.get(f"{SERVICE_SCHEME}://{host}:{SERVICE_PORT}/status",
                             timeout=_PROBE_TIMEOUT, verify=_verify())
            return r.status_code == 200
        except Exception:
            return False

    def resolve(self, force=False):
        # Snapshot state under the lock, then probe WITHOUT holding it. Probing can
        # take (candidates x timeout) seconds when addresses are dead; holding the
        # lock across that would serialize every Flask request behind the resolver.
        with self._lock:
            now = time.time()
            if (not force and self._host
                    and now - self._checked < _RECHECK_SECONDS):
                return self._host
            prev = self._host
        order = self.candidates()
        if prev in order:
            order = [prev] + [h for h in order if h != prev]
        winner = None
        for h in order:
            if self._alive(h):
                winner = h
                break
        with self._lock:
            if winner:
                if winner != self._host:
                    logger.warning("[RobotHost] robot service resolved at %s%s", winner,
                                   f" (was {self._host})" if self._host else "")
                self._host = winner
            elif not self._host:
                self._host = order[0]
                logger.warning("[RobotHost] no candidate answered; using %s", self._host)
            self._checked = time.time()
            return self._host

    def report_failure(self):
        """Callers hit a connection error - force a re-probe on next resolve()."""
        with self._lock:
            self._checked = 0.0

    # ---- convenience --------------------------------------------------
    def host(self):
        return self.resolve()

    def service_url(self):
        return f"{SERVICE_SCHEME}://{self.resolve()}:{SERVICE_PORT}"

    def cached_service_url(self):
        """URL of the last resolved robot WITHOUT probing (None if none yet), for
        the drive path: discovery never runs inside a Move's deadline. A due
        re-check is started in the background instead."""
        with self._lock:
            host = self._host
            due = time.time() - self._checked >= _RECHECK_SECONDS
            start = (due or host is None) and not self._reprobing
            if start:
                self._reprobing = True
        if start:
            threading.Thread(target=self._background_resolve, daemon=True, name="robot-resolve").start()
        return f"{SERVICE_SCHEME}://{host}:{SERVICE_PORT}" if host else None

    def _background_resolve(self):
        try:
            self.resolve()
        finally:
            with self._lock:
                self._reprobing = False

    def rtsp_url(self, channel="color"):
        return f"rtsp://{self.resolve()}:{RTSP_PORT}/{channel}"


robot_host = RobotHost()


# ── Authenticated, keep-alive HTTP to the robot link (go2_service on the Orin) ──
# Command endpoints on the Orin require a control token (only the Thor holds it,
# so other dashboards are view-only). One pooled session keeps TCP connections
# alive, so a D-pad Move doesn't pay a new handshake every 150 ms.
_session = None
_session_lock = threading.Lock()


def _control_token():
    tok = os.environ.get("WATCHDOG_ROBOT_TOKEN", "").strip()
    path = os.environ.get("WATCHDOG_ROBOT_TOKEN_FILE", "")
    if not tok and path:
        try:
            with open(path) as f:
                tok = f.read().strip()
        except OSError:
            tok = ""
    return tok


def _make_session(with_token):
    import requests
    from requests.adapters import HTTPAdapter
    sess = requests.Session()
    ad = HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=0)
    sess.mount("http://", ad)
    sess.mount("https://", ad)
    sess.verify = _verify()
    if with_token:
        tok = _control_token()
        if tok and tok.isascii() and not any(c.isspace() for c in tok):
            sess.headers["Authorization"] = "Bearer " + tok
    return sess


_public = None


def http():
    """Control session: pooled keep-alive, CA-verified, WITH the control token.
    Use only for command endpoints."""
    global _session
    with _session_lock:
        if _session is None:
            _session = _make_session(True)
        return _session


def public():
    """Read-only session (status/battery/video): CA-verified, NO token, so the
    credential never travels on reads."""
    global _public
    with _session_lock:
        if _public is None:
            _public = _make_session(False)
        return _public


# Reachable from the shared resolver object too (web_app imports the instance).
RobotHost.http = staticmethod(http)
RobotHost.public = staticmethod(public)

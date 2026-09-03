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
RTSP_PORT = 8554
_PROBE_TIMEOUT = 1.2
_RECHECK_SECONDS = 60.0


def _config_candidates():
    """Optional operator override list from config.yaml (go2.host_candidates)."""
    try:
        import yaml
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "config.yaml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
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
            r = requests.get(f"http://{host}:{SERVICE_PORT}/status", timeout=_PROBE_TIMEOUT)
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
        return f"http://{self.resolve()}:{SERVICE_PORT}"

    def rtsp_url(self, channel="color"):
        return f"rtsp://{self.resolve()}:{RTSP_PORT}/{channel}"


robot_host = RobotHost()

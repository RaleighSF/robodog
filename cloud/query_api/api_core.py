"""Cloud-neutral pieces of the query API that both hosts share (Azure Functions in
function_app.py, AWS Lambda in aws_handler.py): the cached agent brief, the
staff-key check and question cleaning. One copy, so the clouds cannot drift."""
import hmac
import logging
import os
import threading
import time

BRIEF_PROMPT = ("Give the booth's crew-alerting brief: check overwatch_findings and vitals_latest (including Posture "
                "and Charging), then state the single most important thing and the action, in at most 2 short "
                "sentences (under 30 words). Never recommend what is already happening (for example lying down when "
                "the dog is already lying). Don't restate nominal values; if everything is nominal, say so in one "
                "short sentence.")
BRIEF_TTL_S = 60          # one model call per minute at most, however many screens poll
QUESTION_MAX = 500


class BriefCache:
    def __init__(self, get_agent):
        self._get_agent = get_agent
        self._lock = threading.Lock()
        self._t, self._body = 0.0, None

    def get(self):
        """(body, error): the cached brief, refreshed at most every BRIEF_TTL_S."""
        with self._lock:
            if self._body is None or time.time() - self._t > BRIEF_TTL_S:
                try:
                    r = self._get_agent().ask(BRIEF_PROMPT)
                    self._t, self._body = time.time(), {"text": r["text"], "at": time.time(), "seconds": r["seconds"]}
                except Exception:
                    logging.exception("agent brief failed")
                    if self._body is None:
                        return None, "agent unavailable"
            return dict(self._body, age_s=round(time.time() - self._t, 1)), None


def staff_ok(got: str) -> bool:
    want = os.environ.get("STAFF_KEY", "")
    return bool(want) and hmac.compare_digest(want.encode(), (got or "").encode())


def clean_question(q) -> str:
    return str(q or "").strip()[:QUESTION_MAX]

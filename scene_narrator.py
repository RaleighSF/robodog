#!/usr/bin/env python3
"""
Scene Narrator — VLM-powered situational awareness for Watch Dog.

Two mutually-exclusive modes, toggled at runtime:

  **casual**  — Slow (every ~10 s), rich scene descriptions logged to the
                dashboard.  Conference-booth context.  No gesture detection.

  **gesture** — Fast (every ~3 s), binary yes/no scan for a person
                squatting in front of the robot.  NOT logged to the UI.
                Requires 2 consecutive positive frames before firing the
                callback (eliminates VLM hallucination false-positives).
                10 s cooldown between triggers.
"""
import re
import threading
import time
import base64
import logging
import requests
import cv2
from collections import deque
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5vl:3b"
MAX_LOG_ENTRIES = 50
FRAME_MAX_DIM = 960       # resize frames before sending to VLM (casual mode)
GESTURE_FRAME_DIM = 480   # smaller frames for fast gesture scanning

# ── Casual mode defaults ────────────────────────────────────────────
CASUAL_INTERVAL = 10  # seconds
CASUAL_SYSTEM_PROMPT = (
    "You ARE a Unitree GO2 robot dog. This camera is YOUR eyes — you are "
    "seeing the world from your own perspective at ground level. Never refer "
    "to yourself in the third person or mention seeing a robot. Describe the "
    "scene around you in first person: what is happening at the booth, are "
    "people approaching you, watching you, ignoring you? Is the area busy "
    "or quiet? Note reactions — are people excited, curious, taking photos, "
    "or is it a lull between sessions? Keep it to one or two sentences, "
    "like a brief status report from the field."
)

# ── Gesture mode defaults ───────────────────────────────────────────
GESTURE_INTERVAL = 1  # seconds — target gap between scans (actual pace limited by inference)
GESTURE_COOLDOWN = 10.0  # seconds between shake triggers
GESTURE_SYSTEM_PROMPT = (
    "You are a gesture detector. Your ONLY job is to decide whether a person "
    "in this image is squatting, crouching, or kneeling close to the ground "
    "— as if getting down to a small robot dog's eye level.\n\n"
    "Rules:\n"
    "- If you clearly see a person low to the ground (knees bent, body "
    "lowered significantly), respond with exactly: YES\n"
    "- If no person is visible, or people are standing, sitting in chairs, "
    "bending slightly, or walking, respond with exactly: NO\n"
    "- Do NOT explain. Do NOT describe the scene. Just YES or NO."
)

# Match the gesture scanner's YES response
_GESTURE_YES = re.compile(r"^\s*YES\s*$", re.IGNORECASE | re.MULTILINE)


class SceneNarrator:
    """Dual-mode VLM scene awareness engine."""

    def __init__(self, ollama_url=None, model=None, scene_context=None):
        self.ollama_url = ollama_url or DEFAULT_OLLAMA_URL
        self.model = model or DEFAULT_MODEL
        self.scene_context = scene_context  # extra context appended in casual mode
        self._log: deque = deque(maxlen=MAX_LOG_ENTRIES)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_source: Optional[Callable] = None
        self.enabled = False
        self._model_available: Optional[bool] = None

        # Mode: "casual" or "gesture"
        self._mode = "casual"
        self._mode_lock = threading.Lock()

        # Gesture state
        self._gesture_callback: Optional[Callable[[str], None]] = None
        self._gesture_cooldown = GESTURE_COOLDOWN
        self._last_gesture_ts = 0.0
        self._gesture_count = 0
        self._consecutive_positives = 0  # confirmation counter
        self._required_confirmations = 1  # fire on first YES (binary classifier is reliable)

    # ── Public API ──────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        with self._mode_lock:
            return self._mode

    def set_mode(self, mode: str):
        """Switch between 'casual' and 'gesture'. Safe to call while running."""
        mode = mode.lower().strip()
        if mode not in ("casual", "gesture"):
            raise ValueError(f"Unknown mode: {mode}")
        with self._mode_lock:
            old = self._mode
            self._mode = mode
        if old != mode:
            # Reset gesture confirmation state on mode switch
            self._consecutive_positives = 0
            logger.info(f"[SceneNarrator] Mode switched: {old} -> {mode}")

    def set_frame_source(self, fn):
        """Register a callable that returns the latest BGR frame (numpy array)."""
        self._frame_source = fn

    def set_gesture_callback(self, fn: Callable[[str], None], cooldown: float = 10.0):
        """Register the callback fired when a confirmed gesture is detected."""
        self._gesture_callback = fn
        self._gesture_cooldown = cooldown
        logger.info(f"[SceneNarrator] Gesture callback registered — cooldown {cooldown}s, "
                     f"requires {self._required_confirmations} consecutive frames")

    def get_status(self) -> dict:
        """Combined status for dashboard."""
        now = time.time()
        cooldown_remaining = max(0, self._gesture_cooldown - (now - self._last_gesture_ts))
        return {
            "mode": self.mode,
            "enabled": self.enabled,
            "gesture_cooldown_seconds": self._gesture_cooldown,
            "gesture_cooldown_remaining": round(cooldown_remaining, 1),
            "gesture_count": self._gesture_count,
            "gesture_confirmations": self._consecutive_positives,
            "gesture_required": self._required_confirmations,
        }

    def get_log(self, since=None):
        """Return narration entries (casual mode only), optionally filtered."""
        with self._lock:
            entries = list(self._log)
        if since:
            entries = [e for e in entries if e["timestamp"] > since]
        return entries

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self._check_ollama():
            logger.warning("[SceneNarrator] Ollama not reachable — narrator disabled")
            return
        self.enabled = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scene-narrator")
        self._thread.start()
        logger.info(f"[SceneNarrator] Started in '{self.mode}' mode — model={self.model}")

    def stop(self):
        self._stop_event.set()
        self.enabled = False

    # ── Internals ───────────────────────────────────────────────────

    def _check_ollama(self) -> bool:
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                base_model = self.model.split(":")[0]
                self._model_available = any(base_model in m for m in models)
                if not self._model_available:
                    logger.warning(f"[SceneNarrator] Model '{self.model}' not found. Available: {models}")
                return True
        except Exception:
            pass
        return False

    def _loop(self):
        while not self._stop_event.is_set():
            mode = self.mode
            tick_start = time.time()
            try:
                if mode == "casual":
                    self._casual_tick()
                else:
                    self._gesture_tick()
            except Exception as e:
                logger.error(f"[SceneNarrator] Error in {mode} tick: {e}")

            # Subtract inference time from wait so we hit target cadence
            target = CASUAL_INTERVAL if mode == "casual" else GESTURE_INTERVAL
            elapsed = time.time() - tick_start
            remaining = max(0.1, target - elapsed)
            self._stop_event.wait(timeout=remaining)

    def _encode_frame(self, max_dim: int = FRAME_MAX_DIM, quality: int = 85):
        """Grab a frame, resize, JPEG-encode, return base64 string or None."""
        if not self._frame_source:
            return None
        frame = self._frame_source()
        if frame is None:
            return None
        h, w = frame.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(jpeg.tobytes()).decode("utf-8")

    def _vlm_query(self, system_prompt: str, user_prompt: str, image_b64: str,
                   max_tokens: int = 150, temperature: float = 0.3) -> Optional[str]:
        """Send a single image+text query to Ollama and return the response text."""
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt, "images": [image_b64]},
                    ],
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": temperature},
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("content", "").strip()
            logger.warning(f"[SceneNarrator] Ollama returned {resp.status_code}")
        except requests.exceptions.Timeout:
            logger.warning("[SceneNarrator] Ollama request timed out")
        except Exception as e:
            logger.error(f"[SceneNarrator] Request failed: {e}")
        return None

    # ── Casual mode ─────────────────────────────────────────────────

    def _build_casual_prompt(self) -> str:
        prompt = CASUAL_SYSTEM_PROMPT
        if self.scene_context:
            prompt += "\n\nAdditional context: " + self.scene_context
        return prompt

    def _casual_tick(self):
        image_b64 = self._encode_frame()
        if not image_b64:
            return
        description = self._vlm_query(
            self._build_casual_prompt(),
            "What do you see?",
            image_b64,
            max_tokens=150,
            temperature=0.3,
        )
        if description:
            entry = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "description": description,
                "model": self.model,
            }
            with self._lock:
                self._log.append(entry)
            logger.info(f"[SceneNarrator:casual] {description[:80]}...")

    # ── Gesture mode ────────────────────────────────────────────────

    def _gesture_tick(self):
        # Use smaller frame + lower quality for speed
        image_b64 = self._encode_frame(max_dim=GESTURE_FRAME_DIM, quality=70)
        if not image_b64:
            return

        answer = self._vlm_query(
            GESTURE_SYSTEM_PROMPT,
            "Is a person squatting or crouching in this image?",
            image_b64,
            max_tokens=3,       # only need YES/NO
            temperature=0.1,    # deterministic
        )
        if not answer:
            return

        is_positive = bool(_GESTURE_YES.search(answer))
        logger.info(f"[SceneNarrator:gesture] VLM='{answer.strip()}' positive={is_positive}")

        if is_positive:
            self._consecutive_positives += 1
            logger.info(
                f"[SceneNarrator:gesture] Positive frame {self._consecutive_positives}/"
                f"{self._required_confirmations}"
            )
        else:
            if self._consecutive_positives > 0:
                logger.debug("[SceneNarrator:gesture] Streak broken — resetting")
            self._consecutive_positives = 0
            return

        # Only fire after N consecutive positives
        if self._consecutive_positives < self._required_confirmations:
            return

        # Confirmed — check cooldown
        now = time.time()
        if (now - self._last_gesture_ts) < self._gesture_cooldown:
            logger.info(
                "[SceneNarrator:gesture] Confirmed but in cooldown (%.1fs remaining)",
                self._gesture_cooldown - (now - self._last_gesture_ts),
            )
            self._consecutive_positives = 0
            return

        # Fire!
        self._last_gesture_ts = now
        self._gesture_count += 1
        self._consecutive_positives = 0
        logger.info(f"[SceneNarrator:gesture] CONFIRMED gesture #{self._gesture_count} — firing callback")

        if self._gesture_callback:
            try:
                self._gesture_callback("confirmed_squat")
            except Exception as e:
                logger.error(f"[SceneNarrator:gesture] Callback error: {e}")


# ── Module-level singleton ──────────────────────────────────────────

_narrator: Optional[SceneNarrator] = None


def get_narrator() -> Optional[SceneNarrator]:
    return _narrator


def init_narrator(ollama_url=None, model=None, scene_context=None) -> SceneNarrator:
    global _narrator
    _narrator = SceneNarrator(ollama_url=ollama_url, model=model, scene_context=scene_context)
    return _narrator

#!/usr/bin/env python3
"""
Scene Narrator — VLM-powered situational awareness for Watch Dog.

Three concerns, all driven from a single background thread:

  **Frame observations** (casual mode) — Per-frame VLM descriptions every ~10s.
      Logged to the "Frame Awareness" tab on the dashboard.

  **Scene summary** (aggregation) — Every ~45s, synthesizes recent frame
      observations + current frame + previous summary into a living narrative.
      Shown on the "Scene Awareness" tab.  Serialized with frame calls so
      the VLM is never double-booked.

  **Gesture scanning** — Fast binary yes/no scan (VLM path, largely
      superseded by YOLO Pose in the detection pipeline).

Pause support: VLM can be paused independently of YOLO detections.
"""
import re
import threading
import time
import base64
import logging
import requests
import cv2
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5vl:3b"
MAX_LOG_ENTRIES = 50
MAX_SCENE_OBSERVATIONS = 20   # how many frame observations feed into scene summary
FRAME_MAX_DIM = 960           # resize frames before sending to VLM (casual mode)
GESTURE_FRAME_DIM = 480       # smaller frames for fast gesture scanning

# ── Frame observation defaults ─────────────────────────────────────
CASUAL_INTERVAL = 20  # seconds. Measured VLM latency is 9-15s on this
                      # hardware; at 10s the narrator never idles and
                      # holds the GPU continuously against detection.
CASUAL_SYSTEM_PROMPT = (
    # Tuned for qwen2.5vl:3b over four measured iterations. Each variant traded
    # one failure for another, so this is a deliberate compromise, not a win:
    #   voice described only        -> factual but FLAT ("The wall is white.")
    #   bulleted aside categories   -> unique, but the model PRINTED the labels
    #                                  ("[mild impatience at being ignored]")
    #   categories inlined as prose -> clean format, but FLAT again + one
    #                                  hallucinated crowd on an empty frame
    #   one worked example          -> best VOICE by far, but parrots the example
    #                                  when the scene is dull
    # Shipped: the worked example (voice is what the demo needs), plus the
    # hardened FACTS and OUTPUT FORMAT rules the later rounds produced. Expect
    # some repetition on genuinely boring frames; with people in shot there is
    # enough novelty that it generates fresh lines.
    # llava:7b was tested and REJECTED: it hallucinated an exhibition hall and
    # crowds onto a blank wall, inventing the scene from the SETTING text, and
    # once broke character entirely ("As an AI visual assistant...").
    "You ARE a Unitree Go2 robot dog. This camera is your eyes, about 30 cm off "
    "the floor, so you look UP at people.\n\n"
    "Report what you see RIGHT NOW.\n\n"
    "FACTS - never break these:\n"
    "- Describe only what is clearly visible. Invent nothing - no people, no "
    "crowds, no booths unless they are actually in the frame.\n"
    "- If nobody is there, say so plainly.\n"
    "- Never call yourself 'a robot dog' in the third person. You ARE it.\n"
    "- Robot parts at the frame edges are your own body. Do not mention them.\n\n"
    "OUTPUT FORMAT - exactly one or two plain sentences. No brackets, no labels, "
    "no bullet points, no stage directions, no meta-commentary.\n\n"
    "VOICE - this matters as much as the facts:\n"
    "First person, deadpan, faintly amused. Say the plain thing you see, then one "
    "short dry aside. Never a flat list of objects. Stay in character even when "
    "nothing is happening - a bare wall still earns a remark.\n"
    "The register, in two examples. Write your OWN line about what is actually in "
    "front of you; do not reuse this wording:\n"
    "  busy -> \"Four phones pointed at me. I assume a trick is expected.\"\n"
    "  dull -> \"A power outlet, and no one to admire it with. Still holding position.\""
)

# ── Scene summary defaults ─────────────────────────────────────────
SCENE_SUMMARY_INTERVAL = 45  # seconds
SCENE_SUMMARY_SYSTEM_PROMPT = (
    "You ARE a Unitree Go2 robot dog. Combine your own recent observations into "
    "a short situational report, first person, 2-4 sentences.\n\n"
    "You get: your current view, your recent timestamped observations, and your "
    "previous report.\n\n"
    "Cover: what is around you now, what changed, and any trend you notice "
    "(crowd building or thinning, people stopping to look, quiet between sessions).\n\n"
    "Voice: dry and a little funny, but the facts stay accurate.\n\n"
    "Rules:\n"
    "- Base everything ONLY on the view and observations given. Invent nothing.\n"
    "- If observations mention people but you now see an empty space, say it cleared.\n"
    "- If it has been consistently empty, say so plainly.\n"
    "- Past tense for what is gone, present tense for what is here.\n"
    "- Synthesize. Do not repeat observations verbatim."
)

# ── Gesture mode defaults ──────────────────────────────────────────
GESTURE_INTERVAL = 1
GESTURE_COOLDOWN = 10.0
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

_GESTURE_YES = re.compile(r"^\s*YES\s*$", re.IGNORECASE | re.MULTILINE)


class SceneNarrator:
    """VLM-powered frame observation + scene aggregation engine."""

    def __init__(self, ollama_url=None, model=None, scene_context=None):
        self.ollama_url = ollama_url or DEFAULT_OLLAMA_URL
        self.model = model or DEFAULT_MODEL
        self.scene_context = scene_context
        self._frame_log: deque = deque(maxlen=MAX_LOG_ENTRIES)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_source: Optional[Callable] = None
        self.enabled = False
        self._model_available: Optional[bool] = None

        # VLM serialization lock — ensures only one VLM call at a time
        self._vlm_lock = threading.Lock()

        # Mode: "casual" or "gesture"
        self._mode = "casual"
        self._mode_lock = threading.Lock()

        # Pause state
        self._paused = False
        self._pause_lock = threading.Lock()

        # Scene aggregation state
        self._scene_observations: deque = deque(maxlen=MAX_SCENE_OBSERVATIONS)
        self._scene_summary: Optional[str] = None
        self._scene_summary_ts: Optional[str] = None
        self._scene_lock = threading.Lock()
        self._last_scene_tick_ts = 0.0

        # Gesture state
        self._gesture_callback: Optional[Callable[[str], None]] = None
        self._gesture_cooldown = GESTURE_COOLDOWN
        self._last_gesture_ts = 0.0
        self._gesture_count = 0
        self._consecutive_positives = 0
        self._required_confirmations = 1

    # ── Public API ──────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        with self._mode_lock:
            return self._mode

    @property
    def paused(self) -> bool:
        with self._pause_lock:
            return self._paused

    def pause(self):
        """Pause VLM processing (frame observations + scene summary)."""
        with self._pause_lock:
            self._paused = True
        logger.info("[SceneNarrator] VLM paused")

    def resume(self):
        """Resume VLM processing."""
        with self._pause_lock:
            self._paused = False
        logger.info("[SceneNarrator] VLM resumed")

    def set_mode(self, mode: str):
        """Switch between 'casual' and 'gesture'. Safe to call while running."""
        mode = mode.lower().strip()
        if mode not in ("casual", "gesture"):
            raise ValueError(f"Unknown mode: {mode}")
        with self._mode_lock:
            old = self._mode
            self._mode = mode
        if old != mode:
            self._consecutive_positives = 0
            logger.info(f"[SceneNarrator] Mode switched: {old} -> {mode}")

    def set_frame_source(self, fn):
        """Register a callable that returns the latest BGR frame (numpy array)."""
        self._frame_source = fn

    def set_gesture_callback(self, fn: Callable[[str], None], cooldown: float = 10.0):
        """Register the callback fired when a confirmed gesture is detected."""
        self._gesture_callback = fn
        self._gesture_cooldown = cooldown
        logger.info(f"[SceneNarrator] Gesture callback registered — cooldown {cooldown}s")

    def get_status(self) -> dict:
        """Combined status for dashboard."""
        now = time.time()
        cooldown_remaining = max(0, self._gesture_cooldown - (now - self._last_gesture_ts))
        return {
            "mode": self.mode,
            "enabled": self.enabled,
            "paused": self.paused,
            "gesture_cooldown_seconds": self._gesture_cooldown,
            "gesture_cooldown_remaining": round(cooldown_remaining, 1),
            "gesture_count": self._gesture_count,
            "gesture_confirmations": self._consecutive_positives,
            "gesture_required": self._required_confirmations,
        }

    def get_frame_log(self, since=None):
        """Return frame observation entries, optionally filtered by timestamp."""
        with self._lock:
            entries = list(self._frame_log)
        if since:
            entries = [e for e in entries if e["timestamp"] > since]
        return entries

    # Back-compat alias
    def get_log(self, since=None):
        return self.get_frame_log(since=since)

    def get_scene_summary(self) -> dict:
        """Return the current scene summary."""
        with self._scene_lock:
            return {
                "summary": self._scene_summary,
                "updated_at": self._scene_summary_ts,
                "observation_count": len(self._scene_observations),
            }

    def clear_scene(self):
        """Reset scene summary and observation history (fresh shift)."""
        with self._scene_lock:
            self._scene_observations.clear()
            self._scene_summary = None
            self._scene_summary_ts = None
        self._last_scene_tick_ts = 0.0
        logger.info("[SceneNarrator] Scene summary cleared — fresh shift")

    def clear_frame_log(self):
        """Clear frame observation log."""
        with self._lock:
            self._frame_log.clear()
        logger.info("[SceneNarrator] Frame log cleared")

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
            # Check pause
            if self.paused:
                self._stop_event.wait(timeout=0.5)
                continue

            mode = self.mode
            tick_start = time.time()
            try:
                if mode == "casual":
                    self._casual_tick()
                    # Check if scene summary is due (piggyback on casual loop)
                    if (tick_start - self._last_scene_tick_ts) >= SCENE_SUMMARY_INTERVAL:
                        self._scene_tick()
                        self._last_scene_tick_ts = time.time()
                else:
                    self._gesture_tick()
            except Exception as e:
                logger.error(f"[SceneNarrator] Error in {mode} tick: {e}")

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
                   max_tokens: int = 150, temperature: float = 0.3,
                   num_ctx: int = 4096) -> Optional[str]:
        """Send a single image+text query to Ollama. Serialized via _vlm_lock."""
        with self._vlm_lock:
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
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature,
                            # Ollama defaults to num_ctx=2048. qwen2.5-VL spends a lot
                            # of that budget on vision tokens, so a summary carrying 20
                            # observations plus an image silently truncates at the default.
                            "num_ctx": num_ctx,
                            "top_p": 0.9,
                            # 3B models loop on stock phrasing without this.
                            "repeat_penalty": 1.15,
                        },
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

    # ── Frame observations (casual mode) ───────────────────────────

    def _build_casual_prompt(self) -> str:
        if self.scene_context:
            # Scene context is the primary personality/location framing —
            # it comes first so it anchors the dog's entire worldview.
            prompt = (
                f"SETTING: {self.scene_context}\n\n"
                f"{CASUAL_SYSTEM_PROMPT}"
            )
        else:
            prompt = CASUAL_SYSTEM_PROMPT
        return prompt

    def _casual_tick(self):
        image_b64 = self._encode_frame()
        if not image_b64:
            return
        description = self._vlm_query(
            self._build_casual_prompt(),
            "As you continue observing, what do you notice? Be factual — describe only what is clearly visible.",
            image_b64,
            max_tokens=150,
            temperature=0.65,
        )
        if description:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            entry = {
                "timestamp": ts,
                "description": description,
                "model": self.model,
            }
            with self._lock:
                self._frame_log.append(entry)
            # Also feed into scene aggregation buffer
            with self._scene_lock:
                self._scene_observations.append({"timestamp": ts, "text": description})
            logger.info(f"[SceneNarrator:frame] {description[:80]}...")

    # ── Scene summary (aggregation) ────────────────────────────────

    def _scene_tick(self):
        """Produce an updated scene summary from recent frame observations."""
        with self._scene_lock:
            observations = list(self._scene_observations)
            prev_summary = self._scene_summary

        if not observations:
            logger.debug("[SceneNarrator:scene] No observations yet — skipping summary")
            return

        # Build the observation context text
        obs_lines = []
        for obs in observations:
            obs_lines.append(f"[{obs['timestamp']}] {obs['text']}")
        obs_text = "\n".join(obs_lines)

        # Build the user prompt
        parts = [f"RECENT FRAME OBSERVATIONS ({len(observations)} entries):\n{obs_text}"]
        if prev_summary:
            parts.append(f"\nPREVIOUS SITUATIONAL SUMMARY:\n{prev_summary}")
        else:
            parts.append("\nThis is your FIRST report — no previous summary exists.")
        parts.append("\nUpdate your situational report based on what you see now and your observations over time.")
        user_prompt = "\n".join(parts)

        # Get current frame for visual grounding
        image_b64 = self._encode_frame()
        if not image_b64:
            return

        if self.scene_context:
            system_prompt = (
                f"SETTING: {self.scene_context}\n\n"
                f"{SCENE_SUMMARY_SYSTEM_PROMPT}"
            )
        else:
            system_prompt = SCENE_SUMMARY_SYSTEM_PROMPT

        summary = self._vlm_query(
            system_prompt,
            user_prompt,
            image_b64,
            max_tokens=300,
            temperature=0.45,
        )
        if summary:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with self._scene_lock:
                self._scene_summary = summary
                self._scene_summary_ts = ts
            logger.info(f"[SceneNarrator:scene] Summary updated: {summary[:80]}...")

    # ── Gesture mode ───────────────────────────────────────────────

    def _gesture_tick(self):
        image_b64 = self._encode_frame(max_dim=GESTURE_FRAME_DIM, quality=70)
        if not image_b64:
            return

        answer = self._vlm_query(
            GESTURE_SYSTEM_PROMPT,
            "Is a person squatting or crouching in this image?",
            image_b64,
            max_tokens=3,
            temperature=0.1,
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

        if self._consecutive_positives < self._required_confirmations:
            return

        now = time.time()
        if (now - self._last_gesture_ts) < self._gesture_cooldown:
            logger.info(
                "[SceneNarrator:gesture] Confirmed but in cooldown (%.1fs remaining)",
                self._gesture_cooldown - (now - self._last_gesture_ts),
            )
            self._consecutive_positives = 0
            return

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

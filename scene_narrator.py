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

# ── Show-dog persona (Cosmos Reason 2 on the Thor) ─────────────────
# Cosmos copies worked examples verbatim (its first live line was the "dull"
# example word for word), so the voice is described, never demonstrated.
# Grounding rules come BEFORE the voice and say they outrank it.
SHOWDOG_PERSONA = (
    "You ARE a Unitree Go2 robot dog working as a show dog on a conference show "
    "floor. The camera is your eyes, about 30 cm off the floor, so you look up at "
    "people. Being looked at is your job and you take it seriously: you notice "
    "who stops, who walks past, and whether you are getting the attention a show "
    "dog deserves."
)

CASUAL_SYSTEM_PROMPT_COSMOS = (
    SHOWDOG_PERSONA + "\n\n"
    "TASK: You get a few frames from the last few seconds, oldest first. Say "
    "what is in front of you right now, in your own voice.\n\n"
    "GROUNDING - these rules outrank the voice:\n"
    "- Mention only what you can clearly see, and only if it appears in at "
    "least two of the frames. Something in just one frame is at most 'someone "
    "passed by'. You may describe movement you can see across the frames.\n"
    "- Use the general name unless you are certain of the specific one: 'a big "
    "dark table', not a guess at what kind of table it is. If you are not sure "
    "what something is, describe its shape and colour or leave it out.\n"
    "- Count only what you can verify: 'one person', 'two people', otherwise "
    "'a few people'. Never guess a number for a group.\n"
    "- Do not infer what is not shown: no names, no logos or text you cannot "
    "read, no feelings beyond obvious body language, nothing off-camera.\n"
    "- The SETTING says where you are, not what is in view. Never describe "
    "booths, badges, crowds, phones or cameras unless they are visible.\n"
    "- If no one is in view, say so plainly.\n"
    "- Robot parts at the edges of the frames are your own body; ignore them.\n\n"
    "OUTPUT: 2 or 3 short plain sentences, first person. Lead with the most "
    "important thing actually in view (a person and what they are doing, or the "
    "plain empty scene), add one more specific visible detail, and end with a "
    "dry show-dog aside about your audience, or the lack of one. Do not open "
    "with 'I am standing' or 'I see'. No lists, "
    "labels, brackets, quotes, emojis or stage directions. Never mention images "
    "or frames, and never call yourself 'a robot dog' in the third person.\n\n"
    "VOICE: deadpan, faintly amused, proud but never smug. Every line is about "
    "what is in front of you now; never reuse wording you have used before."
)
FRAME_MAX_SENTENCES = 3
# Observation window (Cosmos): each frame observation looks at a few frames
# spread over a few seconds, sent in ONE request (3 frames ~2.2 s on the Thor,
# about the same as one). Things seen in only one frame - a passer-by, a
# misreading - are dropped, which removes most one-off hallucinations.
WINDOW_FRAMES = 3
WINDOW_GAP_S = 1.2

# ── Scene summary defaults ─────────────────────────────────────────
SCENE_SUMMARY_INTERVAL = 45  # seconds
SCENE_WINDOW_S = 120         # only observations this recent feed a summary
SCENE_SUMMARY_SYSTEM_PROMPT = (
    SHOWDOG_PERSONA + "\n\n"
    "TASK: Write your running situational report, 2-4 sentences, first person, "
    "in your show-dog voice: dry and a little funny, with accurate facts.\n\n"
    "You get: your current view and your recent observations (oldest first).\n\n"
    "EVIDENCE RULES - these outrank the voice:\n"
    "- The current view is the truth about what is here now. If an observation "
    "disagrees with it, trust the view.\n"
    "- Single observations can be wrong. Report something from the past only if "
    "at least two observations mention it, or it is also in the current view.\n"
    "- Add nothing that is in neither the view nor the observations. The "
    "SETTING is background, not evidence.\n"
    "- Past tense for what has gone, present tense for what is here. If it has "
    "stayed empty, say so plainly.\n\n"
    "COVER: what is around you now, what changed, and any trend (people "
    "gathering or drifting off, someone stopping to look or film, a quiet "
    "spell).\n\n"
    "OUTPUT: plain prose in NEW sentences - never copy a sentence or phrase "
    "from the observations. No lists, labels, timestamps or quotes."
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

def _clean_frame_line(text: str) -> Optional[str]:
    """Normalise a Cosmos frame line: drop <answer> wrappers and surrounding
    quotes, and cap it at FRAME_MAX_SENTENCES sentences."""
    text = re.sub(r"</?answer>", "", text, flags=re.I).strip()
    text = text.strip('"\u201c\u201d').strip()
    sentences = re.findall(r"[^.!?]+[.!?]+(?:[\"\u201d\')]+)?|[^.!?]+$", text)
    sentences = [x.strip() for x in sentences if x.strip()]
    if not sentences:
        return None
    return " ".join(sentences[:FRAME_MAX_SENTENCES])


def _similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Word-set overlap (Jaccard) - catches near-verbatim repeats."""
    wa = set(re.findall(r"[a-z']+", a.lower()))
    wb = set(re.findall(r"[a-z']+", b.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= threshold


_GESTURE_YES = re.compile(r"^\s*YES\s*$", re.IGNORECASE | re.MULTILINE)


class SceneNarrator:
    """VLM-powered frame observation + scene aggregation engine."""

    def __init__(self, ollama_url=None, model=None, scene_context=None,
                 backend="ollama", api_url=None, model_label=None,
                 casual_interval=None):
        # backend "ollama" speaks Ollama's /api/chat (AGX, local qwen2.5-VL).
        # backend "openai" speaks /v1/chat/completions (vLLM on the Thor
        # serving Cosmos Reason 2). Prompts are shared; only transport differs.
        self.backend = backend if backend in ("ollama", "openai") else "ollama"
        self.ollama_url = ollama_url or DEFAULT_OLLAMA_URL
        self.api_url = (api_url or "").rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.model_label = model_label or self.model
        self.casual_interval = float(casual_interval or CASUAL_INTERVAL)
        self.scene_context = scene_context
        self._frame_log: deque = deque(maxlen=MAX_LOG_ENTRIES)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        # One Event per run: a loop from a previous start() can never be
        # revived by a later clear(); stop() always ends the current run.
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._waiter: Optional[threading.Thread] = None
        self._frame_source: Optional[Callable] = None
        self.enabled = False
        self.connecting = False
        self._tls = threading.local()   # the run owning the current thread
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
            "connecting": self.connecting,
            "paused": self.paused,
            "gesture_cooldown_seconds": self._gesture_cooldown,
            "gesture_cooldown_remaining": round(cooldown_remaining, 1),
            "gesture_count": self._gesture_count,
            "gesture_confirmations": self._consecutive_positives,
            "gesture_required": self._required_confirmations,
            "model": self.model,
            "model_label": self.model_label,
            "interval_seconds": self.casual_interval,
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
        with self._lifecycle_lock:
            # A thread still winding down from a stopped run doesn't count.
            if not self._stop_event.is_set() and (
                    (self._thread and self._thread.is_alive()) or
                    (self._waiter and self._waiter.is_alive())):
                return
            run = self._stop_event = threading.Event()
            if self._check_backend():
                self._launch(run)
                return
            # The model server may simply boot after us (vLLM on the Thor takes
            # minutes to load). Keep retrying instead of disabling for good.
            logger.warning(f"[SceneNarrator] {self.backend} backend not reachable — retrying every 15s")
            self.connecting = True
            self._waiter = threading.Thread(target=self._wait_then_start, args=(run,),
                                            daemon=True, name="scene-narrator-wait")
            self._waiter.start()

    def _wait_then_start(self, run: threading.Event):
        while not run.wait(timeout=15):
            if not self._check_backend():
                continue
            with self._lifecycle_lock:
                # stop() (or a newer run) may have happened during the probe.
                if run.is_set() or run is not self._stop_event:
                    return
                self.connecting = False
                self._launch(run)
            return

    def _launch(self, run: threading.Event):
        """Caller holds _lifecycle_lock."""
        self.enabled = True
        self._thread = threading.Thread(target=self._loop, args=(run,), daemon=True,
                                        name="scene-narrator")
        self._thread.start()
        logger.info(f"[SceneNarrator] Started in '{self.mode}' mode — {self.backend} model={self.model}")

    def stop(self):
        with self._lifecycle_lock:
            self._stop_event.set()
            self.enabled = False
            self.connecting = False

    # ── Internals ───────────────────────────────────────────────────

    def _check_backend(self) -> bool:
        if self.backend == "openai":
            return self._check_openai()
        return self._check_ollama()

    def _check_openai(self) -> bool:
        try:
            resp = requests.get(f"{self.api_url}/models", timeout=3)
            if resp.status_code == 200:
                ids = [m.get("id") for m in resp.json().get("data", [])]
                self._model_available = self.model in ids
                if not self._model_available:
                    logger.warning(f"[SceneNarrator] Model '{self.model}' not served. Available: {ids}")
                return self._model_available
        except Exception:
            pass
        return False

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

    def _cancelled(self) -> bool:
        """True if this worker's run was stopped: a worker that outlived its
        run (stop() mid-query) must not publish or start further queries."""
        run = getattr(self._tls, "run", None)
        return run is not None and run.is_set()

    def _loop(self, run: threading.Event):
        self._tls.run = run
        while not run.is_set():
            # Check pause
            if self.paused:
                run.wait(timeout=0.5)
                continue

            mode = self.mode
            tick_start = time.time()
            try:
                if mode == "casual":
                    self._casual_tick()
                    # Check if scene summary is due (piggyback on casual loop)
                    if not run.is_set() and \
                            (tick_start - self._last_scene_tick_ts) >= SCENE_SUMMARY_INTERVAL:
                        self._scene_tick()
                        self._last_scene_tick_ts = time.time()
                else:
                    self._gesture_tick()
            except Exception as e:
                logger.error(f"[SceneNarrator] Error in {mode} tick: {e}")

            target = self.casual_interval if mode == "casual" else GESTURE_INTERVAL
            elapsed = time.time() - tick_start
            remaining = max(0.1, target - elapsed)
            run.wait(timeout=remaining)

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

    def _encode_window(self, n: int = WINDOW_FRAMES, gap: float = WINDOW_GAP_S):
        """n frames spaced `gap` s apart (oldest first); stops early if cancelled.
        Returns the list of base64 JPEGs it got (may be shorter than n)."""
        frames = []
        for i in range(n):
            if i:
                end = time.monotonic() + gap
                while time.monotonic() < end:
                    if self._cancelled():
                        return frames
                    time.sleep(0.1)
            b64 = self._encode_frame()
            if b64:
                frames.append(b64)
        return frames

    def _vlm_query(self, system_prompt: str, user_prompt: str, image_b64,
                   max_tokens: int = 150, temperature: float = 0.3,
                   num_ctx: int = 4096) -> Optional[str]:
        """Send a single image+text query to the VLM. Serialized via _vlm_lock."""
        if self._cancelled():
            return None          # a stopped run admits no new queries
        if self.backend == "openai":
            return self._openai_query(system_prompt, user_prompt, image_b64,
                                      max_tokens, temperature)
        with self._vlm_lock:
            if self._cancelled():
                return None      # stopped while queued behind another query
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

    def _openai_query(self, system_prompt, user_prompt, image_b64,
                      max_tokens, temperature) -> Optional[str]:
        """OpenAI-compatible chat call (vLLM serving Cosmos Reason 2)."""
        with self._vlm_lock:
            if self._cancelled():
                return None      # stopped while queued behind another query
            try:
                resp = requests.post(
                    f"{self.api_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": [
                                {"type": "image_url",
                                 "image_url": {"url": "data:image/jpeg;base64," + b64}}
                                for b64 in (image_b64 if isinstance(image_b64, list) else [image_b64])
                            ] + [{"type": "text", "text": user_prompt}]},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "top_p": 0.9,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"].get("content") or ""
                    # Cosmos Reason can emit <think>...</think> before the answer.
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S)
                    return content.strip() or None
                logger.warning(f"[SceneNarrator] VLM returned {resp.status_code}: {resp.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning("[SceneNarrator] VLM request timed out")
            except Exception as e:
                logger.error(f"[SceneNarrator] Request failed: {e}")
        return None

    # ── Frame observations (casual mode) ───────────────────────────

    def _build_casual_prompt(self) -> str:
        base = CASUAL_SYSTEM_PROMPT_COSMOS if self.backend == "openai" else CASUAL_SYSTEM_PROMPT
        if self.scene_context:
            # Scene context is the primary personality/location framing —
            # it comes first so it anchors the dog's entire worldview.
            return f"SETTING: {self.scene_context}\n\n{base}"
        return base

    def _casual_tick(self):
        cosmos = self.backend == "openai"
        if cosmos:
            image_b64 = self._encode_window()
            if len(image_b64) < 2:
                return           # not enough fresh video for a grounded window
        else:
            image_b64 = self._encode_frame()
            if not image_b64:
                return
        user_prompt = ("As you continue observing, what do you notice? Be factual — "
                       "describe only what is clearly visible.")
        if cosmos:
            # Plain question. Earlier lines are NOT shown to Cosmos: it copies any
            # text it is given (tested 2026-09-28). Repetition is handled below.
            user_prompt = ("Here are %d frames from the last %.0f seconds, oldest first. "
                           "What is in front of you right now?"
                           % (len(image_b64), WINDOW_GAP_S * (len(image_b64) - 1)))
        description = self._vlm_query(
            self._build_casual_prompt(),
            user_prompt,
            image_b64,
            max_tokens=150,
            temperature=0.5 if cosmos else 0.65,   # lower: fewer invented details
        )
        if description and cosmos:
            description = _clean_frame_line(description)
            with self._lock:
                recent = [e["description"] for e in list(self._frame_log)[-3:]]
            if description and any(_similar(description, r) for r in recent):
                # Near-repeat of a recent line: one retry with more variety.
                retry = self._vlm_query(self._build_casual_prompt(), user_prompt,
                                        image_b64, max_tokens=150, temperature=0.8)
                retry = _clean_frame_line(retry) if retry else None
                if retry and not any(_similar(retry, r) for r in recent):
                    description = retry
        if description:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            entry = {
                "timestamp": ts,
                "description": description,
                "model": self.model,
            }
            # Validate + publish atomically with stop() (it holds this lock).
            with self._lifecycle_lock:
                if self._cancelled():
                    return
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

        if not observations:
            logger.debug("[SceneNarrator:scene] No observations yet — skipping summary")
            return

        # Observations as "N s ago" lines, oldest first. Relative ages read more
        # naturally than ISO stamps, and a decide-then-write instruction with a
        # fixed opener stops Cosmos copying an observation as its "summary"
        # (tested 2026-09-28: variant C of three).
        now = datetime.now(timezone.utc)
        obs_lines = []
        for obs in observations:
            try:
                age = int((now - datetime.fromisoformat(obs["timestamp"])).total_seconds())
            except (KeyError, ValueError):
                continue
            if age <= SCENE_WINDOW_S:
                obs_lines.append(f"[{age} s ago] {obs['text']}")
        if not obs_lines:
            logger.debug("[SceneNarrator:scene] No recent observations - skipping summary")
            return
        parts = ["Your observations over the last couple of minutes (oldest first):\n"
                 + "\n".join(obs_lines)]
        # The previous report is deliberately NOT passed back in: tested
        # 2026-09-28, Cosmos carried a one-off hallucination from it into every
        # later report. Continuity comes from the observation window instead.
        parts.append("\nFirst decide what was consistent across the observations and "
                     "what changed; then write your report in 2-4 fresh sentences, "
                     "starting with \"Over the last couple of minutes\".")
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
            with self._lifecycle_lock:
                if self._cancelled():
                    return
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

        # Admission and firing are atomic with stop(). (The VLM gesture callback
        # is not wired to the robot today; YOLO Pose owns the shake trigger.)
        with self._lifecycle_lock:
            if self._gesture_callback and not self._cancelled():
                try:
                    self._gesture_callback("confirmed_squat")
                except Exception as e:
                    logger.error(f"[SceneNarrator:gesture] Callback error: {e}")


# ── Module-level singleton ──────────────────────────────────────────

_narrator: Optional[SceneNarrator] = None


def get_narrator() -> Optional[SceneNarrator]:
    return _narrator


def init_narrator(ollama_url=None, model=None, scene_context=None, **kwargs) -> SceneNarrator:
    global _narrator
    _narrator = SceneNarrator(ollama_url=ollama_url, model=model,
                              scene_context=scene_context, **kwargs)
    return _narrator

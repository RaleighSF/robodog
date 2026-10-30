"""Amazon Bedrock overwatch agent for re:Invent (ADR 0004, ADR 0011).

Same ask() contract and the same instructions + Go2 knowledge base as the
Foundry agent (cloud/agent). The one tool, `watchdog_telemetry`, runs the
read-only query operations in-process (backends.OPERATIONS), so the agent
can only read what the dashboard reads. Claude on Bedrock via the Anthropic
SDK's AnthropicBedrock client (IAM-signed InvokeModel on an inference profile)."""
import json
import os
import time

from backends import OPERATIONS, get_backend

MODEL = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-5-5")
REGION = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION", "us-east-1")
MAX_TURNS = 6
HERE = os.path.dirname(os.path.abspath(__file__))


def _instructions() -> str:
    base = os.environ.get("AGENT_DIR") or os.path.join(HERE, "..", "agent_assets")
    with open(os.path.join(base, "instructions.md")) as f:
        text = f.read()
    with open(os.path.join(base, "knowledge", "go2_health.md")) as f:
        return text + "\n\n---\n\n# Go2 knowledge base (background, not live data)\n\n" + f.read()


TOOL = {
    "name": "watchdog_telemetry",
    "description": ("Read-only telemetry for the Go2 robot dog (vitals, 12 joints, posture, findings, maneuvers, "
                    "detections). Cannot command the robot. Timespans look like 10m, 1h or 1d."),
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": sorted(OPERATIONS)},
            "window": {"type": "string", "description": "Lookback window, e.g. 15m or 1h (windowed operations only)"},
            "bin_size": {"type": "string", "description": "Bin size for series, e.g. 1m"},
        },
        "required": ["operation"],
    },
}


class BedrockAgent:
    def __init__(self):
        from anthropic import AnthropicBedrock
        self.client = AnthropicBedrock(aws_region=REGION)
        # The long, stable instructions are a cache breakpoint: each brief/ask
        # re-reads them at the cached rate instead of full price.
        self.system = [{"type": "text", "text": _instructions(), "cache_control": {"type": "ephemeral"}}]
        self.backend = get_backend()

    def _tool(self, args: dict) -> str:
        op = args.get("operation")
        if op not in OPERATIONS:
            return json.dumps({"error": f"unknown operation {op!r}"})
        fn, defaults = OPERATIONS[op]
        params = {k: str(args.get(k) or d) for k, d in defaults.items()}
        try:
            return json.dumps({"operation": op, "rows": self.backend.run(fn, params)}, default=str)[:60000]
        except ValueError as e:
            return json.dumps({"error": str(e)})

    def ask(self, question: str, timeout_s: float = 45) -> dict:
        t0 = time.time()
        messages = [{"role": "user", "content": question}]
        for _ in range(MAX_TURNS):
            remaining = timeout_s - (time.time() - t0)
            if remaining < 2:
                break
            # The deadline bounds each model call too (including SDK retries), so
            # the caller always gets control back with time to answer.
            msg = self.client.with_options(timeout=remaining, max_retries=0).messages.create(
                model=MODEL, max_tokens=2000, system=self.system, tools=[TOOL],
                output_config={"effort": "low"}, messages=messages)
            if msg.stop_reason == "refusal":
                return {"text": "I can't answer that one. Ask me about the dog's health or telemetry.",
                        "seconds": round(time.time() - t0, 1)}
            if msg.stop_reason != "tool_use":
                text = "".join(b.text for b in msg.content if b.type == "text").strip()
                return {"text": text, "seconds": round(time.time() - t0, 1)}
            messages.append({"role": "assistant", "content": msg.content})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "content": self._tool(b.input or {})}
                for b in msg.content if b.type == "tool_use"]})
        raise TimeoutError("agent did not finish in time")

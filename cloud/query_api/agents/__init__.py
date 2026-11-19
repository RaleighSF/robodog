"""Agent providers for the overwatch: same ask(question) -> text on every cloud.
Azure AI Foundry Agent Service for Ignite; Amazon Bedrock for re:Invent (ADR 0004)."""
import os


def get_agent():
    kind = os.environ.get("AGENT_PROVIDER", "azure").lower()
    if kind == "azure":
        from .azure import FoundryAgent
        return FoundryAgent()
    if kind == "aws":
        from .aws import BedrockAgent
        return BedrockAgent()
    raise ValueError(f"unknown AGENT_PROVIDER {kind!r}")

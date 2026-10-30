"""Amazon Bedrock agent for re:Invent - same ask() contract. Built for re:Invent (ADR 0004)."""


class BedrockAgent:
    def ask(self, question: str, timeout_s: float = 45) -> dict:
        raise NotImplementedError("Bedrock agent is built for re:Invent")

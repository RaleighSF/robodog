"""AWS backend for re:Invent - same operations and result shapes as ADX.
To be implemented over the S3 telemetry (Athena) or Timestream."""


class AWSBackend:
    def run(self, function_name: str, params: dict) -> list:
        raise NotImplementedError("AWS backend is built for re:Invent")

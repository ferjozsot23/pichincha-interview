"""AWS Lambda entry point: the same FastAPI app behind a Lambda Function URL.

The orchestrator and Bedrock client are created at import time (cold start) and reused
across invocations of the same execution environment.
"""

from mangum import Mangum

from .api import app

handler = Mangum(app, lifespan="off")

import os

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "qwen.qwen3-32b-v1:0")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock")  # "bedrock" | "offline"

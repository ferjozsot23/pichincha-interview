"""LLM backends. Every backend speaks the Bedrock Converse request/response shape.

`converse(system, messages, tools)` receives tool definitions as
{"name", "description", "input_schema"} and returns a Converse response dict
({"output": {"message": ...}, "stopReason": ...}).
"""

import json
import re
from typing import Protocol

from . import config


class LLMClient(Protocol):
    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> dict: ...


class BedrockConverseClient:
    """Amazon Bedrock Converse API via boto3 (credentials resolved by the standard AWS chain)."""

    def __init__(
        self,
        model_id: str = config.LLM_MODEL_ID,
        region: str = config.AWS_REGION,
        max_tokens: int = config.LLM_MAX_TOKENS,
    ):
        import boto3  # imported lazily so offline runs and tests don't need AWS libraries

        self.model_id = model_id
        self.max_tokens = max_tokens
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        return self._client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=messages,
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool["name"],
                            "description": tool["description"],
                            "inputSchema": {"json": tool["input_schema"]},
                        }
                    }
                    for tool in tools
                ]
            },
            inferenceConfig={"maxTokens": self.max_tokens},
        )


_CASE_PATTERN = re.compile(r"<case>\s*(.*?)\s*</case>", re.DOTALL)


def text_response(text: str) -> dict:
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn"}


def tool_use_response(name: str, args: dict, tool_use_id: str = "tool-1") -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": args}}],
            }
        },
        "stopReason": "tool_use",
    }


class OfflineLLM:
    """Deterministic stand-in for demos and tests: no network, no model.

    It calls the first offered tool, filling its arguments from the <case> block by
    property name. Missing required fields -> plain-text answer instead of a tool call.
    """

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        last = messages[-1]["content"]
        results = [block["toolResult"] for block in last if "toolResult" in block]
        if results:
            payload = results[-1]["content"][0]
            return text_response(f"Resultado: {json.dumps(payload.get('json', payload), ensure_ascii=False)}")

        case = _extract_case(messages[0])
        tool = tools[0]
        schema = tool["input_schema"]
        args = {key: case[key] for key in schema["properties"] if key in case}
        missing = [key for key in schema.get("required", []) if key not in args]
        if missing:
            return text_response(f"Faltan datos para continuar: {', '.join(missing)}")
        return tool_use_response(tool["name"], args)


def _extract_case(message: dict) -> dict:
    text = "".join(block.get("text", "") for block in message["content"])
    match = _CASE_PATTERN.search(text)
    return json.loads(match.group(1)) if match else {}

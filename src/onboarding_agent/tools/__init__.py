"""Onboarding tools plus a framework-agnostic registry the orchestrator can dispatch from.

Each tool module owns its SCHEMA (name, description, input_schema, output_schema).
`TOOLS` pairs every schema with a handler that returns the plain-dict contract, and
`tool_definitions()` gives the LLM-facing definitions (no handler, no output schema).
"""

from . import documentation, identity, risk
from .documentation import SUPPORTED_PRODUCTS, DocumentationResult, prepare_documentation
from .identity import CONFIDENCE_THRESHOLD, IdentityResult, verify_identity
from .risk import RiskResult, check_risk_lists

TOOLS: dict[str, dict] = {
    identity.SCHEMA["name"]: {
        **identity.SCHEMA,
        "handler": lambda args: verify_identity(args["document_id"]).to_dict(),
    },
    risk.SCHEMA["name"]: {
        **risk.SCHEMA,
        "handler": lambda args: check_risk_lists(args["name"], args["document_id"]).to_dict(),
    },
    documentation.SCHEMA["name"]: {
        **documentation.SCHEMA,
        "handler": lambda args: prepare_documentation(args["product"], args.get("client_data")).to_dict(),
    },
}


def tool_definitions() -> list[dict]:
    """Definitions to pass to the LLM (`tools=` parameter): name, description, input_schema."""
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS.values()
    ]


__all__ = [
    "CONFIDENCE_THRESHOLD",
    "SUPPORTED_PRODUCTS",
    "TOOLS",
    "DocumentationResult",
    "IdentityResult",
    "RiskResult",
    "check_risk_lists",
    "prepare_documentation",
    "tool_definitions",
    "verify_identity",
]

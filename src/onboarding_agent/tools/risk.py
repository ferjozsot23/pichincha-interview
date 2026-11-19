"""Tool 2: check_risk_lists(name, document_id) -> {"risk_level": "low|medium|high", "matches": [...]}."""

import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Literal

from .mock_data import WATCHLIST

RiskLevel = Literal["low", "medium", "high"]

_LEVEL_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class RiskResult:
    risk_level: RiskLevel
    matches: list[dict] = field(default_factory=list)

    @property
    def requires_escalation(self) -> bool:
        return self.risk_level == "high"

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_name(name: str) -> str:
    """Case-, accent- and whitespace-insensitive form, so 'MARÍA  lópez' == 'Maria Lopez'."""
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())


def check_risk_lists(name: str, document_id: str) -> RiskResult:
    """Mock screening against sanctions, PEP and internal fraud lists.

    - Document ID match: the entry's own severity applies (strong identifier).
    - Name-only match: capped at "medium", since it may be a homonym that needs review
      but should not block the client on its own.
    The overall level is the highest level across all matches.
    """
    normalized_name = _normalize_name(name or "")
    document_id = (document_id or "").strip()

    matches: list[dict] = []
    level: RiskLevel = "low"

    for entry in WATCHLIST:
        if document_id and entry["document_id"] == document_id:
            matched_on, entry_level = "document_id", entry["severity"]
        elif normalized_name and _normalize_name(entry["name"]) == normalized_name:
            matched_on, entry_level = "name", "medium"
        else:
            continue

        matches.append({"list": entry["list"], "matched_on": matched_on, "entry_name": entry["name"]})
        if _LEVEL_ORDER[entry_level] > _LEVEL_ORDER[level]:
            level = entry_level

    return RiskResult(risk_level=level, matches=matches)


SCHEMA = {
    "name": "check_risk_lists",
    "description": (
        "Screens a client against sanctions (OFAC), PEP and internal fraud lists. "
        "Returns risk_level (low/medium/high) and the matched entries; high requires escalation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Client's full name"},
            "document_id": {"type": "string", "description": "Client's cédula (10 digits)"},
        },
        "required": ["name", "document_id"],
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "risk_level": {"type": "string", "enum": list(_LEVEL_ORDER)},
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "list": {"type": "string"},
                        "matched_on": {"type": "string", "enum": ["document_id", "name"]},
                        "entry_name": {"type": "string"},
                    },
                    "required": ["list", "matched_on", "entry_name"],
                },
            },
        },
        "required": ["risk_level", "matches"],
    },
}

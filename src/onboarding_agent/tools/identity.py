"""Tool 1: verify_identity(document_id) -> {"verified": bool, "confidence": float}."""

import hashlib
from dataclasses import asdict, dataclass

from .mock_data import IDENTITY_REGISTRY

CONFIDENCE_THRESHOLD = 0.8

_VALID_PROVINCES = set(range(1, 25)) | {30}  # 30 = Ecuadorians registered abroad


@dataclass(frozen=True)
class IdentityResult:
    verified: bool
    confidence: float

    @property
    def requires_escalation(self) -> bool:
        return self.confidence < CONFIDENCE_THRESHOLD

    def to_dict(self) -> dict:
        return asdict(self)


def is_valid_cedula(document_id: str) -> bool:
    """Structural validation of an Ecuadorian cédula (10 digits, modulo-10 check digit)."""
    if len(document_id) != 10 or not document_id.isdigit():
        return False
    if int(document_id[:2]) not in _VALID_PROVINCES or int(document_id[2]) >= 6:
        return False

    total = 0
    for i, char in enumerate(document_id[:9]):
        product = int(char) * (2 if i % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    return (10 - total % 10) % 10 == int(document_id[9])


def _deterministic_confidence(document_id: str) -> float:
    """Stable confidence in [0.85, 0.99] so unknown documents behave the same on every run."""
    digest = int(hashlib.sha256(document_id.encode()).hexdigest(), 16)
    return round(0.85 + (digest % 15) / 100, 2)


def verify_identity(document_id: str) -> IdentityResult:
    """Mock identity check against the civil registry.

    A malformed document never reaches the registry: it comes back unverified with
    zero confidence, which forces escalation.
    """
    document_id = (document_id or "").strip()
    if not is_valid_cedula(document_id):
        return IdentityResult(verified=False, confidence=0.0)

    known = IDENTITY_REGISTRY.get(document_id)
    if known is not None:
        return IdentityResult(**known)
    return IdentityResult(verified=True, confidence=_deterministic_confidence(document_id))


SCHEMA = {
    "name": "verify_identity",
    "description": (
        "Verifies a client's identity against the civil registry. "
        f"Returns verified and confidence (0-1); confidence below {CONFIDENCE_THRESHOLD} requires escalation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "description": "Client's cédula (10 digits)", "pattern": "^[0-9]{10}$"},
        },
        "required": ["document_id"],
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "verified": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["verified", "confidence"],
    },
}

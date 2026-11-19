"""In-memory fixtures that stand in for the external services behind each tool.

Every document ID below is a structurally valid Ecuadorian cédula (province code,
third digit and modulo-10 check digit), so they pass format validation and
exercise the business paths instead of failing early.
"""

# Identity provider (e.g. Registro Civil) responses for known documents.
# Documents not listed here get a deterministic high-confidence match.
IDENTITY_REGISTRY: dict[str, dict] = {
    "1712345675": {"verified": True, "confidence": 0.97},  # clean match
    "0912345675": {"verified": True, "confidence": 0.72},  # weak biometric match -> escalate
    "0102030400": {"verified": False, "confidence": 0.35},  # data mismatch -> escalate
}

# Sanctions / PEP / internal watchlists.
WATCHLIST: list[dict] = [
    {
        "list": "OFAC_SDN",
        "name": "Carlos Andres Mendoza Rivera",
        "document_id": "1700000019",
        "severity": "high",
    },
    {
        "list": "PEP",
        "name": "Maria Fernanda Lopez Vega",
        "document_id": "0923456784",
        "severity": "medium",
    },
    {
        "list": "INTERNAL_FRAUD",
        "name": "Jorge Luis Paredes Castro",
        "document_id": "1711111110",
        "severity": "high",
    },
]

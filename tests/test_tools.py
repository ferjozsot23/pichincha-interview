import pytest

from onboarding_agent.tools import (
    TOOLS,
    check_risk_lists,
    prepare_documentation,
    tool_definitions,
    verify_identity,
)
from onboarding_agent.tools.identity import is_valid_cedula


# --- verify_identity ---------------------------------------------------------

def test_verify_identity_contract_shape():
    assert set(verify_identity("1712345675").to_dict()) == {"verified", "confidence"}


def test_verify_identity_high_confidence_does_not_escalate():
    result = verify_identity("1712345675")
    assert result.verified and result.confidence == 0.97
    assert not result.requires_escalation


def test_verify_identity_low_confidence_escalates():
    result = verify_identity("0912345675")
    assert result.verified and result.confidence < 0.8
    assert result.requires_escalation


@pytest.mark.parametrize("document_id", ["", "123", "abcdefghij", "1712345670", "9912345675"])
def test_verify_identity_invalid_document_fails_closed(document_id):
    result = verify_identity(document_id)
    assert result.to_dict() == {"verified": False, "confidence": 0.0}
    assert result.requires_escalation


def test_verify_identity_unknown_valid_document_is_deterministic():
    first, second = verify_identity("1700000019"), verify_identity("1700000019")
    assert first == second
    assert 0.85 <= first.confidence <= 0.99


def test_cedula_checksum():
    assert is_valid_cedula("1712345675")
    assert not is_valid_cedula("1712345676")


# --- check_risk_lists --------------------------------------------------------

def test_risk_clean_client_is_low():
    result = check_risk_lists("Ana Torres", "1712345675")
    assert result.to_dict() == {"risk_level": "low", "matches": []}
    assert not result.requires_escalation


def test_risk_sanctions_document_match_is_high():
    result = check_risk_lists("Otro Nombre", "1700000019")
    assert result.risk_level == "high"
    assert result.matches[0]["list"] == "OFAC_SDN"
    assert result.requires_escalation


def test_risk_pep_is_medium():
    result = check_risk_lists("Maria Fernanda Lopez Vega", "0923456784")
    assert result.risk_level == "medium"
    assert not result.requires_escalation


def test_risk_name_only_match_is_capped_at_medium_and_accent_insensitive():
    result = check_risk_lists("  CARLOS Andrés mendoza RIVERA ", "1712345675")
    assert result.risk_level == "medium"
    assert result.matches[0]["matched_on"] == "name"


# --- prepare_documentation ---------------------------------------------------

def _codes(result):
    return [d.code for d in result.required_documents]


def test_savings_account_basic_documents():
    assert _codes(prepare_documentation("cuenta_ahorros", {})) == [
        "ID_COPY",
        "PROOF_OF_ADDRESS",
        "ACCOUNT_AGREEMENT",
    ]


def test_credit_product_for_self_employed_requires_tax_documents():
    codes = _codes(prepare_documentation("credito_consumo", {"employment_type": "independiente"}))
    assert {"CREDIT_BUREAU_AUTH", "RUC", "TAX_RETURNS"} <= set(codes)
    assert "PAYROLL_SLIPS" not in codes


def test_pep_and_foreign_client_documents():
    codes = _codes(prepare_documentation("Cuenta_Ahorros", {"is_pep": True, "is_foreign": True}))
    assert codes[0] == "PASSPORT_COPY"
    assert {"MIGRATORY_STATUS", "PEP_DECLARATION"} <= set(codes)


def test_unsupported_product_raises():
    with pytest.raises(ValueError, match="Unsupported product"):
        prepare_documentation("crypto_wallet", {})


# --- registry ----------------------------------------------------------------

def test_registry_handlers_return_plain_dicts():
    assert TOOLS["verify_identity"]["handler"]({"document_id": "1712345675"})["verified"] is True
    assert TOOLS["check_risk_lists"]["handler"]({"name": "X", "document_id": "1711111110"})["risk_level"] == "high"
    docs = TOOLS["prepare_documentation"]["handler"]({"product": "tarjeta_credito"})
    assert docs["required_documents"][0]["code"] == "ID_COPY"


# --- schemas -----------------------------------------------------------------

jsonschema = pytest.importorskip("jsonschema")

_SAMPLE_CALLS = {
    "verify_identity": [{"document_id": "1712345675"}, {"document_id": "0102030400"}],
    "check_risk_lists": [
        {"name": "Ana Torres", "document_id": "1712345675"},
        {"name": "Maria Fernanda Lopez Vega", "document_id": "1700000019"},
    ],
    "prepare_documentation": [
        {"product": "credito_hipotecario", "client_data": {"employment_type": "independiente", "is_pep": True}},
    ],
}


@pytest.mark.parametrize("tool_name", list(TOOLS))
def test_schemas_are_valid_and_outputs_match_contract(tool_name):
    tool = TOOLS[tool_name]
    jsonschema.Draft202012Validator.check_schema(tool["input_schema"])
    jsonschema.Draft202012Validator.check_schema(tool["output_schema"])
    for args in _SAMPLE_CALLS[tool_name]:
        jsonschema.validate(args, tool["input_schema"])
        jsonschema.validate(tool["handler"](args), tool["output_schema"])


def test_input_schema_rejects_malformed_document_but_tool_still_fails_closed():
    tool = TOOLS["verify_identity"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"document_id": "bad"}, tool["input_schema"])
    jsonschema.validate(tool["handler"]({"document_id": "bad"}), tool["output_schema"])


def test_tool_definitions_expose_only_llm_fields():
    defs = tool_definitions()
    assert [d["name"] for d in defs] == ["verify_identity", "check_risk_lists", "prepare_documentation"]
    assert all(set(d) == {"name", "description", "input_schema"} for d in defs)
